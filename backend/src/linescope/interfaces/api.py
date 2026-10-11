from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from ..agent.agent_input import AgentInput
from ..application.agent_service import PreparedAgentResult
from ..application.proposals import ProposalError
from ..application.reads import ToolError, json_value
from ..bootstrap import build_api_services
from ..domain.canonical import strict_json
from ..logging import request_context
from .http_logging import RequestMiddleware


def response(
    request,
    data=None,
    code=None,
    status_code=200,
    *,
    partial=False,
    answer=None,
    evidence=None,
    errors=None,
    warnings=None,
    context_id=None,
):
    request.state.result_code = code or "OK"
    request.state.response_status = "error" if code else "partial" if partial else "ok"
    return JSONResponse(
        {
            "request_id": request.state.request_id,
            "context_id": context_id,
            "status": request.state.response_status,
            "answer": answer,
            "data": data or {},
            "evidence": evidence or {},
            "warnings": warnings or [],
            "errors": errors
            if errors is not None
            else [{"code": code, "message": code, "details": {}}]
            if code
            else [],
        },
        status_code=status_code,
    )


def create_app(settings=None, database=None, event_logger=None, *, llm=None, conversations=None):
    services = build_api_services(
        settings, database, event_logger, llm=llm, conversations=conversations
    )
    settings, database, events = services.settings, services.database, services.events

    @asynccontextmanager
    async def lifespan(app):
        with request_context(uuid4()):
            events.emit("service.started", component="api", outcome="success", result_code="OK")
        try:
            yield
        finally:
            with request_context(uuid4()):
                events.emit("service.stopped", component="api", outcome="success", result_code="OK")

    app = FastAPI(
        title="LineScope", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.database = database
    app.state.read_tools = services.reads
    app.state.conversations = services.conversations
    app.state.events = events
    app.add_middleware(RequestMiddleware, settings=settings, events=events, response=response)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return response(request, code="HTTP_ERROR", status_code=error.status_code)

    @app.get("/health")
    def health(request: Request):
        return response(request, {"service": "linescope", "alive": True})

    @app.get("/health/ready")
    def ready(request: Request):
        try:
            if not database.check():
                return response(request, code="DEPENDENCY_UNAVAILABLE", status_code=503)
        except psycopg.Error:
            return response(request, code="DEPENDENCY_UNAVAILABLE", status_code=503)
        return response(request, {"service": "linescope", "postgresql": "available"})

    @app.get("/update-requests/{request_id}")
    def update_request(request: Request, request_id: str):
        try:
            data = services.proposals.get(request.state.execution_context, request_id)
        except ProposalError as error:
            status = {
                "INVALID_ARGUMENT": 400,
                "AUTHENTICATION_REQUIRED": 401,
                "AUTHORIZATION_DENIED": 403,
                "TARGET_NOT_FOUND": 404,
                "RESOURCE_BUSY": 503,
                "DEPENDENCY_UNAVAILABLE": 503,
            }.get(error.code, 500)
            return response(request, code=error.code, status_code=status)
        return response(request, json_value(data))

    @app.post("/approvals/{approval_id}/approve")
    async def approve(request: Request, approval_id: str):
        try:
            if (
                request.headers.get("content-type", "").split(";")[0].strip().lower()
                != "application/json"
            ):
                raise ValueError("JSON required")
            body = strict_json(await request.body())
            if type(body) is not dict or set(body) != {"snapshot_hash"}:
                raise ValueError("Only Snapshot hash is accepted")
        except (ValueError, TypeError):
            return response(request, code="INVALID_ARGUMENT", status_code=400)
        try:
            result = await run_in_threadpool(
                services.approval.approve,
                request.state.execution_context,
                approval_id,
                body["snapshot_hash"],
            )
        except ProposalError as error:
            code = "APPROVAL_HASH_MISMATCH" if error.code == "APPROVAL_MISMATCH" else error.code
            return response(request, code=code, status_code=error_status(code))
        return response(request, json_value(result))

    @app.post("/approvals/{approval_id}/reject")
    async def reject(request: Request, approval_id: str):
        if await request.body():
            return response(request, code="INVALID_ARGUMENT", status_code=400)
        try:
            result = await run_in_threadpool(
                services.approval.reject,
                request.state.execution_context,
                approval_id,
            )
        except ProposalError as error:
            return response(request, code=error.code, status_code=error_status(error.code))
        return response(request, json_value(result))

    @app.post("/update-requests/{request_id}/execute")
    async def execute(request: Request, request_id: str):
        if await request.body():
            return response(request, code="INVALID_ARGUMENT", status_code=400)
        try:
            result = await run_in_threadpool(
                services.execute.execute, request.state.execution_context, request_id
            )
        except ProposalError as error:
            return response(request, code=error.code, status_code=error_status(error.code))
        data = {
            "update_request_id": str(UUID(request_id)),
            "approval_id": result["approval_id"],
            "status": "COMPLETED",
            "approval_status": "CONSUMED",
            "execution_result": result,
        }
        try:
            observation = await run_in_threadpool(services.execute.observe_current, result)
        except Exception as error:
            code = error.code if isinstance(error, ProposalError) else "INTERNAL_ERROR"
            if not isinstance(error, ProposalError):
                events.emit(
                    "runtime.diagnostic",
                    component="proposal",
                    outcome="failure",
                    result_code=code,
                    level="ERROR",
                    error=error,
                    update_request_id=request_id,
                )
            data.update(current_snapshot=None, current_versions=None, observed_at=None)
            return response(
                request,
                json_value(data),
                partial=True,
                warnings=[
                    {
                        "code": code,
                        "message": "Current values could not be observed; execution is completed.",
                        "details": {},
                    }
                ],
            )
        data.update(observation)
        return response(request, json_value(data))

    @app.post("/agent")
    async def agent(request: Request):
        received_at = datetime.now(timezone.utc)
        try:
            if (
                request.headers.get("content-type", "").split(";")[0].strip().lower()
                != "application/json"
                or len(request.headers.getlist("idempotency-key")) > 1
            ):
                raise ToolError(
                    "INVALID_ARGUMENT", "JSON request and a single retry key are required"
                )
            incoming = AgentInput.parse(
                request.state.execution_context,
                await request.body(),
                received_at=received_at,
                idempotency_key=request.headers.get("idempotency-key"),
            )
            outcome = await run_in_threadpool(
                services.agent.run,
                request.state.execution_context,
                incoming,
                retry_requested=request.headers.get("idempotency-key") is not None,
            )
            if isinstance(outcome, PreparedAgentResult):
                if outcome.error_code:
                    return response(
                        request,
                        json_value(outcome.data),
                        code=outcome.error_code,
                        status_code=error_status(outcome.error_code),
                    )
                return response(
                    request,
                    json_value(outcome.data),
                    answer="保存済みの変更要求を返します。状態とSnapshotを確認してください。"
                    if outcome.replayed
                    else "変更準備を作成しました。業務データや設備の現在状態は変更していません。人間による承認と実行が必要です。",
                )
            result, context_id = outcome.analysis, outcome.context_id
            data = {
                "needs_input": result.needs_input,
                "tool_results": [
                    {"tool_call_id": item.tool_call_id, "tool": item.tool, "data": item.result.data}
                    for item in result.observations
                ],
                "tool_trace": list(result.trace),
            }
            if result.needs_input:
                data.update(candidates=[], missing_fields=["target_identifier"])
            evidence = {
                "tool_results": [
                    {"tool_call_id": item.tool_call_id, "tool": item.tool, **item.result.evidence}
                    for item in result.observations
                ]
            }
            if result.errors and not result.needs_input and not result.observations:
                code = result.errors[0]["code"]
                return response(
                    request,
                    data,
                    code=code,
                    status_code=error_status(code),
                    errors=list(result.errors),
                    evidence=evidence,
                    context_id=context_id,
                )
            return response(
                request,
                data,
                answer=result.answer,
                evidence=evidence,
                context_id=context_id,
                partial=bool(result.errors and result.observations),
                warnings=list(result.errors),
            )
        except (ProposalError, ToolError) as error:
            data = {}
            for key in ("update_request_id", "approval_id"):
                value = getattr(error, "details", {}).get(key)
                if type(value) is str:
                    try:
                        data[key] = str(UUID(value))
                    except ValueError:
                        pass
            return response(request, data, code=error.code, status_code=error_status(error.code))

    return app


def error_status(code):
    return {
        "INVALID_ARGUMENT": 400,
        "AUTHENTICATION_REQUIRED": 401,
        "AUTHORIZATION_DENIED": 403,
        "TARGET_NOT_FOUND": 404,
        "TARGET_AMBIGUOUS": 409,
        "DUPLICATE_REQUEST": 409,
        "CONTEXT_EXPIRED": 409,
        "INVALID_UPDATE_STATE": 409,
        "APPROVAL_HASH_MISMATCH": 409,
        "VERSION_CONFLICT": 409,
        "CREATE_CONFLICT": 409,
        "APPROVAL_INVALIDATED": 409,
        "APPROVAL_ALREADY_CONSUMED": 409,
        "APPROVAL_EXPIRED": 410,
        "BUSINESS_RULE_VIOLATION": 422,
        "RESOURCE_BUSY": 503,
        "DEPENDENCY_UNAVAILABLE": 503,
        "AGENT_LIMIT_REACHED": 503,
    }.get(code, 500)
