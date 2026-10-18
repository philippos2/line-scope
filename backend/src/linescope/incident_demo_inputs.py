"""Registered administrative fixtures; all amounts are explicitly fictitious JPY estimates."""

from .demo_graph_seed import demo_id
from .demo_seed import DEMO_EQUIPMENT
from .domain import capacity, economics, maintenance_inputs, safety
from .persistence import core_capacity, core_economics, core_maintenance_inputs, core_safety

START, END = "2026-10-18T00:00:00Z", "2026-10-19T00:00:00Z"
SOURCE = "架空工場の共通損失台帳 v1（デモ仮定、実損害ではない）"
RATES = {"P-100": "120000", "P-200": "80000", "P-300": "50000"}


def loss(product):
    return {
        "scope_key": "factory-v1:" + product,
        "product_id": str(demo_id(product)),
        "loss_per_hour": RATES[product],
        "independent": True,
        "source": SOURCE,
        "certainty": "ESTIMATED",
    }


def cost(key, kind, amount, hours=None):
    return {
        "key": key,
        "kind": kind,
        "amount": amount,
        "hours": hours,
        "independent": True,
        "source": SOURCE,
        "certainty": "ESTIMATED",
        "valid_from": START,
        "valid_to": END,
    }


def records():
    result = []
    for index, (identifier, code, _, _) in enumerate(DEMO_EQUIPMENT):
        products = ("P-100", "P-200" if index == 0 else "P-300")
        common = {"period_start": START, "period_end": END}
        economic = {
            **common,
            "operating_hours": "24",
            "currency": "JPY",
            "incident_losses": [loss(p) for p in products],
            "options": [
                {
                    "option": "REPAIR",
                    "complete": True,
                    "items": [
                        cost("repair", "DIRECT", "300000"),
                        *[cost(p, "STOPPAGE", RATES[p], "8") for p in products],
                    ],
                },
                {
                    "option": "REPLACE",
                    "complete": False,
                    "items": [cost("replacement", "DIRECT", "2400000")],
                },
                {
                    "option": "CONTINUE",
                    "complete": False,
                    "items": [cost("unknown-running-loss", "DEGRADATION", None, None)],
                },
            ],
        }
        for kind, payload in [
            ("economic", economic),
            (
                "safety",
                {
                    **common,
                    "observation": "主軸異常" if index == 0 else "冷却系異常",
                    "criterion": "修理後の現物確認まで運転しないというデモ条件",
                    "source": SOURCE,
                    "conditions": "現物確認・安全再評価が必要",
                    "decision": "STOP_REQUIRED",
                    "certainty": "ESTIMATED",
                    "risk_notes": "実設備の安全を認定しない",
                },
            ),
        ]:
            result.append(
                make_record(kind, code + "-INCIDENT-" + kind.upper(), str(identifier), payload)
            )
        for kind, work, downtime, amount, lead in [
            ("REPAIR_PLAN", "8", "8", "300000", "0"),
            ("REPLACEMENT_PLAN", "4", "2", "0", "336"),
        ]:
            result.append(
                make_record(
                    "maintenance",
                    code + "-INCIDENT-" + kind,
                    str(identifier),
                    {
                        **common,
                        "kind": kind,
                        "source": SOURCE,
                        "details": "架空の修理／交換見積もり。調達待ちと停止時間は別。",
                        "risk_notes": "復旧・運転許可は別途確認",
                        "maintenance_plan_id": None,
                        "interim_until": None,
                        "include_replacement_cost": kind == "REPLACEMENT_PLAN",
                        "lead_time_hours": lead,
                        "work_hours": work,
                        "downtime_hours": downtime,
                        "direct_cost_jpy": amount,
                        "past_loss_jpy": None,
                        "replacement_cost_jpy": "2400000" if kind == "REPLACEMENT_PLAN" else None,
                    },
                )
            )
        result.append(
            make_record(
                "maintenance",
                code + "-INCIDENT-FAILURE_RECORD",
                str(identifier),
                {
                    "period_start": "2026-10-01T00:00:00Z",
                    "period_end": "2026-10-02T00:00:00Z",
                    "kind": "FAILURE_RECORD",
                    "source": SOURCE,
                    "details": "架空の過去異常記録。現在異常の原因確定や将来故障率を意味しない。",
                    "risk_notes": "過去損失は今回の時間当たり損失や将来対応費へ加算しない",
                    "maintenance_plan_id": None,
                    "interim_until": None,
                    "include_replacement_cost": None,
                    "lead_time_hours": None,
                    "work_hours": None,
                    "downtime_hours": "1",
                    "direct_cost_jpy": None,
                    "past_loss_jpy": "125000" if index == 0 else "50000",
                    "replacement_cost_jpy": None,
                },
            )
        )
    result.append(
        make_record(
            "capacity",
            "M-208-INCIDENT-CAPACITY",
            str(DEMO_EQUIPMENT[1][0]),
            {
                "period_start": START,
                "period_end": END,
                "quantity_unit": "個",
                "required_rate": "100",
                "normal_rate": "120",
                "used_rate": "60",
                "reserved_rate": "20",
                "loads_independent": True,
                "loads_complete": True,
                "compatible": True,
                "source": SOURCE,
                "certainty": "ESTIMATED",
                "recovery": None,
            },
            product_id=str(demo_id("P-100")),
        )
    )
    return result


def make_record(kind, code, equipment_id, payload, **extra):
    module, queries = {
        "economic": (economics, core_economics),
        "capacity": (capacity, core_capacity),
        "safety": (safety, core_safety),
        "maintenance": (maintenance_inputs, core_maintenance_inputs),
    }[kind]
    key = "maintenance_input_id" if kind == "maintenance" else kind + "_input_id"
    after = module.normalize_record(
        {
            key: str(demo_id(code)),
            "input_code": code,
            "equipment_id": equipment_id,
            "payload": payload,
            "version": 1,
            **extra,
        }
    )
    return queries, {"target_id": after[key], "operation_type": "CREATE", "after": after}
