import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DecisionComparison } from "./DecisionComparison";
import { ComparisonInputDetails } from "./ComparisonInputDetails";
import { UpstreamDependencies } from "./UpstreamDependencies";
afterEach(cleanup);
it("keeps known zero costs visible and separates uncalculated costs from evaluation exclusions", () => {
  render(
    <DecisionComparison
      comparison={{
        options: [
          {
            option: "REPAIR",
            feasibility: "UNKNOWN",
            total_cost: "0",
            residual_risk: "UNKNOWN",
          },
          { option: "REPLACE", feasibility: "UNKNOWN", total_cost: null },
        ],
      }}
    />,
  );
  expect(screen.getByText("0 JPY")).toBeDefined();
  expect(screen.getByText(/費用の総額は算定できません/)).toBeDefined();
  expect(
    screen.getByText(/品質・残るリスクは、この版では評価対象外/),
  ).toBeDefined();
  expect(screen.queryByText("UNKNOWN")).toBeNull();
});
it("uses the existing unavailable-candidate gate and product limitation in comparison", () => {
  render(
    <DecisionComparison
      names={{ p: "製品A · P-100", q: "製品B · P-200" }}
      productIds={["p", "q"]}
      comparison={{
        options: [
          {
            option: "SUBSTITUTE",
            equipment_id: "m",
            product_id: "p",
            capacity_status: "SUFFICIENT",
            required_rate: "60",
            available_rate: "80",
            structural_basis: {
              status: "UNAVAILABLE",
              candidate: {
                availability: "UNAVAILABLE",
                structure: { determination: "ESTABLISHED" },
              },
            },
            condition_assessment: { safety: "UNKNOWN", quality: "UNKNOWN" },
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("利用できないため提案しない候補")).toBeDefined();
  expect(screen.queryByText(/能力面で吸収できる見込み/)).toBeNull();
  expect(screen.getByText(/今回選択した能力入力では製品B/)).toBeDefined();
});
it("shows input facts and per-product sources without replacing them with JSON", () => {
  render(
    <ComparisonInputDetails
      names={{ m: "第2加工機 · M-208" }}
      record={{
        equipment_id: "m",
        version: 1,
        payload: {
          period_start: "2026-10-18T00:00:00Z",
          period_end: "2026-10-19T00:00:00Z",
          incident_losses: [
            { product_code: "P-100", loss_per_hour: "120000", source: "出典A" },
            { product_code: "P-200", loss_per_hour: "80000", source: "出典B" },
          ],
        },
      }}
    />,
  );
  expect(screen.getByText("出典A")).toBeDefined();
  expect(screen.getByText("出典B")).toBeDefined();
  expect(screen.getByText("P-100")).toBeDefined();
  expect(screen.getByText("P-200")).toBeDefined();
  expect(screen.getByText(/日本時間/)).toBeDefined();
  expect(
    screen.getByText("技術情報").closest("details")?.getAttribute("open"),
  ).toBeNull();
});
it("labels infrastructure with the known name and code instead of displaying its identifier", () => {
  render(
    <UpstreamDependencies
      names={{ "resource-key": "共通電源 · R-02" }}
      data={{
        complete: true,
        reached_nodes: [
          { entity_type: "InfrastructureResource", entity_id: "resource-key" },
        ],
      }}
    />,
  );
  expect(screen.getByText("共通電源 · R-02")).toBeDefined();
  expect(screen.queryByText("インフラ資源：resource-key")).toBeNull();
});
