"""Fixed PostgreSQL Read Tools. No user-provided SQL or write operations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import psycopg
from psycopg import sql
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError, create_model

from .execution import ExecutionContext


class ToolError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class ReadResult:
    data: dict
    evidence: dict


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


GET_TOOLS = {
    "get_equipment": ("equipment", "equipment_id"),
    "get_equipment_state": ("equipment_current_state", "equipment_id"),
    "get_maintenance_plan": ("maintenance_plan", "maintenance_plan_id"),
    "get_process": ("process", "process_id"),
    "get_production_operation": ("production_operation", "production_operation_id"),
    "get_product": ("product", "product_id"),
    "get_infrastructure_resource": ("infrastructure_resource", "infrastructure_resource_id"),
    "get_dependency_relation": ("dependency_relation", "dependency_relation_id"),
}
SCHEMAS = {
    name: create_model(name + "_arguments", __base__=Arguments, **{key: (UUID, ...)})
    for name, (_, key) in GET_TOOLS.items()
}
SCHEMAS["get_operation_equipment_assignments"] = create_model(
    "assignment_arguments",
    __base__=Arguments,
    production_operation_id=(UUID, ...),
    explicit_as_of=(AwareDatetime, None),
)


def json_value(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value


class ReadTools:
    def __init__(self, database):
        self.database = database

    def schemas(self):
        return {name: model.model_json_schema() for name, model in SCHEMAS.items()}

    def run(self, context, tool, arguments):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if not isinstance(tool, str) or tool not in SCHEMAS:
            raise ToolError("INVALID_ARGUMENT", "Unknown read tool")
        if not isinstance(arguments, dict):
            raise ToolError("INVALID_ARGUMENT", "Tool arguments must be an object")
        if "explicit_as_of" in arguments and not isinstance(
            arguments["explicit_as_of"], (str, datetime)
        ):
            raise ToolError(
                "INVALID_ARGUMENT", "explicit_as_of requires a timezone-aware timestamp"
            )
        try:
            values = SCHEMAS[tool].model_validate(arguments)
        except ValidationError as error:
            # Do not echo arbitrary arguments or validation input into the result.
            raise ToolError("INVALID_ARGUMENT", "Invalid read tool arguments") from error
        explicit_as_of = getattr(values, "explicit_as_of", None)
        if explicit_as_of is not None and explicit_as_of > datetime.now(timezone.utc):
            raise ToolError("INVALID_ARGUMENT", "Future explicit_as_of is not supported")
        try:
            with self.database.transaction() as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY")
                if tool in GET_TOOLS:
                    table, key = GET_TOOLS[tool]
                    row = connection.execute(
                        sql.SQL(
                            "SELECT *, statement_timestamp() AS _observed_at FROM {} WHERE {}=%s"
                        ).format(sql.Identifier(table), sql.Identifier(key)),
                        (getattr(values, key),),
                    ).fetchone()
                    if row is None:
                        raise ToolError("TARGET_NOT_FOUND", "Requested record does not exist")
                    observed_at = row.pop("_observed_at")
                    data = row
                else:
                    # One statement gives parent version and all assignments the same snapshot.
                    rows = connection.execute(
                        """SELECT p.version AS _parent_version,
                                  statement_timestamp() AS _observed_at, a.*
                           FROM production_operation p
                           LEFT JOIN production_operation_equipment_assignment a
                             ON a.production_operation_id=p.production_operation_id
                            AND a.active
                            AND (%s::timestamptz IS NULL OR
                                 (a.effective_from <= %s AND
                                  (a.effective_to IS NULL OR %s < a.effective_to)))
                           WHERE p.production_operation_id=%s ORDER BY a.assignment_id""",
                        (
                            explicit_as_of,
                            explicit_as_of,
                            explicit_as_of,
                            values.production_operation_id,
                        ),
                    ).fetchall()
                    if not rows:
                        raise ToolError("TARGET_NOT_FOUND", "Requested operation does not exist")
                    observed_at = rows[0]["_observed_at"]
                    data = {
                        "parent_version": rows[0]["_parent_version"],
                        "items": [
                            {key: item for key, item in row.items() if not key.startswith("_")}
                            for row in rows
                            if row["assignment_id"] is not None
                        ],
                        "as_of": explicit_as_of,
                        "temporal_scope": "CURRENT_REGISTRATION_AT_AS_OF",
                    }
        except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as error:
            raise ToolError(
                "RESOURCE_BUSY", "Read could not complete within the time limit"
            ) from error
        except (psycopg.OperationalError, psycopg.InterfaceError) as error:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "PostgreSQL is unavailable") from error
        except psycopg.Error as error:
            raise ToolError("INTERNAL_ERROR", "Read failed") from error
        return ReadResult(
            data=json_value(data),
            evidence={
                "source": "POSTGRESQL",
                "tool": tool,
                "observed_at": json_value(observed_at),
                "consistency": "LATEST_PER_CALL",
            },
        )
