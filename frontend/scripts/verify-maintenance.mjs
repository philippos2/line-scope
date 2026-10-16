import { expect } from "@playwright/test";

export async function verifyMaintenance(page, token, approver) {
  console.log(JSON.stringify({ maintenance_stage: "equipment-selection" }));
  await page.getByRole("button", { name: "設備を探す", exact: true }).click();
  await page
    .getByLabel("問い合わせ", { exact: true })
    .fill("設備コードM-204を検索して。変更要求は作成しないでください。");
  const discovery = page.waitForResponse(
    (value) =>
      value.url().endsWith("/api/agent") && value.request().method() === "POST",
    { timeout: 90000 },
  );
  await page
    .getByRole("button", { name: "問い合わせを送信", exact: true })
    .click();
  const discovered = await (await discovery).json();
  console.log(
    JSON.stringify({
      maintenance_stage: "equipment-response",
      status: discovered.status,
      errors: discovered.errors?.map((item) => item.code),
      tools: discovered.data.tool_results?.map((item) => ({
        tool: item.tool,
        count: item.data.items?.length,
        codes:
          item.tool === "search_equipment"
            ? item.data.items?.map((row) => row.equipment_code)
            : undefined,
      })),
    }),
  );
  if (
    !discovered.data.tool_results?.some(
      (item) =>
        item.tool === "search_equipment" &&
        item.data.items?.some((row) => row.equipment_code === "M-204"),
    )
  )
    throw new Error("Expected registered equipment search candidate");

  const candidates = page.getByRole("region", { name: "設備検索の候補" });
  await candidates
    .getByRole("button", { name: /Demo machine M-204/ })
    .click({ timeout: 90000 });
  const panel = page.locator(".maintenance-panel");
  await panel.locator("summary").click();
  await panel
    .getByRole("button", { name: "選択設備の対応計画・故障履歴を登録" })
    .click();
  const editor = panel.getByRole("region", {
    name: "対応計画・故障履歴の登録・訂正",
  });
  await editor
    .getByLabel("対応計画・故障履歴の入力コード", { exact: true })
    .fill("UI-MAINTENANCE");
  await editor
    .getByLabel("評価・記録の期間開始", { exact: true })
    .fill("2020-01-01T00:00:00Z");
  await editor
    .getByLabel("評価・記録の期間終了", { exact: true })
    .fill("2099-01-01T00:00:00Z");
  await editor
    .getByLabel("記録分類", { exact: true })
    .selectOption("REPLACEMENT_PLAN");
  await editor
    .getByLabel("計画・事象の内容", { exact: true })
    .fill("交換部品の調達14日。停止時間は作業と別記");
  await editor.getByLabel("調達待ち（時間）", { exact: true }).fill("336");
  await editor.getByLabel("作業時間（時間）", { exact: true }).fill("4");
  await editor.getByLabel("停止時間（時間）", { exact: true }).fill("2");
  await editor
    .getByLabel("交換費を除く直接費（JPY）", { exact: true })
    .fill("10000");
  await editor
    .getByLabel("評価期間に算入する交換費（JPY）", { exact: true })
    .fill("20000");
  await editor
    .getByLabel("交換費を評価期間の費用へ含める", { exact: true })
    .selectOption("true");
  await editor
    .getByLabel("計画・実績の出典", { exact: true })
    .fill(
      '<img src="/never-fetch-maintenance" onerror="window.maintenanceCommandExecuted=true">',
    );
  async function prepare() {
    const response = page.waitForResponse(
      (value) =>
        value.url().endsWith("/api/maintenance-inputs/prepare") &&
        value.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "対応計画・故障履歴の変更準備を作成" })
      .click();
    const body = await (await response).json();
    if (body.status !== "ok") throw new Error("Maintenance Prepare failed");
    return body.data.update_request_id;
  }
  async function confirm(id) {
    const action = page.locator(".action-panel");
    if (!(await action.evaluate((element) => element.open)))
      await action.locator("summary").click();
    await action.getByRole("button", { name: "直近の変更要求を開く" }).click();
    await action.getByLabel("保存Snapshotと操作内容を確認しました").check();
    await action
      .getByRole("button", { name: "Snapshotを承認", exact: true })
      .click();
    await expect(action.getByRole("alert")).toContainText(
      "AUTHORIZATION_DENIED",
    );
    async function switchUser(value) {
      await page.getByRole("button", { name: "接続解除", exact: true }).click();
      await page.getByLabel("Bearer token").fill(value);
      await page.getByRole("button", { name: "接続する", exact: true }).click();
      await page.locator(".action-panel summary").click();
      await page.getByLabel("変更要求ID", { exact: true }).fill(id);
      await page
        .getByRole("button", { name: "保存状態を再取得", exact: true })
        .click();
      await expect(
        page.getByRole("heading", { name: "保存済みSnapshot", exact: true }),
      ).toBeVisible();
    }
    await switchUser(approver);
    await page.getByLabel("保存Snapshotと操作内容を確認しました").check();
    await page
      .getByRole("button", { name: "Snapshotを承認", exact: true })
      .click();
    await expect(page.getByText(/状態：APPROVED/)).toBeVisible();
    await switchUser(token);
    await page.getByLabel("保存Snapshotと操作内容を確認しました").check();
    await page
      .getByRole("button", { name: "承認済み変更を実行", exact: true })
      .click();
    await expect(page.getByText(/状態：COMPLETED/)).toBeVisible();
  }
  async function load() {
    if (!(await panel.evaluate((element) => element.open)))
      await panel.locator("summary").click();
    await panel
      .getByLabel("対応計画・故障履歴コード", { exact: true })
      .fill("UI-MAINTENANCE");
    await panel
      .getByRole("button", { name: "登録済み対応計画・故障履歴を検索" })
      .click();
    const read = page.waitForResponse(
      (value) =>
        value.url().includes("/api/maintenance-inputs/") &&
        value.request().method() === "GET",
    );
    await panel
      .getByRole("region", { name: "対応計画・故障履歴の検索候補" })
      .getByRole("button", { name: /UI-MAINTENANCE/ })
      .click();
    const result = await (await read).json();
    if (result.data.source !== "REGISTERED_INPUT")
      throw new Error("Registered maintenance source missing");
    return result.data;
  }
  console.log(JSON.stringify({ maintenance_stage: "prepare-approve-execute" }));
  await confirm(await prepare());
  const registered = await load();
  if (
    registered.calculation.lead_time_hours !== "336" ||
    registered.calculation.downtime_hours !== "2" ||
    registered.calculation.known_plan_direct_cost_subtotal_jpy !== "30000"
  )
    throw new Error("Maintenance durations or cost mismatch");
  const result = panel.getByRole("region", {
    name: "登録済み対応計画・故障履歴の参照結果",
  });
  await expect(
    result.getByRole("heading", { name: "交換案", exact: true }),
  ).toBeVisible();
  await expect(result.locator("img")).toHaveCount(0);
  if (await page.evaluate(() => globalThis.maintenanceCommandExecuted === true))
    throw new Error("Source executed");
  await panel
    .getByRole("button", {
      name: "この対応計画・故障履歴をAgentへ問い合わせる",
    })
    .click();
  const response = page.waitForResponse(
    (value) =>
      value.url().endsWith("/api/agent") && value.request().method() === "POST",
    { timeout: 90000 },
  );
  await page
    .getByRole("button", { name: "問い合わせを送信", exact: true })
    .click();
  const agent = await (await response).json();
  console.log(
    JSON.stringify({
      maintenance_stage: "agent-response",
      status: agent.status,
      errors: agent.errors?.map((item) => item.code),
      tools: agent.data.tool_results?.map((item) => item.tool),
      has_maintenance_summary:
        agent.answer?.includes("調達待ちと作業・停止時間は別です"),
    }),
  );
  if (
    !agent.data.tool_results?.some(
      (item) => item.tool === "get_maintenance_input",
    ) ||
    !agent.answer?.includes("調達待ちと作業・停止時間は別です")
  )
    throw new Error("Registered maintenance Agent read failed");
  await expect(
    page.getByRole("heading", {
      name: "正式対応計画・故障履歴：UI-MAINTENANCE",
      exact: true,
    }),
  ).toHaveCount(2);
  console.log(JSON.stringify({ maintenance_stage: "unknown-cost-update" }));
  await panel
    .getByRole("button", { name: "この対応計画・故障履歴の訂正を準備" })
    .click();
  await editor.getByLabel("停止時間（時間）", { exact: true }).fill("");
  await editor
    .getByLabel("交換費を評価期間の費用へ含める", { exact: true })
    .selectOption("UNKNOWN");
  await confirm(await prepare());
  const updated = await load();
  if (
    updated.input.version !== 2 ||
    updated.calculation.downtime_hours !== null ||
    updated.calculation.known_plan_direct_cost_subtotal_jpy !== null
  )
    throw new Error("Unknown costs or downtime were inferred");
  // The same UI records a sourced historical incident without forecast fields.
  await panel
    .getByRole("button", { name: "この対応計画・故障履歴の訂正を準備" })
    .click();
  await editor
    .getByLabel("記録分類", { exact: true })
    .selectOption("FAILURE_RECORD");
  await editor
    .getByLabel("評価・記録の期間終了", { exact: true })
    .fill("2021-01-01T00:00:00Z");
  await editor.getByLabel("調達待ち（時間）", { exact: true }).fill("");
  await editor
    .getByLabel("評価期間に算入する交換費（JPY）", { exact: true })
    .fill("");
  await editor
    .getByLabel("過去停止損失（JPY・履歴のみ）", { exact: true })
    .fill("120000");
  await confirm(await prepare());
  const historical = await load();
  if (
    historical.input.version !== 3 ||
    historical.calculation.record_scope !== "HISTORICAL" ||
    historical.calculation.past_loss_jpy !== "120000" ||
    historical.calculation.future_failure_probability !== null
  )
    throw new Error("Historical record mismatch");
  console.log(
    JSON.stringify({
      result: "PASS",
      maintenance: "REGISTERED_INPUT",
      workflow: "CREATE_UPDATE_DISTINCT_MANAGER_APPROVAL_REQUESTER_EXECUTE",
      agent: "REAL_LLM_REGISTERED_TOOLS",
    }),
  );
}
