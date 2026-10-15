import { expect } from "@playwright/test";

export async function verifyEconomics(page, token, approver) {
  console.log(JSON.stringify({ economic_stage: "equipment-selection" }));
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
      economic_stage: "equipment-response",
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
  console.log(JSON.stringify({ economic_stage: "form" }));
  const panel = page.locator(".economic-panel");
  await panel.locator("summary").click();
  await panel.getByRole("button", { name: "選択設備の経済入力を登録" }).click();
  const editor = panel.getByRole("region", { name: "経済入力の登録・訂正" });
  await editor.getByLabel("入力コード", { exact: true }).fill("UI-ECONOMIC");
  await editor
    .getByLabel("比較開始", { exact: true })
    .fill("2026-10-01T00:00:00Z");
  await editor
    .getByLabel("比較終了", { exact: true })
    .fill("2026-10-02T00:00:00Z");
  await editor.getByLabel("稼働時間", { exact: true }).fill("16");
  console.log(JSON.stringify({ economic_stage: "cost-items" }));
  const repair = editor.getByRole("group", { name: "修理", exact: true });
  async function fillItem(group, n, key, kind, amount, hours, source) {
    const item = group.getByRole("group", {
      name: `費用項目 ${n}`,
      exact: true,
    });
    await item.getByLabel("項目キー", { exact: true }).fill(key);
    await item.getByRole("combobox", { name: /^費用種別/ }).selectOption(kind);
    await item
      .getByLabel(kind === "DIRECT" ? "直接費（JPY）" : "損失率（JPY/hour）", {
        exact: true,
      })
      .fill(amount);
    if (kind !== "DIRECT")
      await item.getByLabel("損失時間", { exact: true }).fill(hours);
    await item.getByLabel("出典", { exact: true }).fill(source);
    await item.getByLabel("他の項目と重複しないことを確認した").check();
  }
  const hostile =
    '<img src="/never-fetch-economic" onerror="window.economicCommandExecuted=true">';
  await fillItem(repair, 1, "repair-fee", "DIRECT", "300000", "", hostile);
  for (const [n, key, rate] of [
    [2, "P100", "120000"],
    [3, "P200", "80000"],
  ]) {
    await repair.getByRole("button", { name: "費用項目を追加" }).click();
    await fillItem(repair, n, key, "STOPPAGE", rate, "8", "生産損失見積");
  }
  await repair.getByLabel("この期間に必要な費用項目を網羅した").check();
  await fillItem(
    editor.getByRole("group", { name: "交換", exact: true }),
    1,
    "replace-fee",
    "DIRECT",
    "3000000",
    "",
    "交換見積。停止損失は未調査",
  );
  await fillItem(
    editor.getByRole("group", { name: "継続", exact: true }),
    1,
    "degradation",
    "DEGRADATION",
    "1000",
    "16",
    "劣化損失見積",
  );
  console.log(JSON.stringify({ economic_stage: "prepare" }));
  const response = page.waitForResponse(
    (value) =>
      value.url().endsWith("/api/economic-inputs/prepare") &&
      value.request().method() === "POST",
  );
  await editor
    .getByRole("button", { name: "経済入力の変更準備を作成" })
    .click();
  const prepared = await (await response).json();
  if (prepared.status !== "ok") throw new Error("Economic Prepare failed");
  const id = prepared.data.update_request_id;
  const action = page.locator(".action-panel");
  if (!(await action.evaluate((element) => element.open)))
    await action.locator("summary").click();
  await action.getByRole("button", { name: "直近の変更要求を開く" }).click();
  await expect(action.getByText(/状態：WAITING_APPROVAL/)).toBeVisible();
  await action.getByLabel("保存Snapshotと操作内容を確認しました").check();
  await action
    .getByRole("button", { name: "Snapshotを承認", exact: true })
    .click();
  await expect(action.getByRole("alert")).toContainText("AUTHORIZATION_DENIED");
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
  console.log(JSON.stringify({ economic_stage: "approval" }));
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
  console.log(JSON.stringify({ economic_stage: "registered-read" }));
  await page.locator(".economic-panel summary").click();
  await page.getByLabel("経済入力コード", { exact: true }).fill("UI-ECONOMIC");
  await page.getByRole("button", { name: "登録済み経済入力を検索" }).click();
  await page
    .getByRole("region", { name: "経済入力の検索候補" })
    .getByRole("button", { name: /UI-ECONOMIC/ })
    .click();
  const result = page.getByRole("region", {
    name: "登録済み経済入力の計算結果",
  });
  await expect(result.getByText("1900000 JPY", { exact: true })).toBeVisible();
  await expect(result.getByText("不明", { exact: true }).first()).toBeVisible();
  await expect(result.locator("img")).toHaveCount(0);
  if (await page.evaluate(() => globalThis.economicCommandExecuted === true))
    throw new Error("Economic source executed");
  await page.getByRole("button", { name: "この経済入力の訂正を準備" }).click();
  await expect(
    page
      .getByRole("region", { name: "経済入力の登録・訂正" })
      .getByLabel("稼働時間", { exact: true }),
  ).toHaveValue("16");
  await page.getByRole("button", { name: "編集を閉じる" }).click();
  await page
    .getByRole("button", { name: "この経済入力をAgentへ問い合わせる" })
    .click();
  console.log(JSON.stringify({ economic_stage: "agent-read" }));
  const agent = page.waitForResponse(
    (value) =>
      value.url().endsWith("/api/agent") && value.request().method() === "POST",
    { timeout: 90000 },
  );
  await page
    .getByRole("button", { name: "問い合わせを送信", exact: true })
    .click();
  const read = await (await agent).json();
  if (
    !read.data.tool_results?.some(
      (item) => item.tool === "get_economic_input",
    ) ||
    !read.answer?.includes("交換総額不明")
  )
    throw new Error("Registered economic Agent read failed");
  await expect(
    page.getByRole("heading", {
      name: "正式経済入力：UI-ECONOMIC",
      exact: true,
    }),
  ).toHaveCount(2);
  await page.screenshot({ path: "/tmp/frontend-economic.png", fullPage: true });
  console.log(
    JSON.stringify({
      result: "PASS",
      economic: "REGISTERED_INPUT",
      workflow: "FORM_PREPARE_DISTINCT_MANAGER_APPROVAL_REQUESTER_EXECUTE",
      agent: "REAL_LLM_REGISTERED_TOOLS",
    }),
  );
}
