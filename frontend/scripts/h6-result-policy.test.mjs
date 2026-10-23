import { expect, test } from "vitest";
import { identityOnlyResult } from "./h6-result-policy.mjs";

test("U19 permits real identity candidates only at the ambiguity boundary", () => {
  const body = {
    data: {
      tool_results: [{ tool: "search_equipment" }],
      answer_sections: {
        facts: [{ predicate: "equipment.identity_candidate" }],
      },
    },
  };
  expect(identityOnlyResult(body, "TARGET_AMBIGUOUS")).toBe(true);
  expect(identityOnlyResult(body, "UNSUPPORTED")).toBe(false);
  body.data.answer_sections.facts = [{ predicate: "get_equipment_state" }];
  expect(identityOnlyResult(body, "TARGET_AMBIGUOUS")).toBe(false);
});
