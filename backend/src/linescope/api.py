from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from .agent_input import AgentInput, ConversationStore
from .approvals import HumanApproval
from .canonical import strict_json
from .database import Database
from .equipment_command import EquipmentCommandPrepare
from .execute import HumanExecute
from .http_logging import RequestMiddleware
from .llm import OllamaClient
from .logging import EventLogger, request_context
from .maintenance_command import MaintenanceCommandPrepare
from .proposals import REQUEST_ROLES, ProposalError, ProposalStore
from .read_agent import ReadAgent
from .reads import ReadTools, ToolError, json_value
from .settings import Settings
from .snapshot import CATEGORIES
from .tools import ToolDispatcher
from .update_intent import equipment_state_command, maintenance_plan_command


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
    settings = settings or Settings.env()
    database = database or Database(settings)
    events = event_logger or EventLogger(settings.log_level)

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
    app.state.read_tools = ReadTools(database)
    equipment_prepare = EquipmentCommandPrepare(database, event_logger=events)
    maintenance_prepare = MaintenanceCommandPrepare(database, event_logger=events)
    human_approval = HumanApproval(database, event_logger=events)
    human_execute = HumanExecute(database, settings, event_logger=events)

    conversations = conversations or ConversationStore()
    if llm is None and settings.llm_model:
        llm = OllamaClient(base_url=settings.llm_base_url, model=settings.llm_model)
    read_agent = (
        ReadAgent(ToolDispatcher(database), llm, event_logger=events) if llm is not None else None
    )
    app.state.conversations = conversations
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
            data = ProposalStore(database).get(request.state.execution_context, request_id)
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
                human_approval.approve,
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
                human_approval.reject,
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
                human_execute.execute, request.state.execution_context, request_id
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
            observation = await run_in_threadpool(human_execute.observe_current, result)
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

    async def prepared_response(request, context, saved):
        try:
            data = await run_in_threadpool(
                ProposalStore(database).get, context, saved.update_request_id
            )
        except ProposalError as error:
            # The proposal is already durable. A response-read failure must not
            # hide its identity or imply rollback of the saved request.
            return response(
                request,
                json_value(
                    {
                        "update_request_id": saved.update_request_id,
                        "approval_id": saved.approval_id,
                        "status": saved.status,
                    }
                ),
                code=error.code,
                status_code=error_status(error.code),
            )
        return response(
            request,
            json_value(data),
            answer="保存済みの変更要求を返します。状態とSnapshotを確認してください。"
            if saved.replayed
            else "変更準備を作成しました。業務データや設備の現在状態は変更していません。人間による承認と実行が必要です。",
        )

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
            context = request.state.execution_context
            if request.headers.get("idempotency-key") is not None:
                saved = await run_in_threadpool(
                    ProposalStore(database).find_by_retry,
                    context,
                    incoming.retry_key,
                    agent_input_hash=incoming.input_hash,
                )
                if saved is not None:
                    category = CATEGORIES[saved.snapshot.data["targets"][0]["target_type"]]
                    if context.role not in REQUEST_ROLES[category]:
                        raise ToolError(
                            "AUTHORIZATION_DENIED", "Prepare retry permission is required"
                        )
                    return await prepared_response(request, context, saved)
            previous = (
                conversations.get(context, incoming.context_id)["messages"]
                if incoming.context_id
                else []
            )
            if equipment_state_command(incoming) is not None:
                saved = await run_in_threadpool(equipment_prepare.run, context, incoming)
                return await prepared_response(request, context, saved)
            if maintenance_plan_command(incoming) is not None:
                saved = await run_in_threadpool(maintenance_prepare.run, context, incoming)
                return await prepared_response(request, context, saved)
            if read_agent is None:
                raise ToolError("DEPENDENCY_UNAVAILABLE", "LLM is not configured")
            result = await run_in_threadpool(
                read_agent.run,
                context,
                incoming,
                previous_messages=previous if incoming.context_id else None,
            )
            context_id = incoming.context_id
            if result.needs_input or context_id:
                stored = {"messages": [*previous, incoming.message]}
                if context_id:
                    conversations.update(context, context_id, stored)
                else:
                    context_id = conversations.create(context, stored)
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
