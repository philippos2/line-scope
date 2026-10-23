// Evaluation boundary, independent of question strings and equipment IDs.
const identityTools = new Set([
  "search_equipment",
  "get_equipment",
  "get_process",
  "get_product",
  "get_production_operation",
  "get_infrastructure_resource",
]);

export function identityOnlyResult(body, expected) {
  const tools = body.data?.tool_results;
  const facts = body.data?.answer_sections?.facts;
  return (
    Array.isArray(tools) &&
    Array.isArray(facts) &&
    tools.every((tool) => identityTools.has(tool.tool)) &&
    facts.every(
      (fact) =>
        fact.predicate === "equipment.identity" ||
        (expected === "TARGET_AMBIGUOUS" &&
          fact.predicate === "equipment.identity_candidate"),
    )
  );
}
