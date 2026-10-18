import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.LINESCOPE_BROWSER_URL,
  token = process.env.LINESCOPE_BROWSER_TOKEN,
  approver = process.env.LINESCOPE_BROWSER_APPROVER_TOKEN;
const output = process.env.LINESCOPE_BROWSER_OUTPUT ?? "/tmp/incident";
if (!base || !token || !approver)
  throw new Error("Explicit demo URL and credentials required");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const stages = [],
  errors = [];
let phase = "login";
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
page.on("pageerror", (e) => errors.push(e.message));
page.setDefaultTimeout(15000);
async function mark(stage, details = {}) {
  phase = stage;
  stages.push({ stage, ...details });
  await page.screenshot({
    path: `${output}/${stages.length}-${stage}.png`,
    fullPage: true,
  });
  console.log(JSON.stringify(stages.at(-1)));
}
async function login(p, t) {
  await p.goto(base);
  await p.getByLabel("Bearer token").fill(t);
  await p.getByRole("button", { name: "接続する", exact: true }).click();
  await expect(
    p.getByRole("navigation", { name: "調査に続く操作" }),
  ).toBeVisible();
}
async function step(p, name) {
  await p
    .getByRole("navigation", { name: "調査に続く操作" })
    .getByRole("button", { name, exact: true })
    .click();
}
async function responseClick(button, path) {
  const wait = page.waitForResponse(
    (r) => r.url().endsWith(`/api${path}`) && r.request().method() === "POST",
    { timeout: 150000 },
  );
  await button.click();
  const r = await wait;
  const body = await r.json();
  if (r.status() !== 200)
    throw new Error(`${path}: ${r.status()} ${JSON.stringify(body.errors)}`);
  return body;
}
async function settings() {
  if (!(await page.locator(".incident-controls").evaluate((e) => e.open)))
    await page.locator(".incident-controls > summary").click();
}
async function prepareState(code, state) {
  const card = page
    .locator(".incident-loss article")
    .filter({ hasText: code + "：" });
  await card.getByText("この設備の登録状態を変更する", { exact: true }).click();
  await card
    .getByLabel(`変更後の登録状態（${code}）`, { exact: true })
    .selectOption(state);
  await card
    .getByRole("button", { name: "状態変更の準備へ", exact: true })
    .click();
  const saved = await responseClick(
    page
      .locator(".action-panel")
      .getByRole("button", { name: "変更準備を作成", exact: true }),
    "/agent",
  );
  if (!saved.data.update_request_id) throw new Error("State Prepare missing");
  await approveAndExecute(saved.data.update_request_id);
}
async function investigate() {
  const body = await responseClick(
    page.getByRole("button", {
      name: "選択した設備の影響と被害額を調べる",
      exact: true,
    }),
    "/incidents/investigate",
  );
  await expect(
    page.getByRole("status").filter({ hasText: "正本データと関係" }),
  ).toHaveCount(0, { timeout: 60000 });
  return body;
}
async function approveAndExecute(id) {
  const other = await browser.newPage();
  await login(other, approver);
  await step(other, "変更・承認・実行");
  const a = other.locator(".action-panel");
  await a.getByLabel("変更要求ID", { exact: true }).fill(id);
  await a
    .getByRole("button", { name: "保存状態を再取得", exact: true })
    .click();
  await a.getByLabel("保存Snapshotと操作内容を確認しました").check();
  await a.getByRole("button", { name: "Snapshotを承認", exact: true }).click();
  await expect(a.getByText(/状態：APPROVED/)).toBeVisible();
  await other.close();
  await step(page, "変更・承認・実行");
  const action = page.locator(".action-panel");
  await action.getByLabel("変更要求ID", { exact: true }).fill(id);
  await action
    .getByRole("button", { name: "保存状態を再取得", exact: true })
    .click();
  await expect(action.getByText(/状態：APPROVED/)).toBeVisible();
  await action.getByLabel("保存Snapshotと操作内容を確認しました").check();
  await action
    .getByRole("button", { name: "承認済み変更を実行", exact: true })
    .click();
  await expect(action.getByText(/状態：COMPLETED/)).toBeVisible();
}
try {
  await login(page, token);
  const loss = page.getByRole("complementary", { name: "推定被害額" });
  await expect(loss).toContainText("未算出");
  await mark("entry-and-visible-loss-placeholder");
  await page
    .getByRole("button", { name: "設備と損失根拠を確認する", exact: true })
    .click();
  await page.getByRole("checkbox", { name: /M-204/ }).check();
  await page.getByRole("checkbox", { name: /M-208/ }).check();
  const first = await investigate();
  if (first.data.loss.loss_per_hour !== "250000")
    throw new Error("Expected shared-scope estimate 250000");
  await expect(loss.locator(".incident-amount")).toHaveText("250,000 円／時間");
  await expect(
    page.locator(".incident-workspace .react-flow__node.entity-Equipment"),
  ).toHaveCount(2);
  await expect(
    page.locator(".incident-workspace .react-flow__node.entity-Product"),
  ).toHaveCount(3);
  await mark("two-machine-impact-and-loss", {
    loss_per_hour: first.data.loss.loss_per_hour,
    scope_count: first.data.loss.items.length,
  });
  await loss.getByText("損失の内訳と出典", { exact: true }).click();
  await expect(loss).toContainText("factory-v1:P-100");
  await page
    .locator(".incident-workspace .react-flow__node.entity-Product")
    .first()
    .click();
  await expect(
    page.locator(".incident-workspace .path-highlight").first(),
  ).toBeVisible();
  await mark("shared-impact-path-and-breakdown");
  await settings();
  await page
    .getByLabel("損失評価の開始", { exact: true })
    .fill("2026-10-17T00:00:00Z");
  await expect(loss.locator(".incident-amount")).toHaveText("未算出");
  const mismatch = await investigate();
  if (mismatch.data.loss.loss_per_hour !== null)
    throw new Error("Period mismatch became complete loss");
  await expect(loss).toContainText("根拠と評価期間が一致しません");
  await settings();
  await page
    .getByLabel("損失評価の開始", { exact: true })
    .fill("2026-10-18T00:00:00Z");
  await investigate();
  await mark("period-mismatch-not-zero");
  await loss
    .locator("article")
    .filter({ hasText: "M-204：" })
    .getByRole("button", { name: "この設備の対応案を比べる" })
    .click();
  const comparison = page.locator(".registered-comparison");
  await comparison
    .getByRole("button", {
      name: "比較に使う正式入力の候補を取得",
      exact: true,
    })
    .click();
  await expect(comparison.getByText("正式入力を確認中…")).toHaveCount(0);
  await comparison.getByLabel(/M-204-INCIDENT-ECONOMIC/).check();
  await comparison
    .getByRole("button", {
      name: "入力・出典を確認：M-204-INCIDENT-ECONOMIC",
      exact: true,
    })
    .click();
  await comparison
    .getByRole("button", { name: "選択した正式入力で比較する", exact: true })
    .click();
  await expect(
    comparison.getByRole("heading", { name: "対応案を比較する", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".incident-workspace .react-flow")).toBeVisible();
  await mark("compare-with-graph-retained");
  await step(page, "根拠を確かめる");
  const documents = await responseClick(
    page.getByRole("button", { name: "選択設備の関連文書を検索", exact: true }),
    "/agent",
  );
  if (
    documents.data.search_source !== "QDRANT" ||
    !documents.evidence.citations.length
  )
    throw new Error("Real vector citation missing");
  await mark("real-vector-evidence", {
    citations: documents.evidence.citations.length,
  });
  await step(page, "入力を登録・訂正");
  const econ = page.locator(".economic-panel:not(.registered-comparison)");
  await econ
    .getByRole("button", { name: "登録済み経済入力を検索", exact: true })
    .click();
  await econ
    .getByRole("region", { name: "経済入力の検索候補" })
    .getByRole("button", { name: /M-204-INCIDENT-ECONOMIC/ })
    .click();
  await econ
    .getByRole("button", { name: "この経済入力の訂正を準備", exact: true })
    .click();
  const editor = page.getByRole("region", { name: "経済入力の登録・訂正" });
  await expect(
    editor.getByText("調査用の停止損失根拠（円／時間）", { exact: true }),
  ).toBeVisible();
  await editor
    .getByLabel("時間当たり損失：factory-v1:P-200", { exact: true })
    .fill("80001");
  const saved = await responseClick(
    editor.getByRole("button", {
      name: "経済入力の変更準備を作成",
      exact: true,
    }),
    "/economic-inputs/prepare",
  );
  const preparedId = saved.data.update_request_id;
  const payload = saved.data.canonical_snapshot.targets[0].after.payload;
  if (
    payload.incident_losses.length !== 2 ||
    !payload.incident_losses.every((r) => r.product_id && r.source)
  )
    throw new Error("Incident scopes dropped on edit");
  await approveAndExecute(preparedId);
  await expect(loss.locator(".incident-amount")).toHaveText("未算出");
  await expect(loss).toContainText("変更確定前の結果");
  const refreshed = await responseClick(
    loss.getByRole("button", { name: "影響と被害額を再取得する", exact: true }),
    "/incidents/investigate",
  );
  if (refreshed.data.loss.loss_per_hour !== "250001")
    throw new Error("Confirmed input version not reflected");
  await expect(loss.locator(".incident-amount")).toHaveText("250,001 円／時間");
  await mark("approved-economic-edit-and-loss-refresh", {
    update_request_id: preparedId,
  });
  // Explicit user command prepares the existing state update; approval and execution stay in UI.
  await prepareState("M-208", "RUNNING");
  await expect(loss.locator(".incident-amount")).toHaveText("未算出");
  const after = await responseClick(
    loss.getByRole("button", { name: "影響と被害額を再取得する", exact: true }),
    "/incidents/investigate",
  );
  if (after.data.loss.loss_per_hour !== "200001")
    throw new Error("Current state not reflected");
  await expect(loss.locator(".incident-amount")).toHaveText("200,001 円／時間");
  await mark("state-confirmed-and-investigation-refreshed", {
    loss_per_hour: after.data.loss.loss_per_hour,
    actual_damage_confirmed: after.data.loss.actual_damage_confirmed,
  });
  for (const width of [390, 768, 1600]) {
    await page.setViewportSize({ width, height: 1100 });
    if (
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth >
          document.documentElement.clientWidth,
      )
    )
      throw new Error(`Overflow at ${width}`);
    await page.screenshot({
      path: `${output}/width-${width}.png`,
      fullPage: true,
    });
  }
  // Restore only this scenario's changes through the same approved UI workflow.
  await prepareState("M-208", "STOPPED");
  await responseClick(
    loss.getByRole("button", { name: "影響と被害額を再取得する", exact: true }),
    "/incidents/investigate",
  );
  await loss
    .locator("article")
    .filter({ hasText: "M-204：" })
    .getByRole("button", { name: "この設備の対応案を比べる" })
    .click();
  await step(page, "入力を登録・訂正");
  await econ
    .getByRole("button", { name: "登録済み経済入力を検索", exact: true })
    .click();
  await econ
    .getByRole("region", { name: "経済入力の検索候補" })
    .getByRole("button", { name: /M-204-INCIDENT-ECONOMIC/ })
    .click();
  await econ
    .getByRole("button", { name: "この経済入力の訂正を準備", exact: true })
    .click();
  await editor
    .getByLabel("時間当たり損失：factory-v1:P-200", { exact: true })
    .fill("80000");
  const restore = await responseClick(
    editor.getByRole("button", {
      name: "経済入力の変更準備を作成",
      exact: true,
    }),
    "/economic-inputs/prepare",
  );
  await approveAndExecute(restore.data.update_request_id);
  const restored = await responseClick(
    loss.getByRole("button", { name: "影響と被害額を再取得する", exact: true }),
    "/incidents/investigate",
  );
  if (restored.data.loss.loss_per_hour !== "250000")
    throw new Error("Demo starting values not restored");
  await mark("demo-values-restored-with-audit-history");
  const draftCard = loss.locator("article").filter({ hasText: "M-208：" });
  await draftCard
    .getByText("この設備の登録状態を変更する", { exact: true })
    .click();
  await draftCard
    .getByLabel("変更後の登録状態（M-208）", { exact: true })
    .selectOption("UNDER_MAINTENANCE");
  await draftCard
    .getByRole("button", { name: "状態変更の準備へ", exact: true })
    .click();
  await expect(
    page.getByLabel("明示的な変更指示", { exact: true }),
  ).toHaveValue(/M-208/);
  await loss
    .locator("article")
    .filter({ hasText: "M-204：" })
    .getByRole("button", { name: "この設備の対応案を比べる" })
    .click();
  await step(page, "変更・承認・実行");
  await expect(
    page.getByLabel("明示的な変更指示", { exact: true }),
  ).toHaveValue("");
  await mark("target-switch-discards-old-change-draft");
  if (errors.length) throw new Error("Browser runtime errors");
  await writeFile(
    `${output}/report.json`,
    JSON.stringify(
      {
        result: "PASS",
        scope: "INCIDENT_UI_REAL_SERVICES",
        stages,
        browser_errors: errors,
      },
      null,
      2,
    ),
  );
} catch (e) {
  await writeFile(
    `${output}/report.json`,
    JSON.stringify(
      {
        result: "FAIL",
        phase,
        error: String(e),
        stages,
        browser_errors: errors,
      },
      null,
      2,
    ),
  );
  if (phase !== "login")
    await page.screenshot({ path: `${output}/failure.png`, fullPage: true });
  throw e;
} finally {
  await browser.close();
}
