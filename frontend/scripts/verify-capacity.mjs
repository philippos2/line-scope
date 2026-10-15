import { expect } from "@playwright/test";

export async function verifyCapacity(page, token, approver) {
  console.log(JSON.stringify({ capacity_stage: "equipment-selection" }));
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
      capacity_stage: "equipment-response",
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
  const panel = page.locator(".capacity-panel");
  await panel.locator("summary").click();
  await panel.getByRole("button", { name: "選択設備の能力入力を登録" }).click();
  const editor = panel.getByRole("region", { name: "能力入力の登録・訂正" });
  await editor
    .getByLabel("能力入力の入力コード", { exact: true })
    .fill("UI-CAPACITY");
  await editor.getByLabel("製品名・コード", { exact: true }).fill("P-100");
  await editor.getByRole("button", { name: "製品候補を探す" }).click();
  await editor
    .getByRole("region", { name: "製品の検索候補" })
    .getByRole("button", { name: /P-100/ })
    .click();
  await editor
    .getByLabel("能力評価開始", { exact: true })
    .fill("2026-10-01T00:00:00Z");
  await editor
    .getByLabel("能力評価終了", { exact: true })
    .fill("2026-10-02T00:00:00Z");
  await editor.getByLabel("数量単位", { exact: true }).fill("個");
  for (const [label, value] of [
    ["必要能力", "90"],
    ["通常能力", "100"],
    ["使用中負荷", "20"],
    ["予約負荷", "20"],
  ])
    await editor.getByLabel(label, { exact: true }).fill(value);
  await editor
    .getByLabel("使用中負荷と予約負荷に重複がないことを確認した")
    .check();
  await editor.getByLabel("この期間の負荷を網羅した").check();
  await editor
    .getByRole("combobox", { name: /^製品互換性/ })
    .selectOption("yes");
  const hostile =
    '<img src="/never-fetch-capacity" onerror="window.capacityCommandExecuted=true">';
  await editor.getByLabel("能力入力の出典", { exact: true }).fill(hostile);
  await editor.getByLabel("bufferと復旧条件を入力する").check();
  await editor.getByLabel("利用可能buffer", { exact: true }).fill("120");
  await editor
    .getByLabel("停止開始日時", { exact: true })
    .fill("2026-10-01T00:00:00Z");
  await editor.getByLabel("評価期間中の需要と供給は一定").check();
  await editor.getByLabel("bufferの他用途への引当はない").check();
  await editor.getByLabel("復旧後は必要量を満たせる").check();
  async function prepare() {
    const response = page.waitForResponse(
      (value) =>
        value.url().endsWith("/api/capacity-inputs/prepare") &&
        value.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "能力入力の変更準備を作成" })
      .click();
    const body = await (await response).json();
    if (body.status !== "ok") throw new Error("Capacity Prepare failed");
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
      .getByLabel("能力入力コード", { exact: true })
      .fill("UI-CAPACITY");
    await panel.getByRole("button", { name: "登録済み能力入力を検索" }).click();
    const read = page.waitForResponse(
      (value) =>
        value.url().includes("/api/capacity-inputs/") &&
        value.request().method() === "GET",
    );
    await panel
      .getByRole("region", { name: "能力入力の検索候補" })
      .getByRole("button", { name: /UI-CAPACITY/ })
      .click();
    const result = await (await read).json();
    if (result.data.source !== "REGISTERED_INPUT")
      throw new Error("Registered capacity source missing");
    return result.data;
  }
  console.log(JSON.stringify({ capacity_stage: "prepare-approve-execute" }));
  await confirm(await prepare());
  const registered = await load();
  if (
    registered.calculation.shortage_rate !== "30" ||
    registered.calculation.permissible_downtime_hours !== "4"
  )
    throw new Error("Capacity calculation mismatch");
  const result = panel.getByRole("region", {
    name: "登録済み能力入力の計算結果",
  });
  await expect(
    result.getByRole("heading", { name: "能力不足", exact: true }),
  ).toBeVisible();
  await expect(
    result.getByText("条件付き許容停止時間：4 時間", { exact: true }),
  ).toBeVisible();
  await expect(result.locator("img")).toHaveCount(0);
  if (await page.evaluate(() => globalThis.capacityCommandExecuted === true))
    throw new Error("Source executed");
  await panel
    .getByRole("button", { name: "この能力入力をAgentへ問い合わせる" })
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
  if (
    !agent.data.tool_results?.some(
      (item) => item.tool === "get_capacity_input",
    ) ||
    !agent.answer?.includes("不足30") ||
    !agent.answer?.includes("条件付き許容停止時間4時間")
  )
    throw new Error("Registered capacity Agent read failed");
  await expect(
    page.getByRole("heading", {
      name: "正式能力入力：UI-CAPACITY",
      exact: true,
    }),
  ).toHaveCount(2);
  console.log(JSON.stringify({ capacity_stage: "unknown-update" }));
  await panel.getByRole("button", { name: "この能力入力の訂正を準備" }).click();
  await expect(editor.getByLabel("予約負荷", { exact: true })).toHaveValue(
    "20",
  );
  await editor.getByLabel("予約負荷", { exact: true }).fill("");
  await confirm(await prepare());
  const updated = await load();
  if (
    updated.input.version !== 2 ||
    updated.calculation.available_rate !== null ||
    updated.calculation.recovery_deadline !== null
  )
    throw new Error("Unknown load became spare capacity");
  await expect(
    result.getByRole("heading", { name: "能力判定不明", exact: true }),
  ).toBeVisible();
  console.log(
    JSON.stringify({
      result: "PASS",
      capacity: "REGISTERED_INPUT",
      workflow: "CREATE_UPDATE_DISTINCT_MANAGER_APPROVAL_REQUESTER_EXECUTE",
      agent: "REAL_LLM_REGISTERED_TOOLS",
    }),
  );
}
