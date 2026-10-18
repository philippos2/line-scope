"""Authorized incident read use case; Graph and registered loss evidence stay separate."""

from datetime import datetime, timezone

from ..domain.incident_loss import aggregate, normalize_selection
from .economics import EconomicInputs, require
from .proposals import ProposalError
from .reads import ReadTools, ToolError, json_value


class IncidentInvestigation:
    def __init__(self, database, graph):
        self.reads, self.economics, self.graph = (
            ReadTools(database),
            EconomicInputs(database),
            graph,
        )

    def investigate(self, context, values):
        require(context)
        try:
            selection = normalize_selection(values)
        except (ValueError, TypeError) as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid incident selection") from error
        if self.graph is None:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "Graph analysis is not configured")
        inputs = [self.economics.get(context, i) for i in selection["economic_input_ids"]]
        records = [row["input"] for row in inputs]
        if any(row["equipment_id"] not in selection["equipment_ids"] for row in records):
            raise ProposalError("BUSINESS_RULE_VIOLATION", "Economic input equipment mismatch")
        impacts, evidence = [], []
        as_of = datetime.now(timezone.utc).isoformat()
        generation = None
        for identifier in selection["equipment_ids"]:
            equipment = self.reads.run(context, "get_equipment", {"equipment_id": identifier})
            result = self.graph.call(
                context,
                "trace_downstream_impact",
                {
                    "target": {"entity_type": "Equipment", "entity_id": identifier},
                    "explicit_as_of": as_of,
                },
            )
            current_generation = result.evidence["graph_generation"]
            if generation is not None and generation != current_generation:
                raise ToolError(
                    "GRAPH_NOT_CURRENT", "Graph generation changed; retry incident analysis"
                )
            generation = current_generation
            state = next(
                (
                    row
                    for row in result.evidence["current_states"]
                    if row["equipment_id"] == identifier
                ),
                None,
            )
            impacts.append(
                {
                    "equipment_id": identifier,
                    "equipment": equipment.data,
                    "state_code": state["state_code"] if state else "UNKNOWN",
                    "state_version": state["version"] if state else None,
                    "product_ids": sorted(
                        row["entity_id"]
                        for row in result.data["reached_nodes"]
                        if row["entity_type"] == "Product"
                    ),
                    "complete": result.data["complete"],
                    "impact": result.data,
                }
            )
            evidence.append(
                {
                    "equipment_id": identifier,
                    "equipment": equipment.evidence,
                    "impact": result.evidence,
                }
            )
        loss = aggregate(impacts, records, (selection["period_start"], selection["period_end"]))
        return json_value(
            {
                "selection": selection,
                "impacts": impacts,
                "loss": loss,
                "automatic_state_change": False,
                "evidence": {
                    "graph_generation": generation,
                    "as_of": as_of,
                    "impacts": evidence,
                    "registered_inputs": inputs,
                    "observation_scope": "SEPARATE_GRAPH_AND_POSTGRESQL_OBSERVATIONS",
                },
            }
        )
