"""Catalog-bound readonly requests. Message text is never executable input here."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from ..application.reads import ReadResult, ToolError
from ..domain.canonical import normalize_uuid
from .agent_tools import AgentToolSession
from .grounded_answer import build_answer
from .read_catalog import BUSINESS_FIELDS, CATALOG_VERSION, SUBJECT_COUNTS, TERMS
from .read_scope import ReadScope
from .scope_check import FIELD_MEANINGS
from .scoped_reads import CollectedRead, collect_scope

DESTINATIONS = {"registered_comparison": "comparison", "document_excerpt": "documents"}


def catalog():
    return {
        "version": CATALOG_VERSION,
        "entries": [
            {
                "key": key,
                "label": TERMS[key][0],
                "description": FIELD_MEANINGS[key],
                "min_targets": 1 if key in DESTINATIONS else SUBJECT_COUNTS[key][0],
                "max_targets": 1 if key in DESTINATIONS else SUBJECT_COUNTS[key][1],
                "action": "OPEN_WORKSPACE" if key in DESTINATIONS else "EXECUTE",
                **({"destination": DESTINATIONS[key]} if key in DESTINATIONS else {}),
            }
            for key in BUSINESS_FIELDS
        ],
    }


def parse_selection(value):
    if type(value) is not dict:
        raise ValueError("Read selection must be an object")
    if value == {"operation": "CATALOG"}:
        return dict(value)
    if set(value) != {"operation", "catalog_version", "key", "targets"}:
        raise ValueError("Invalid explicit read fields")
    key = value["key"]
    if (
        value["operation"] != "EXECUTE"
        or value["catalog_version"] != CATALOG_VERSION
        or type(key) is not str
        or key not in BUSINESS_FIELDS
        or key in DESTINATIONS
        or type(value["targets"]) is not list
    ):
        raise ValueError("Invalid explicit read selection")
    minimum, maximum = SUBJECT_COUNTS[key]
    if not minimum <= len(value["targets"]) <= maximum:
        raise ValueError("Invalid target count")
    targets = []
    for target in value["targets"]:
        if (
            type(target) is not dict
            or set(target) != {"entity_type", "entity_id"}
            or target["entity_type"] != "Equipment"
        ):
            raise ValueError("Invalid explicit target")
        targets.append(
            {"entity_type": "Equipment", "entity_id": normalize_uuid(target["entity_id"])}
        )
    if len({target["entity_id"] for target in targets}) != len(targets):
        raise ValueError("Duplicate targets")
    return {**value, "targets": targets}


def selection_required():
    from .read_agent import ReadAgentResult

    return ReadAgentResult(
        "参照観点はまだ確定していません。対象と調べる項目を選んでください。該当する項目がなければ「該当する観点がない」を選べます。",
        (),
        (),
        (),
        True,
        {
            "version": 1,
            "facts": [],
            "unavailable": [],
            "scope": [],
            "read_outcome": "SELECTION_REQUIRED",
        },
        read_catalog=catalog(),
    )


def verified_result(observation):
    """Validate the existing result/evidence contract before any payload is public."""
    data, evidence = observation.result.data, observation.result.evidence
    if not isinstance(data, dict) or not isinstance(evidence, dict):
        return False
    if not evidence.get("source") or evidence.get("tool") != observation.tool:
        return False
    if evidence.get("tool_call_id", observation.tool_call_id) != observation.tool_call_id:
        return False
    at = evidence.get("observed_at", evidence.get("graph_observed_at"))
    try:
        if (
            not isinstance(at, str)
            or datetime.fromisoformat(at.replace("Z", "+00:00")).tzinfo is None
        ):
            return False
    except ValueError:
        return False
    arguments = observation.arguments or {}
    if observation.tool in {"get_equipment", "get_equipment_state"}:
        if data.get("equipment_id") != arguments.get("equipment_id"):
            return False
    if observation.tool == "get_equipment_state" and data.get("state_code") not in {
        "RUNNING",
        "STOPPED",
        "UNDER_MAINTENANCE",
        "UNKNOWN",
    }:
        return False
    if observation.tool.startswith("search_") and arguments.get("filter", {}).get("equipment_id"):
        items = data.get("items")
        if type(items) is not list or any(
            type(item) is not dict
            or item.get("equipment_id") != arguments["filter"]["equipment_id"]
            for item in items
        ):
            return False
    if "target" in arguments and data.get("target") != arguments["target"]:
        return False
    if "targets" in arguments:
        # The common-dependency DTO sorts roots canonically. Order is not identity.
        actual, expected = data.get("targets"), arguments["targets"]
        if type(actual) is not list or any(
            type(item) is not dict or set(item) != {"entity_type", "entity_id"} for item in actual
        ):
            return False
        actual_roots = sorted((r["entity_type"], r["entity_id"]) for r in actual)
        expected_roots = sorted((r["entity_type"], r["entity_id"]) for r in expected)
        if actual_roots != expected_roots:
            return False
    return True


class ExplicitReads:
    def __init__(self, dispatcher, *, event_logger=None, deadline_seconds=60):
        self.dispatcher, self.events, self.deadline_seconds = (
            dispatcher,
            event_logger,
            deadline_seconds,
        )

    def run(self, context, request):
        from .read_agent import ReadAgentResult

        selection = parse_selection(request.read_selection)
        if selection["operation"] == "CATALOG":
            return ReadAgentResult(
                "調べる項目と対象を選んでください。元の質問への回答ではありません。",
                (),
                (),
                (),
                False,
                {"version": 1, "facts": [], "unavailable": [], "scope": []},
                read_catalog=catalog(),
            )
        key, targets = selection["key"], selection["targets"]
        session = AgentToolSession(
            context,
            replace(request, message="明示された登録照会", read_selection=None),
            self.dispatcher,
            event_logger=self.events,
            deadline_seconds=self.deadline_seconds,
        )
        observations, trace, errors = [], [], []
        for target in targets:
            call_id = str(uuid4())
            arguments = {"equipment_id": target["entity_id"]}
            try:
                result = session.run("get_equipment", arguments, tool_call_id=call_id)
                if not isinstance(result, ReadResult):
                    raise ToolError("INTERNAL_ERROR", "Invalid identity result")
                if result.data.get("equipment_id") != target["entity_id"]:
                    raise ToolError("INTERNAL_ERROR", "Identity result does not match selection")
                observations.append(CollectedRead(call_id, "get_equipment", result, arguments))
                trace.append(
                    {"tool_call_id": call_id, "tool": "get_equipment", "code": "OK", "attempt": 1}
                )
            except ToolError as error:
                errors.append(error.as_dict())
                trace.append(
                    {
                        "tool_call_id": call_id,
                        "tool": "get_equipment",
                        "code": error.code,
                        "attempt": 1,
                    }
                )
        scope = ReadScope(
            (BUSINESS_FIELDS[key],),
            tuple({"entity_type": "Equipment", "reference": t["entity_id"]} for t in targets),
            requested_fields=(key,),
        )
        if not errors:
            values, attempts, failures = collect_scope(
                scope,
                session,
                resolved_targets=targets,
                selected_fields=(key,),
            )
            observations.extend(values)
            trace.extend(attempts)
            errors.extend(failures)
        if any(not verified_result(item) for item in observations):
            observations = []
            errors.append(
                {
                    "code": "INTERNAL_ERROR",
                    "message": "Read result or evidence could not be verified",
                    "details": {},
                }
            )
        if any(
            error["code"] in {"AUTHORIZATION_DENIED", "AUTHENTICATION_REQUIRED"} for error in errors
        ):
            observations = []
        # Identity verifies the selected target; it does not authorize publication
        # of every attribute returned by the underlying identity read.
        observations = [
            replace(
                item,
                result=ReadResult(
                    {
                        k: v
                        for k, v in item.result.data.items()
                        if k in {"equipment_id", "equipment_name", "equipment_code", key}
                    },
                    item.result.evidence,
                ),
            )
            if item.tool == "get_equipment"
            else item
            for item in observations
        ]
        answer, sections = build_answer(
            tuple(observations),
            scope=scope,
            errors=tuple(errors),
            question=TERMS[key][0],
            selected_fields=(key,),
            identity_verified=True,
        )
        if any(
            item["code"] in {"INVALID_RESULT", "UNVERIFIABLE_RESULT", "NO_PUBLIC_RENDERER"}
            for item in sections["unavailable"]
        ):
            observations = []
            errors.append(
                {
                    "code": "INTERNAL_ERROR",
                    "message": "Public result format could not be verified",
                    "details": {},
                }
            )
            answer, sections = build_answer(
                (),
                scope=scope,
                errors=tuple(errors),
                question=TERMS[key][0],
                selected_fields=(key,),
            )
        sections["read_outcome"] = (
            "TARGET_NOT_FOUND"
            if errors and all(e["code"] == "TARGET_NOT_FOUND" for e in errors)
            else "INCOMPLETE"
            if errors
            else "EXPLICIT_READ"
        )
        return ReadAgentResult(
            answer,
            tuple(observations),
            tuple(trace),
            tuple(errors),
            False,
            sections,
            read_selection={
                "key": key,
                "label": TERMS[key][0],
                "description": FIELD_MEANINGS[key],
                "catalog_version": CATALOG_VERSION,
                "targets": targets,
                "original_question": request.message,
                "target_labels": [
                    f"{o.result.data.get('equipment_name', '設備')} · {o.result.data.get('equipment_code', '')}"
                    for o in observations
                    if o.tool == "get_equipment"
                ],
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
