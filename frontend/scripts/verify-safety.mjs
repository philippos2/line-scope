import { expect } from "@playwright/test";

export async function verifySafety(page, token, approver) {
  console.log(JSON.stringify({ safety_stage: "equipment-selection" }));
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
      safety_stage: "equipment-response",
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
  const panel = page.locator(".safety-panel");
  await panel.locator("summary").click();
  await panel.getByRole("button", { name: "選択設備の安全入力を登録" }).click();
  const editor = panel.getByRole("region", { name: "安全入力の登録・訂正" });
  await editor
    .getByLabel("安全入力の入力コード", { exact: true })
    .fill("UI-SAFETY");
  await editor
    .getByLabel("安全情報の適用開始", { exact: true })
    .fill("2020-01-01T00:00:00Z");
  await editor
    .getByLabel("安全情報の適用終了", { exact: true })
    .fill("2099-01-01T00:00:00Z");
  await editor
    .getByLabel("観測内容", { exact: true })
    .fill("点検で停止基準を超えたことを確認");
  await editor
    .getByLabel("適用する安全基準", { exact: true })
    .fill("試験用の承認済み基準S-1");
  await editor
    .getByLabel("継続条件", { exact: true })
    .fill("停止必須のため継続不可");
  await editor
    .getByLabel("安全判断の出典", { exact: true })
    .fill(
      '<img src="/never-fetch-safety" onerror="window.safetyCommandExecuted=true">',
    );
  await editor
    .getByRole("combobox", { name: /^安全判定/ })
    .selectOption("STOP_REQUIRED");
  await editor
    .getByRole("combobox", { name: /^安全判断の確度/ })
    .selectOption("CONFIRMED");
  async function prepare() {
    const response = page.waitForResponse(
      (value) =>
        value.url().endsWith("/api/safety-inputs/prepare") &&
        value.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "安全入力の変更準備を作成" })
      .click();
    const body = await (await response).json();
    if (body.status !== "ok") throw new Error("Safety Prepare failed");
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
    await panel.getByLabel("安全入力コード", { exact: true }).fill("UI-SAFETY");
    await panel.getByRole("button", { name: "登録済み安全入力を検索" }).click();
    const read = page.waitForResponse(
      (value) =>
        value.url().includes("/api/safety-inputs/") &&
        value.request().method() === "GET",
    );
    await panel
      .getByRole("region", { name: "安全入力の検索候補" })
      .getByRole("button", { name: /UI-SAFETY/ })
      .click();
    const result = await (await read).json();
    if (result.data.source !== "REGISTERED_INPUT")
      throw new Error("Registered safety source missing");
    return result.data;
  }
  console.log(JSON.stringify({ safety_stage: "prepare-approve-execute" }));
  await confirm(await prepare());
  const registered = await load();
  if (
    registered.calculation.status !== "STOP_REQUIRED" ||
    registered.calculation.continue_candidate !== "EXCLUDED"
  )
    throw new Error("Safety verdict mismatch");
  const result = panel.getByRole("region", {
    name: "登録済み安全入力の判定結果",
  });
  await expect(
    result.getByRole("heading", { name: "停止必須", exact: true }),
  ).toBeVisible();
  await expect(result.locator("img")).toHaveCount(0);
  if (await page.evaluate(() => globalThis.safetyCommandExecuted === true))
    throw new Error("Source executed");
  await panel
    .getByRole("button", { name: "この安全入力をAgentへ問い合わせる" })
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
      (item) => item.tool === "get_safety_input",
    ) ||
    !agent.answer?.includes("継続案を候補から除外")
  )
    throw new Error("Registered safety Agent read failed");
  await expect(
    page.getByRole("heading", {
      name: "正式安全入力：UI-SAFETY",
      exact: true,
    }),
  ).toHaveCount(2);
  console.log(JSON.stringify({ safety_stage: "unknown-update" }));
  await panel.getByRole("button", { name: "この安全入力の訂正を準備" }).click();
  await expect(editor.getByRole("combobox", { name: /^安全判定/ })).toHaveValue(
    "STOP_REQUIRED",
  );
  await editor
    .getByRole("combobox", { name: /^安全判定/ })
    .selectOption("UNKNOWN");
  await confirm(await prepare());
  const updated = await load();
  if (
    updated.input.version !== 2 ||
    updated.calculation.status !== "UNKNOWN" ||
    updated.calculation.continue_candidate !== "UNASSESSED"
  )
    throw new Error("Unknown declaration became safety permission");
  await expect(
    result.getByRole("heading", { name: "不明", exact: true }),
  ).toBeVisible();
  console.log(
    JSON.stringify({
      result: "PASS",
      safety: "REGISTERED_INPUT",
      workflow: "CREATE_UPDATE_DISTINCT_MANAGER_APPROVAL_REQUESTER_EXECUTE",
      agent: "REAL_LLM_REGISTERED_TOOLS",
    }),
  );
}
