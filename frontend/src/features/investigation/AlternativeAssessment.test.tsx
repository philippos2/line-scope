import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AlternativeAssessment } from "./AlternativeAssessment";
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
  missing_information: ["confirmed_continued_operation_conditions"],
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
  expect(screen.getByText("条件付き")).toBeTruthy();
  expect(screen.getByText("高い")).toBeTruthy();
  expect(
    screen.getByText("運転継続の確認条件を確認してください。"),
  ).toBeTruthy();
  expect(screen.getByText("この評価は運転許可を出していません。")).toBeTruthy();
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
