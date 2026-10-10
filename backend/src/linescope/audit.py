"""Transaction-local audit writes. No autonomous commit or public logging API."""

from uuid import uuid4

from .core_approval import find_approval_parent
from .core_audit import insert_audit_event
from .core_proposals import lock_request_approval, lock_request_state


def prepare_saved(connection, context, update_request_id, approval_id, target_count):
    insert_audit_event(
        connection,
        audit_event_id=uuid4(),
        request_id=context.request_id,
        update_request_id=update_request_id,
        approval_id=approval_id,
        actor_id=context.authenticated_user_id,
        action="PREPARE",
        before_status=None,
        after_status="WAITING_APPROVAL",
        result_code="OK",
        details={"target_count": target_count},
    )


def proposal_replaced(connection, context, previous, replacement_id):
    insert_audit_event(
        connection,
        audit_event_id=uuid4(),
        request_id=context.request_id,
        update_request_id=previous.update_request_id,
        approval_id=previous.approval_id,
        actor_id=context.authenticated_user_id,
        action="INVALIDATE",
        before_status=previous.status,
        after_status="INVALIDATED",
        result_code="OK",
        details={"replacement_update_request_id": str(replacement_id)},
    )


def failed_attempt(store, events, context, action, code, *, request_id=None, approval_id=None):
    """Best-effort separate audit after the main transaction has ended."""
    from .canonical import normalize_uuid
    from .proposals import ProposalError

    try:
        try:
            if request_id is not None:
                request_id = normalize_uuid(request_id)
            elif approval_id is not None:
                approval_id = normalize_uuid(approval_id)
            else:
                return None
        except ValueError:
            return None
        with store._transaction() as c:
            if request_id is None:
                parent = find_approval_parent(c, approval_id)
                if parent is None:
                    return None
                request_id = parent["update_request_id"]
            state = lock_request_state(c, request_id)
            if state is None:
                return None
            approval = lock_request_approval(c, request_id)
            approval_id = approval["approval_id"] if approval else None
            insert_audit_event(
                c,
                audit_event_id=uuid4(),
                request_id=context.request_id,
                update_request_id=request_id,
                approval_id=approval_id,
                actor_id=context.authenticated_user_id,
                action="FAILURE",
                before_status=state["status"],
                after_status=state["status"],
                result_code=code,
                details={"attempted_action": action},
            )
    except ProposalError:
        events.emit(
            "audit.persist_failed",
            component="audit",
            outcome="failure",
            result_code="INTERNAL_ERROR",
            level="ERROR",
            approval_id=approval_id,
            update_request_id=request_id,
        )
    return request_id
