import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AlternativeAssessment } from "./AlternativeAssessment";
import { displayPeriod } from "./EquipmentInvestigation";
import { lossSourceLines } from "./readModel";
import { label } from "../graph/model";
import type { Envelope, JsonObject } from "../../api/client";
afterEach(cleanup);
// Response fields from the real scenario probe; state variations are controlled UI inputs.
const option: JsonObject = {
  equipment_id: "candidate",
  product_id: "product",
  capacity_status: "SUFFICIENT",
  required_rate: "60",
  available_rate: "80",
  quantity_unit: "個",
  structural_basis: { status: "AVAILABLE" },
  condition_assessment: {
    safety: "UNKNOWN",
    quality: "UNKNOWN",
    operational_permission: false,
  },
  residual_risk: "UNKNOWN",
  missing_information: [
    "confirmed_continued_operation_conditions",
    "economic_input",
  ],
};
function show(availability = "AVAILABLE", changes: JsonObject = {}) {
  return render(
    <AlternativeAssessment
      option={{ ...option, ...changes }}
      candidate={{
        availability,
        reason:
          availability === "UNAVAILABLE"
            ? "UNAVAILABLE_DEPENDENCY"
            : availability === "UNKNOWN"
              ? "UNKNOWN_AVAILABILITY"
              : null,
        structure: { determination: "ESTABLISHED" },
      }}
      product="製品A"
      unevaluated={["製品B"]}
    />,
  );
}
it.each(["AVAILABLE", "UNAVAILABLE", "UNKNOWN"])(
  "gates a sufficient capacity response with candidate availability %s",
  (availability) => {
    show(availability);
    expect(
      screen.queryByText("製品Aは、能力面で吸収できる見込み") !== null,
    ).toBe(availability === "AVAILABLE");
    expect(
      screen.getByText("今回選択した能力入力では製品Bを評価していません。"),
    ).toBeTruthy();
    expect(screen.getByText("利用可能性")).toBeTruthy();
    expect(
      screen.getByText("品質・残るリスクは、この版では評価対象外です。"),
    ).toBeTruthy();
    expect(
      screen.getByText("今回の評価では安全条件の入力を選択していません。"),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "この版では、代替運転の費用を比較結果に含めていません。",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("品質", { selector: "dt" })).toBeNull();
    expect(screen.queryByText("残るリスク", { selector: "dt" })).toBeNull();
    expect(
      displayPeriod(
        "2026-10-18T00:00:00.000000Z",
        "2026-10-19T00:00:00.000000Z",
      ),
    ).toBe("2026/10/18 09:00〜2026/10/19 09:00（日本時間）");
    if (availability === "UNAVAILABLE")
      expect(
        screen.getByText(/設備自身または必須の依存先を利用できません/),
      ).toBeTruthy();
    if (availability === "UNKNOWN")
      expect(
        screen.getByRole("heading", { name: "利用できるか確認できない候補" }),
      ).toBeTruthy();
  },
);
it("does not suggest absorption for an available candidate with insufficient capacity", () => {
  show("AVAILABLE", { capacity_status: "INSUFFICIENT" });
  expect(screen.getByRole("heading").textContent).toContain("能力が不足");
  expect(screen.queryByText(/吸収できる見込み/)).toBeNull();
});
it("renders safety, quality, residual risk and blocking conditions from the server values", () => {
  show("AVAILABLE", {
    condition_assessment: {
      safety: "STOP_REQUIRED",
      quality: "CONDITIONAL",
      operational_permission: false,
    },
    residual_risk: "HIGH",
  });
  expect(screen.getByText("停止が必要")).toBeTruthy();
  expect(screen.getByText("品質の返却値：条件付き")).toBeTruthy();
  expect(screen.getByText("残るリスクの返却値：高い")).toBeTruthy();
  expect(
    screen.getByText("選択した安全条件では停止が必要と判定されています。"),
  ).toBeTruthy();
  expect(
    screen.getByText("利用可能性と能力の評価は、運転許可を意味しません。"),
  ).toBeTruthy();
});
it("does not propose when the comparison availability disagrees with the alternative result", () => {
  show("AVAILABLE", { structural_basis: { status: "UNKNOWN" } });
  expect(screen.queryByText(/吸収できる見込み/)).toBeNull();
  expect(screen.getByRole("heading").textContent).toBe(
    "利用できるか確認できない候補",
  );
});
it("does not draw a zero capacity bar for an unknown numeric value", () => {
  show("UNKNOWN", { available_rate: null });
  expect(screen.getAllByRole("progressbar")).toHaveLength(1);
  expect(screen.getByText(/空き能力：不明/)).toBeTruthy();
});
it("labels an infrastructure node with the resource fields returned by its own get tool", () => {
  const products = (id: string) => `製品 · ${id}`;
  expect(
    lossSourceLines(
      [
        { product_id: "P-100", source: "共通出典" },
        { product_id: "P-200", source: "共通出典" },
      ],
      products,
    ),
  ).toEqual(["共通出典"]);
  expect(
    lossSourceLines(
      [
        { product_id: "P-100", source: "出典A" },
        { product_id: "P-200", source: "出典B" },
      ],
      products,
    ),
  ).toEqual(["製品 · P-100：出典A", "製品 · P-200：出典B"]);

  const result = {
    data: {
      tool_results: [
        {
          tool: "get_infrastructure_resource",
          data: {
            infrastructure_resource_id: "resource",
            resource_name: "共通電源",
            resource_code: "R-02",
          },
        },
      ],
    },
  } as unknown as Envelope;
  expect(
    label(result, {
      entity_type: "InfrastructureResource",
      entity_id: "resource",
    }),
  ).toBe("共通電源 · R-02");
});
