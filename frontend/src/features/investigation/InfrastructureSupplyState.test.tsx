import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { EquipmentInvestigation } from "./EquipmentInvestigation";

vi.mock("../graph/GraphCanvas", () => ({ GraphCanvas: () => null }));
afterEach(cleanup);
const id = "same-id";
const root = {
  equipment_id: "root",
  equipment_name: "起点",
  equipment_code: "X1",
};
function props(type = "InfrastructureResource") {
  const envelope = (tool: string, data: object) => ({
    status: "ok",
    request_id: tool,
    data: { tool_results: [{ tool, data }] },
    evidence: { graph_generation: "g" },
  });
  return {
    root,
    direction: "down",
    graphMemory: {},
    onGraphMemory: vi.fn(),
    onRootChange: vi.fn(),
    onUseEquipment: vi.fn(),
    onRegister: vi.fn(),
    onObservations: vi.fn(),
    onDirection: vi.fn(),
    model: {
      selected: { entity_type: type, entity_id: id },
      labelStates: {},
      economic: [],
      capacity: [],
      economicId: "",
      capacityId: "",
      inputLoading: {},
      inputErrors: {},
      candidateEquipment: [
        { equipment_id: id, equipment_code: "X2", equipment_name: "候補" },
      ],
      retry: vi.fn(),
      retryCalculation: vi.fn(),
      currentState: "STOPPED",
      metadata: [
        {
          tool: "get_infrastructure_resource",
          data: {
            infrastructure_resource_id: id,
            resource_code: "POWER",
            resource_name: "電源",
            registered_supply_state: {
              supply_state: "UNAVAILABLE",
              observed_at: "2026-10-26T00:00:00Z",
              record: {
                infrastructure_resource_id: id,
                version: 3,
                source: "初期登録条件",
                registered_at: "2020-01-01T00:00:00Z",
              },
            },
          },
        },
        {
          tool: "get_equipment",
          data: {
            equipment_id: id,
            equipment_code: "X2",
            equipment_name: "候補",
          },
        },
      ],
      states: {
        down: {
          value: envelope("find_downstream_dependencies", {
            target: { entity_type: "Equipment", entity_id: "root" },
            representative_paths: [],
            graph_sync_state: "CURRENT",
            reached_nodes: [],
          }),
        },
        alternatives: {
          value: envelope("find_alternative_paths", {
            complete: true,
            graph_sync_state: "CURRENT",
            representative_paths: [],
            alternatives: [
              {
                candidates: [
                  {
                    candidate: { entity_type: "Equipment", entity_id: id },
                    availability: "UNAVAILABLE",
                    structure: { determination: "ESTABLISHED" },
                    reason: "UNAVAILABLE_DEPENDENCY",
                  },
                ],
              },
            ],
          }),
        },
        comparison: {
          value: {
            status: "ok",
            request_id: "comparison",
            evidence: { graph_generation: "g" },
            data: {
              decision_package: {
                comparison: {
                  options: [
                    {
                      option: "SUBSTITUTE",
                      equipment_id: id,
                      product_id: "product",
                      capacity_status: "SUFFICIENT",
                      structural_basis: { status: "AVAILABLE" },
                      condition_assessment: { safety: "UNKNOWN" },
                    },
                  ],
                },
              },
            },
          },
        },
      },
    },
  } as unknown as ComponentProps<typeof EquipmentInvestigation>;
}
it("shows readonly supply provenance and distinct timestamps only for the typed resource", () => {
  const result = render(<EquipmentInvestigation {...props()} />);
  const supply = screen.getByRole("region", { name: "登録供給状態" });
  expect(supply.textContent).toContain("供給不可");
  expect(supply.textContent).toContain("初期登録条件");
  expect(supply.textContent).toContain("供給状態の版3");
  expect(supply.textContent).toContain("2020/01/01");
  expect(supply.textContent).toContain("2026/10/26");
  expect(supply.querySelectorAll("button,input,select")).toHaveLength(0);
  result.rerender(<EquipmentInvestigation {...props("Equipment")} />);
  expect(screen.queryByRole("region", { name: "登録供給状態" })).toBeNull();
});
it("does not turn unavailable power into usable substitution despite sufficient capacity", () => {
  render(<EquipmentInvestigation {...props("Equipment")} />);
  expect(
    screen.getByRole("heading", { name: /利用できない候補/ }),
  ).toBeTruthy();
  expect(screen.queryByText(/能力面で吸収できる見込み/)).toBeNull();
  expect(screen.queryByText("利用可能", { exact: true })).toBeNull();
});
