import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { EquipmentCandidates } from "./EquipmentCandidates";
import type { Envelope } from "../../api/client";
afterEach(cleanup);
function result(items: unknown[], next_cursor: string | null = null): Envelope {
  return {
    request_id: "r",
    context_id: null,
    status: "ok",
    answer: null,
    data: {
      tool_results: [
        { tool: "search_equipment", data: { items, next_cursor } },
      ],
    },
    evidence: {},
    warnings: [],
    errors: [],
  };
}
it("shows no candidates without claiming the factory has no equipment", () => {
  render(
    <EquipmentCandidates
      result={result([])}
      disabled={false}
      onSelect={vi.fn()}
    />,
  );
  expect(screen.getByText("選択できる候補はありません。")).toBeTruthy();
  expect(
    screen.getByText(/工場全体の一覧や現在状態ではありません/),
  ).toBeTruthy();
});
it("keeps a continuation visible and disables stale candidates", () => {
  render(
    <EquipmentCandidates
      result={result(
        [
          {
            equipment_id: "e",
            equipment_code: "M-208",
            equipment_name: "予備機",
          },
        ],
        "next",
      )}
      disabled={true}
      onSelect={vi.fn()}
    />,
  );
  expect(screen.getByText(/検索の続きは未取得/)).toBeTruthy();
  expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
});
it("renders untrusted names as text and reports malformed candidates", () => {
  const { container } = render(
    <EquipmentCandidates
      result={result([
        {
          equipment_id: "e",
          equipment_code: "M-208",
          equipment_name: '<img src=x onerror="alert(1)">',
        },
        {},
      ])}
      disabled={false}
      onSelect={vi.fn()}
    />,
  );
  expect(screen.getByText(/<img src=x/)).toBeTruthy();
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText(/表示できない候補/)).toBeTruthy();
});
