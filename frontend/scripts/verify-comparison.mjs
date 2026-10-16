import { URL } from "node:url";
import { randomUUID } from "node:crypto";
import { expect } from "@playwright/test";

export async function verifyComparison(page, token, approver) {
  async function api(path, body, actor = token) {
    const response = await page.request.post(
      new URL(`/api${path}`, page.url()).toString(),
      { headers: { Authorization: `Bearer ${actor}` }, data: body },
    );
    const result = await response.json();
    if (!response.ok())
      throw new Error(`Fixture ${path}: ${result.errors?.[0]?.code}`);
    return result.data;
  }
  console.log(JSON.stringify({ comparison_stage: "registered-fixture" }));
  const found = await api("/agent", { message: "M-204の修理と交換を比較して" });
  const focus = found.equipment_id;
  const candidates = found.tool_results?.find(
    (row) => row.tool === "search_equipment",
  )?.data.items;
  if (!candidates?.some((row) => row.equipment_id === focus))
    throw new Error("Equipment discovery missing");
  const equipment = candidates[0];
  const other = await api("/agent", { message: "M-208の修理と交換を比較して" });
  const alternative = other.equipment_id;
  const products = await api("/capacity-inputs/products/search", {
    query: "P-100",
  });
  const product = products.items.find((row) => row.product_code === "P-100");
  if (!product) throw new Error("Registered product missing");
  const start = "2030-01-01T00:00:00Z",
    end = "2030-01-02T00:00:00Z";
  const item = (key, kind, amount, hours = null) => ({
    key,
    kind,
    amount,
    hours,
    independent: true,
    source: "明示的な試験見積",
    certainty: "ESTIMATED",
    valid_from: start,
    valid_to: end,
  });
  async function register(kind, values) {
    const idKey = `${kind}_input_id`;
    const saved = await api(`/${kind}-inputs/prepare`, {
      retry_key: randomUUID(),
      [idKey]: null,
      input: values,
      supersedes_update_request_id: null,
    });
    await api(
      `/approvals/${saved.approval_id}/approve`,
      { snapshot_hash: saved.snapshot_hash },
      approver,
    );
    await api(`/update-requests/${saved.update_request_id}/execute`, undefined);
    return saved.canonical_snapshot.targets[0].target_id;
  }
  const economic = await register("economic", {
    input_code: "UI-COMP-ECON",
    equipment_id: focus,
    payload: {
      period_start: start,
      period_end: end,
      operating_hours: "16",
      currency: "JPY",
      options: [
        {
          option: "REPAIR",
          complete: true,
          items: [
            item("repair", "DIRECT", "300000"),
            item("P100", "STOPPAGE", "120000", "8"),
            item("P200", "STOPPAGE", "80000", "8"),
          ],
        },
        {
          option: "REPLACE",
          complete: false,
          items: [item("replacement", "DIRECT", "3000000")],
        },
        {
          option: "CONTINUE",
          complete: true,
          items: [item("degradation", "DEGRADATION", "1000", "16")],
        },
      ],
    },
  });
  const capacity = await register("capacity", {
    input_code: "UI-COMP-CAP",
    equipment_id: alternative,
    product_id: product.product_id,
    payload: {
      period_start: start,
      period_end: end,
      quantity_unit: "units",
      required_rate: "90",
      normal_rate: "100",
      used_rate: "20",
      reserved_rate: "20",
      loads_complete: true,
      loads_independent: true,
      compatible: true,
      source: "明示的な試験生産計画",
      certainty: "CONFIRMED",
      recovery: {
        buffer: "120",
        stopped_at: start,
        constant_flow: true,
        no_other_allocations: true,
        recovery_meets_demand: true,
      },
    },
  });
  const safety = await register("safety", {
    input_code: "UI-COMP-SAFE",
    equipment_id: focus,
    payload: {
      period_start: "2020-01-01T00:00:00Z",
      period_end: "2099-01-01T00:00:00Z",
      observation: "停止基準に該当",
      criterion: "試験用停止基準",
      source:
        '<img src="/never-fetch-comparison" onerror="window.comparisonInjected=true">',
      conditions: null,
      decision: "STOP_REQUIRED",
      certainty: "CONFIRMED",
      risk_notes: null,
    },
  });
  const maintenance = await register("maintenance", {
    input_code: "UI-COMP-PLAN",
    equipment_id: focus,
    payload: {
      kind: "REPLACEMENT_PLAN",
      period_start: start,
      period_end: end,
      details: "明示的な交換案",
      source: "試験見積",
      risk_notes: null,
      maintenance_plan_id: null,
      lead_time_hours: "336",
      work_hours: "4",
      downtime_hours: "2",
      direct_cost_jpy: "3000000",
      replacement_cost_jpy: null,
      past_loss_jpy: null,
      interim_until: null,
      include_replacement_cost: false,
    },
  });
  const history = await register("maintenance", {
    input_code: "UI-COMP-HISTORY",
    equipment_id: focus,
    payload: {
      kind: "FAILURE_RECORD",
      period_start: "2021-01-01T00:00:00Z",
      period_end: "2021-01-02T00:00:00Z",
      details: "出典付きの過去故障",
      source: "試験故障記録",
      risk_notes: null,
      maintenance_plan_id: null,
      lead_time_hours: null,
      work_hours: "4",
      downtime_hours: "8",
      direct_cost_jpy: "10000",
      replacement_cost_jpy: null,
      past_loss_jpy: "120000",
      interim_until: null,
      include_replacement_cost: null,
    },
  });
  // The UI independently discovers and explicitly selects equipment and saved records.
  await page
    .getByRole("button", { name: "正式入力を探す", exact: true })
    .click();
  await page
    .getByRole("button", { name: "問い合わせを送信", exact: true })
    .click();
  await page
    .getByRole("region", { name: "設備検索の候補" })
    .getByRole("button", { name: new RegExp(equipment.equipment_name) })
    .click();
  const panel = page.locator(".registered-comparison");
  await panel.locator("summary").first().click();
  await panel
    .getByRole("button", {
      name: "比較に使う正式入力の候補を取得",
      exact: true,
    })
    .click();
  for (const code of [
    "UI-COMP-ECON",
    "UI-COMP-CAP",
    "UI-COMP-SAFE",
    "UI-COMP-PLAN",
    "UI-COMP-HISTORY",
  ])
    await panel.getByLabel(new RegExp(code)).check();
  await panel
    .getByRole("button", {
      name: "入力・出典を確認：UI-COMP-ECON",
      exact: true,
    })
    .click();
  await expect(
    panel.getByLabel("共通比較期間の開始", { exact: true }),
  ).toHaveValue("2030-01-01T00:00:00.000000Z");
  const response = page.waitForResponse((value) =>
    value.url().endsWith("/api/decisions/compare"),
  );
  await panel
    .getByRole("button", { name: "選択した正式入力で比較する", exact: true })
    .click();
  const result = await (await response).json();
  if (result.status !== "partial" || result.data.source !== "REGISTERED_INPUT")
    throw new Error("Registered comparison response missing");
  const upstream = result.data.decision_package.upstream_dependencies;
  const infrastructure = upstream.reached_nodes.filter(
    (row) => row.entity_type === "InfrastructureResource",
  );
  if (
    !upstream.complete ||
    infrastructure.length !== 1 ||
    result.data.decision_package.impact.reached_nodes.some(
      (row) => row.entity_type === "InfrastructureResource",
    )
  )
    throw new Error(
      "Upstream infrastructure was confused with downstream damage",
    );
  if (
    result.data.evidence.upstream_dependencies.graph_generation !==
      result.data.evidence.impact.graph_generation ||
    !result.data.evidence.upstream_dependencies.representative_paths.length
  )
    throw new Error("Upstream infrastructure Evidence missing");
  await expect(
    panel.getByRole("region", { name: "設備が依存する上流インフラ" }),
  ).toContainText(infrastructure[0].entity_id);
  const options = result.data.decision_package.comparison.options;
  if (
    options.find((row) => row.option === "REPAIR").total_cost !== "1900000" ||
    options.find((row) => row.option === "CONTINUE").feasibility !==
      "INFEASIBLE" ||
    options.find((row) => row.option === "SUBSTITUTE").shortage_rate !== "30"
  )
    throw new Error("Registered cost/constraint/capacity mismatch");
  await expect(
    panel.getByText("1900000 JPY", { exact: true }).first(),
  ).toBeVisible();
  const assessment = result.data.decision_package.comparison;
  if (
    assessment.economics.loss_per_hour !== "200000" ||
    assessment.options.find((row) => row.option === "SUBSTITUTE")
      .condition_assessment.structure !== "AVAILABLE" ||
    assessment.history[0].calculation.past_loss_jpy !== "120000" ||
    assessment.history[0].included_in_future_cost !== false
  )
    throw new Error("Registered decision assessments are not connected");
  await expect(panel.getByRole("region", { name: "登録費用差" })).toContainText(
    "1884000 JPY",
  );
  await expect(
    panel.getByRole("region", { name: "選択した故障・修理履歴" }),
  ).toContainText("UI-COMP-HISTORY");
  await expect(
    panel.getByText("代替の条件別確認", { exact: true }),
  ).toBeVisible();

  await expect(panel.getByText("336 時間", { exact: true })).toBeVisible();
  await expect(panel.getByText("2 時間", { exact: true })).toBeVisible();
  await expect(panel.locator("img")).toHaveCount(0);
  const selection = {
    equipment_id: focus,
    period_start: start,
    period_end: end,
    economic_input_id: economic,
    capacity_input_ids: [capacity],
    safety_input_ids: [safety],
    maintenance_input_ids: [maintenance, history],
  };
  await page
    .getByLabel("問い合わせ", { exact: true })
    .fill(
      "次の引数でcompare_registered_inputsを呼んで条件を評価してください。" +
        JSON.stringify(selection),
    );
  const modelResponse = page.waitForResponse(
    (value) => value.url().endsWith("/api/agent"),
    { timeout: 90000 },
  );
  await page
    .getByRole("button", { name: "問い合わせを送信", exact: true })
    .click();
  const model = await (await modelResponse).json();
  console.log(
    JSON.stringify({
      comparison_stage: "agent-response",
      status: model.status,
      errors: model.errors?.map((row) => row.code),
      tools: model.data.tool_results?.map((row) => row.tool),
    }),
  );
  if (
    !model.data.tool_results?.some(
      (row) => row.tool === "compare_registered_inputs",
    ) ||
    !model.answer?.includes("候補から除外")
  )
    throw new Error("Real model registered comparison reference failed");
  const compareTool = model.data.tool_results.find(
    (row) => row.tool === "compare_registered_inputs",
  );
  if (
    !compareTool.data.decision_package.upstream_dependencies.reached_nodes.some(
      (row) => row.entity_id === infrastructure[0].entity_id,
    )
  )
    throw new Error("Agent comparison lost upstream infrastructure");
  if (await page.evaluate(() => globalThis.comparisonInjected === true))
    throw new Error("Source executed");
  await panel
    .getByLabel("共通比較期間の終了", { exact: true })
    .fill("2030-01-03T00:00:00Z");
  await panel
    .getByRole("button", { name: "選択した正式入力で比較する", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "BUSINESS_RULE_VIOLATION",
  );
  await panel.getByLabel("共通比較期間の終了", { exact: true }).fill(end);
  await panel.getByLabel(/UI-COMP-ECON/).uncheck();
  const partial = page.waitForResponse((value) =>
    value.url().endsWith("/api/decisions/compare"),
  );
  await panel
    .getByRole("button", { name: "選択した正式入力で比較する", exact: true })
    .click();
  const missing = await (await partial).json();
  if (
    missing.data.decision_package.comparison.options.some(
      (row) => row.total_cost !== null,
    )
  )
    throw new Error("Missing economic input was inferred");
  console.log(
    JSON.stringify({
      result: "PASS",
      scope:
        "REGISTERED_COMPARISON_SELECTION_COST_CONSTRAINT_UNKNOWN_PERIOD_REAL_LLM",
    }),
  );
}
