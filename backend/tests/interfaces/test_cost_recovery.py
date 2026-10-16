from copy import deepcopy
from uuid import uuid4

from domain.test_cost_recovery import recovery_payload

from interfaces.test_economic_inputs_api import (
    approve,
    body,
    client_for,
    execute,
    headers,
    identifier,
    prepare,
)
from interfaces.test_economic_inputs_api import world as world
from linescope.domain.canonical import canonical_hash, canonical_json
from linescope.domain.snapshot import CanonicalSnapshot


def test_legacy_pending_and_v6_create_update_removal_keep_hash_replay_and_history(world):
    with client_for(world) as api:
        legacy = prepare(api, body("LEGACY"))
        legacy_hash = legacy["snapshot_hash"]
        values = body("RECOVERY")
        values["input"]["payload"] = recovery_payload()
        saved = prepare(api, values)
        assert saved["snapshot_schema_version"] == 6
        assert (
            CanonicalSnapshot(
                canonical_json(saved["canonical_snapshot"]), saved["snapshot_hash"]
            ).data
            == saved["canonical_snapshot"]
        )
        assert execute(api, saved).status_code == 409
        assert approve(api, legacy).status_code == 200 and execute(api, legacy).status_code == 200
        assert canonical_hash(legacy["canonical_snapshot"]) == legacy_hash
        assert approve(api, saved).status_code == 200 and execute(api, saved).status_code == 200
        observed = api.get("/economic-inputs/" + identifier(saved), headers=headers()).json()[
            "data"
        ]
        assert observed["calculation"]["simple_cost_recovery"]["days"] == "150"
        assert observed["input"]["version"] == 1
        assert prepare(api, values)["update_request_id"] == saved["update_request_id"]
        removed = deepcopy(values)
        removed.update(retry_key=str(uuid4()), economic_input_id=identifier(saved))
        del removed["input"]["payload"]["cost_recovery"]
        update = prepare(api, removed)
        assert update["snapshot_schema_version"] == 6  # Before contains the extension.
        assert approve(api, update).status_code == 200 and execute(api, update).status_code == 200
        current = api.get("/economic-inputs/" + identifier(saved), headers=headers()).json()["data"]
        assert (
            current["input"]["version"] == 2
            and current["calculation"]["simple_cost_recovery"]["days"] is None
        )
        replay = execute(api, saved).json()["data"]
        assert replay["current_versions"][0]["version_delta"] == 1


def test_retry_fingerprint_covers_recovery_assumptions_and_saved_hash(world):
    with client_for(world) as api:
        values = body("RECOVERY")
        values["input"]["payload"] = recovery_payload()
        saved = prepare(api, values)
        changed = deepcopy(values)
        changed["input"]["payload"]["cost_recovery"]["source"] = "別の登録条件"
        response = api.post("/economic-inputs/prepare", json=changed, headers=headers())
        assert response.status_code == 409
        retrieved = api.get(
            "/update-requests/" + saved["update_request_id"], headers=headers()
        ).json()["data"]
        assert retrieved["snapshot_hash"] == saved["snapshot_hash"]
        assert canonical_json(retrieved["canonical_snapshot"]) == canonical_json(
            saved["canonical_snapshot"]
        )
