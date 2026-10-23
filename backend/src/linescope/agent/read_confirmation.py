"""Read-scope clarification, separate from Prepare and from model-written facts."""

from dataclasses import replace

from ..application.reads import ToolError
from ..domain.canonical import canonical_hash
from .answer_text import public_answer
from .equipment_reference import question_messages, selected_reference, unresolved_selection
from .grounded_answer import build_answer
from .read_catalog import (
    BUSINESS_FIELDS,
    CATALOG_VERSION,
    FIELD_MEANINGS,
    definitions_answer,
    literal_reads,
    subjects_sufficient,
    unbound_attribute,
)
from .read_scope import ReadScope, classify
from .scoped_reads import collect_scope


def original_hash(request):
    return canonical_hash({"message": request.message, "as_of": request.explicit_as_of})


def _result(
    scope,
    request,
    observations,
    trace,
    errors,
    *,
    clarification=None,
    pending=None,
    identity_verified=False,
):
    from .read_agent import ReadAgentResult

    answer, sections = build_answer(
        observations,
        scope=scope,
        errors=errors,
        question=question_messages(request.message)[-1]["content"],
        identification_only=clarification is not None,
        identity_verified=identity_verified,
    )
    sections["read_outcome"] = (
        "TARGET_REQUIRED"
        if scope.scope_issue == "TARGET_REQUIRED"
        else "CONFIRM"
        if clarification
        else "TARGET_AMBIGUOUS"
        if any(e["code"] == "TARGET_AMBIGUOUS" for e in errors)
        else "TARGET_NOT_FOUND"
        if errors and all(e["code"] == "TARGET_NOT_FOUND" for e in errors)
        else "INCOMPLETE"
        if errors
        else "UNVERIFIABLE"
        if scope.scope_issue == "UNVERIFIABLE"
        else "UNSUPPORTED"
        if "UNSUPPORTED" in scope.topics or scope.scope_issue == "UNSUPPORTED"
        else "TARGET_REQUIRED"
        if not subjects_sufficient(scope)
        else "UNVERIFIABLE"
        if scope.scope_issue
        else "AUTO"
    )
    if request.explicit_as_of and not clarification and observations:
        note = "指定時刻について現在登録情報を評価しています。当時の状態の完全復元ではありません。"
        answer = note + "\n" + answer
        sections["unavailable"].append(
            {"code": "CURRENT_REGISTRATION_ONLY", "text": note, "references": []}
        )
    if clarification:
        sections["facts"] = []  # Do not mistake identification for an answer.
        sections["unavailable"] = []
        answer = "質問の解釈を確認してください。照会結果はまだ取得していません。"
    return ReadAgentResult(
        answer,
        observations,
        trace,
        errors,
        scope.scope_issue == "TARGET_REQUIRED"
        or bool(clarification and clarification["status"] == "PENDING")
        or (not subjects_sufficient(scope) and "UNSUPPORTED" not in scope.topics and not errors)
        or any(row["code"] == "TARGET_AMBIGUOUS" for row in errors),
        sections,
        clarification,
        pending,
    )


def interpreted_read(agent, request, session, previous):
    # Explicit structured comparison remains on its existing validated route.
    if set(session.schemas()) == {"compare_registered_inputs"}:
        return None
    candidates = literal_reads(request.message)
    literal = candidates[0] if len(candidates) == 1 else None
    resolved = None
    if (
        len(candidates) > 1
        and not request.explicit_as_of
        and all(item.subject for item in candidates)
        and len({(item.field, item.kind, item.predicate_value) for item in candidates}) == 1
    ):
        observations, trace, failures, choices = [], [], [], {}
        for candidate in candidates:
            targets = []
            values, attempts, errors = collect_scope(
                candidate.scope(), session, identification_only=True, identified_targets=targets
            )
            observations.extend(values)
            trace.extend(attempts)
            if errors and any(error["code"] != "TARGET_NOT_FOUND" for error in errors):
                failures.extend(errors)
                break  # An incomplete candidate cannot be discarded as a non-match.
            if not errors and len(targets) == 1:
                key = (targets[0]["entity_type"], targets[0]["entity_id"])
                choices[key] = (candidate, targets)
        if not failures and len(choices) == 1:
            # Equivalent parses resolved to the same operation on the same real ID.
            literal, targets = next(iter(choices.values()))
            resolved = (tuple(observations), tuple(trace), (), targets)
        else:
            if not failures:
                failures = [
                    {
                        "code": "TARGET_AMBIGUOUS" if choices else "TARGET_NOT_FOUND",
                        "message": "Literal target selection is required"
                        if choices
                        else "No literal target found",
                        "details": {},
                    }
                ]
            scope = ReadScope(
                (BUSINESS_FIELDS[candidates[0].field],),
                tuple(
                    {"entity_type": "Equipment", "reference": item.subject} for item in candidates
                ),
                requested_fields=(candidates[0].field,),
                validation_stage="LITERAL_TARGETS",
            )
            return _result(scope, request, tuple(observations), tuple(trace), tuple(failures))
    if literal and literal.kind == "definition":
        from .read_agent import ReadAgentResult

        sections = definitions_answer(literal.field)
        return ReadAgentResult(FIELD_MEANINGS[literal.field], (), (), (), False, sections)
    scope = literal.scope() if literal else classify(agent.llm, request, session, previous)
    if any(unresolved_selection(request.message, s["reference"]) for s in scope.subjects):
        scope = replace(scope, scope_issue="TARGET_REQUIRED", validation_stage="TARGET_CONTEXT")
        result = _result(scope, request, (), (), ())
        text = (
            "対象の設備が指定されていません。設備名・コードを書くか、画面で設備を選んでください。"
        )
        result.answer_sections["unavailable"] = [
            {"code": "TARGET_REQUIRED", "text": text, "references": []}
        ]
        return replace(result, answer=text)
    scope = replace(
        scope,
        subjects=tuple(
            {**s, "reference": selected_reference(request.message, s["reference"])}
            if s["entity_type"] == "Equipment"
            else s
            for s in scope.subjects
        ),
    )
    if literal and request.explicit_as_of:
        # The grammar does not assert a historic state can be reconstructed.
        literal = None
    targets = []
    if resolved is None:
        observations, trace, errors = collect_scope(
            scope, session, identification_only=True, identified_targets=targets
        )
    else:
        observations, trace, errors, targets = resolved
    if errors or not subjects_sufficient(scope) or len(targets) != len(scope.subjects):
        return _result(scope, request, observations, trace, errors)
    attribute = unbound_attribute(scope, request.message) if not literal else None
    if attribute is not None:
        scope = replace(scope, unbound_attribute=attribute)
    if (
        not literal
        and scope.scope_issue in {None, "UNCERTAIN"}
        and "UNSUPPORTED" not in scope.topics
        and attribute is not None
    ):
        scope = replace(
            scope,
            scope_issue="UNSUPPORTED",
            validation_stage="REQUEST_FIELD",
            validation_reason="UNBOUND_ATTRIBUTE",
            unbound_attribute=attribute,
        )
        return _result(scope, request, observations, trace, errors)
    if literal:
        values, more_trace, failures = collect_scope(scope, session, resolved_targets=targets)
        result = _result(
            scope,
            request,
            observations + values,
            trace + more_trace,
            failures,
            identity_verified=True,
        )
        if literal.predicate_value:
            # Report the actual registered value as well as the Boolean predicate.
            state = [x for x in values if x.tool == "get_equipment_state"]
            if len(state) == 1:
                actual = state[0].result.data.get("state_code")
                if actual in {"RUNNING", "STOPPED", "UNDER_MAINTENANCE", "UNKNOWN"}:
                    verdict = (
                        "確認できません"
                        if actual == "UNKNOWN"
                        else "該当します"
                        if actual == literal.predicate_value
                        else "該当しません"
                    )
                    result = replace(
                        result, answer=f"登録状態の照会条件には{verdict}。\n" + result.answer
                    )
        return result
    if scope.scope_issue not in {None, "UNCERTAIN"} or "UNSUPPORTED" in scope.topics:
        return _result(scope, request, observations, trace, errors)
    # A model can suggest a new, limited read; it cannot declare its interpretation correct.
    clarification = {
        "kind": "READ_SCOPE",
        "status": "PENDING",
        "original_question": public_answer(
            question_messages(request.message)[-1]["content"], observations
        ),
        "scope": [FIELD_MEANINGS[field] for field in scope.requested_fields],
        "reason": "LITERAL_COVERAGE_NOT_ESTABLISHED",
        "limitation": "この範囲の結果で、元の質問全体に答えられるとは限りません。",
        "targets": target_labels(observations, targets)
        or ["対象指定なし（照会範囲を確認してください）"],
    }
    pending = {
        "kind": "READ_SCOPE",
        "hash": original_hash(request),
        "catalog_version": CATALOG_VERSION,
        "scope": scope,
        "targets": targets,
        "clarification": clarification,
        "closed": False,
    }
    return _result(
        scope, request, observations, trace, errors, clarification=clarification, pending=pending
    )


def target_labels(observations, targets):
    found = {}
    for observation in observations:
        data = observation.result.data
        for row in data.get("items", []):
            if row.get("equipment_id"):
                found[row["equipment_id"]] = public_answer(
                    f"{row.get('equipment_name', '')}（{row.get('equipment_code', '')}）",
                    observations,
                )
    return [found.get(target["entity_id"], "識別した登録対象") for target in targets]


def confirmed_read(agent, context, request, saved):
    from .agent_tools import AgentToolSession
    from .read_agent import ReadAgentResult

    if saved.get("kind") != "READ_SCOPE" or saved.get("closed"):
        raise ToolError("CONTEXT_EXPIRED", "Read clarification is unavailable")
    if saved["hash"] != original_hash(request):
        raise ToolError("INVALID_ARGUMENT", "Original Read question has changed")
    clarification = dict(saved["clarification"])
    if request.read_confirmation == "REJECT":
        clarification["status"] = "DECLINED"
        text = "この解釈での照会は行いませんでした。質問を直して送信できます。"
        return ReadAgentResult(
            text,
            (),
            (),
            (),
            False,
            {"version": 1, "facts": [], "unavailable": [], "scope": []},
            clarification,
        )
    if saved["catalog_version"] != CATALOG_VERSION:
        raise ToolError("CONTEXT_EXPIRED", "Read capability definition changed; ask again")
    request = replace(request, explicit_as_of=saved.get("effective_as_of", request.explicit_as_of))
    session = AgentToolSession(
        context,
        request,
        agent.dispatcher,
        clock=agent.clock,
        event_logger=agent.events,
        deadline_seconds=agent.deadline_seconds,
    )
    targets = []
    observations, trace, errors = collect_scope(
        saved["scope"], session, identification_only=True, identified_targets=targets
    )
    attribute = unbound_attribute(saved["scope"], request.message)
    if (
        attribute is not None
        and saved["scope"].scope_issue in {None, "UNCERTAIN"}
        and "UNSUPPORTED" not in saved["scope"].topics
    ):
        scope = replace(
            saved["scope"],
            scope_issue="UNSUPPORTED",
            validation_stage="REQUEST_FIELD",
            validation_reason="UNBOUND_ATTRIBUTE",
            unbound_attribute=attribute,
        )
        return _result(scope, request, observations, trace, errors)
    if saved["scope"].scope_issue not in {None, "UNCERTAIN"}:
        return _result(saved["scope"], request, observations, trace, errors)
    if errors or targets != saved["targets"]:
        if not errors:
            errors = (
                {"code": "TARGET_AMBIGUOUS", "message": "Read targets have changed", "details": {}},
            )
        return _result(saved["scope"], request, observations, trace, errors)
    values, more_trace, failures = collect_scope(saved["scope"], session, resolved_targets=targets)
    result = _result(
        saved["scope"],
        request,
        observations + values,
        trace + more_trace,
        failures,
        identity_verified=True,
    )
    result.answer_sections["read_outcome"] = "EXPLICIT_READ"
    clarification["status"] = "ACCEPTED"
    return replace(result, read_clarification=clarification)
