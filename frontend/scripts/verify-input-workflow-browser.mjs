// Isolated environment only: creates registered inputs through real Prepare/Approval/Execute.
import { URL } from "node:url";
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.LINESCOPE_BROWSER_URL;
const owner = process.env.LINESCOPE_BROWSER_TOKEN;
const approver = process.env.LINESCOPE_BROWSER_APPROVER;
if (!base || !owner || !approver || !process.env.LINESCOPE_BROWSER_ALLOW_WRITES)
  throw new Error(
    "Isolated writable browser environment and explicit write opt-in required",
  );
if (
  process.env.LINESCOPE_BROWSER_ALLOW_WRITES !== "isolated-verification" ||
  ["5173", "5174"].includes(new URL(base).port)
)
  throw new Error("Writable checks must not target the persistent previews");
const out = process.env.LINESCOPE_BROWSER_OUTPUT ?? "/out";
await mkdir(out, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1600, height: 1050 },
});
const page = await context.newPage();
const report = [];
const suffix = Date.now();
async function connect(secret) {
  await page.getByLabel("Bearer token").fill(secret);
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await expect(
    page.getByRole("tab", { name: "接続及び影響範囲", exact: true }),
  ).toBeVisible();
}
async function switchUser(secret) {
  await page.getByRole("button", { name: "接続解除", exact: true }).click();
  await connect(secret);
  await page
    .getByRole("tab", { name: "変更・承認・実行", exact: true })
    .click();
}
async function choose() {
  await page.getByLabel("設備名・コード", { exact: true }).fill("M-204");
  await page.getByRole("button", { name: "検索", exact: true }).click();
  await page
    .locator(".equipment-search-panel > .equipment-result")
    .first()
    .click();
}
async function load(id) {
  await page.getByLabel("変更要求ID", { exact: true }).fill(id);
  await page
    .getByRole("button", { name: "保存状態を再取得", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "保存済みSnapshot" }),
  ).toBeVisible();
}
async function settleApproval() {
  await page
    .getByRole("button", { name: "直近の変更要求を開く", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "保存済みSnapshot" }),
  ).toBeVisible();
  const id = await page.getByLabel("変更要求ID", { exact: true }).inputValue();
  await page.getByLabel("保存Snapshotと操作内容を確認しました").check();
  await expect(
    page.getByRole("button", { name: "Snapshotを承認", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText(/この入力の依頼者は承認できません/),
  ).toBeVisible();
  await switchUser(approver);
  await load(id); // Equipment selection is intentionally omitted for the approver.
  await page.getByLabel("保存Snapshotと操作内容を確認しました").check();
  await page
    .getByRole("button", { name: "Snapshotを承認", exact: true })
    .click();
  await expect(page.getByText(/状態：承認済み/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "承認済み変更を実行", exact: true }),
  ).toBeDisabled();
  await switchUser(owner);
  await load(id);
  await page.getByLabel("保存Snapshotと操作内容を確認しました").check();
  await page
    .getByRole("button", { name: "承認済み変更を実行", exact: true })
    .click();
  await expect(page.getByText(/状態：実行済み/)).toBeVisible();
  return id;
}
const categories = [
  {
    key: "economic",
    tab: "費用・経済",
    create: "選択設備の経済入力を登録",
    editor: "経済入力の登録・訂正",
    code: "入力コード",
    start: "比較開始",
    end: "比較終了",
    submit: "経済入力の変更準備を作成",
  },
  {
    key: "capacity",
    tab: "生産能力",
    create: "選択設備の能力入力を登録",
    editor: "能力入力の登録・訂正",
    code: "能力入力の入力コード",
    start: "能力評価開始",
    end: "能力評価終了",
    submit: "能力入力の変更準備を作成",
  },
  {
    key: "safety",
    tab: "安全条件",
    create: "選択設備の安全入力を登録",
    editor: "安全入力の登録・訂正",
    code: "安全入力の入力コード",
    start: "安全情報の適用開始",
    end: "安全情報の適用終了",
    submit: "安全入力の変更準備を作成",
  },
  {
    key: "maintenance",
    tab: "対応計画・故障履歴",
    create: "選択設備の対応計画・故障履歴を登録",
    editor: "対応計画・故障履歴の登録・訂正",
    code: "対応計画・故障履歴の入力コード",
    start: "評価・記録の期間開始",
    end: "評価・記録の期間終了",
    submit: "対応計画・故障履歴の変更準備を作成",
  },
];
try {
  await page.goto(base);
  await connect(owner);
  for (const item of categories) {
    await choose();
    await page
      .getByRole("tab", { name: "入力を登録・訂正", exact: true })
      .click();
    await page.getByRole("button", { name: item.tab, exact: true }).click();
    if (item.key === "safety") {
      await page
        .getByRole("button", { name: "登録済み安全入力を検索", exact: true })
        .click();
      await expect(page.locator(".safety-panel")).toContainText(
        "検索が完了しました。該当する登録済みの安全入力はありません。",
      );
      await expect(
        page.getByRole("button", { name: item.create, exact: true }),
      ).toBeEnabled();
    }
    await page.getByRole("button", { name: item.create, exact: true }).click();
    const editor = page.getByRole("region", { name: item.editor, exact: true });
    await editor
      .getByLabel(item.code, { exact: true })
      .fill(`B-${item.key}-${suffix}`);
    await editor
      .getByLabel(new RegExp(`^${item.start}`))
      .fill("2026-10-18T09:00");
    await editor
      .getByLabel(new RegExp(`^${item.end}`))
      .fill("2026-10-19T09:00");
    if (item.key === "economic") {
      await editor.getByLabel("稼働時間", { exact: true }).fill("24");
      const keys = editor.getByLabel("項目キー", { exact: true });
      for (let i = 0; i < (await keys.count()); i++)
        await keys.nth(i).fill(`費用${i + 1}`);
      const sources = editor.getByLabel("出典", { exact: true });
      for (let i = 0; i < (await sources.count()); i++)
        await sources.nth(i).fill("隔離環境の検証条件");
    } else if (item.key === "capacity") {
      await editor.getByLabel("製品名・コード", { exact: true }).fill("P-100");
      await editor
        .getByRole("button", { name: "製品候補を探す", exact: true })
        .click();
      await editor.getByRole("button", { name: /P-100/ }).first().click();
      await editor.getByLabel("数量単位", { exact: true }).fill("個");
      for (const [name, value] of [
        ["必要能力", "60"],
        ["通常能力", "120"],
        ["使用中負荷", "40"],
        ["予約負荷", "0"],
      ])
        await editor.getByLabel(name, { exact: true }).fill(value);
      await editor
        .getByLabel("能力入力の出典", { exact: true })
        .fill("隔離環境の検証条件");
    } else if (item.key === "safety") {
      await editor
        .getByLabel("観測内容", { exact: true })
        .fill("検証用の観測記録");
      await editor
        .getByLabel("適用する安全基準", { exact: true })
        .fill("検証条件");
      await editor
        .getByLabel("安全判断の出典", { exact: true })
        .fill("隔離環境の検証条件");
    } else {
      await editor
        .getByLabel("計画・事象の内容", { exact: true })
        .fill("隔離環境の対応計画");
      await editor
        .getByLabel("計画・実績の出典", { exact: true })
        .fill("隔離環境の検証条件");
    }
    const prepared = page.waitForResponse(
      (res) =>
        res.url().endsWith(`/${item.key}-inputs/prepare`) &&
        res.request().method() === "POST",
    );
    await editor
      .getByRole("button", { name: item.submit, exact: true })
      .click();
    const response = await prepared;
    if (!response.ok())
      throw new Error(
        `${item.key} prepare failed: ${JSON.stringify((await response.json()).errors)}`,
      );
    if (item.key === "economic") {
      await expect(
        page.getByRole("tab", { name: "入力を登録・訂正", exact: true }),
      ).toHaveAttribute("aria-selected", "true");
      await expect(
        editor.getByRole("button", { name: item.submit, exact: true }),
      ).toBeDisabled();
      await editor
        .getByRole("button", { name: "承認・実行の画面で開く", exact: true })
        .click();
    }
    await expect(
      page.getByRole("tab", { name: "変更・承認・実行", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    const id = await settleApproval();
    report.push({
      name: `${item.key}-real-workflow`,
      result: "PASS",
      request_id: id,
    });
    console.log("PASS", item.key, "real-workflow");
    await page.screenshot({ path: `${out}/b-${item.key}.png`, fullPage: true });
  }
  // Candidate retrieval failures, empty state, real suggestions, and free text.
  await choose();
  await page
    .getByRole("tab", { name: "入力を登録・訂正", exact: true })
    .click();
  await page
    .getByRole("button", { name: "対応計画・故障履歴", exact: true })
    .click();
  const panel = page.locator(".maintenance-panel");
  const assist = panel
    .locator("..")
    .getByRole("region", { name: "入力候補の案内" })
    .first();
  await page.route("**/api/maintenance-inputs/search", (route) =>
    route.fulfill({
      status: 503,
      json: {
        request_id: "controlled",
        context_id: null,
        status: "error",
        answer: null,
        data: {},
        evidence: {},
        warnings: [],
        errors: [{ code: "DEPENDENCY_UNAVAILABLE" }],
      },
    }),
  );
  await assist.getByRole("button", { name: "入力候補を取得・更新" }).click();
  await expect(assist).toContainText("候補を再取得できます");
  await page.unroute("**/api/maintenance-inputs/search");
  await assist.getByRole("button", { name: "入力候補を取得・更新" }).click();
  await expect(assist).toContainText(
    "件の登録データから入力候補を取得しました",
  );
  const query = panel.getByLabel("対応計画・故障履歴の設備名・コード", {
    exact: true,
  });
  await query.fill("加工機");
  await expect(
    panel.getByText("設備名またはコードを候補から選べます。", { exact: true }),
  ).toBeVisible();

  await expect
    .poll(async () => {
      const list = await query.getAttribute("list");
      return page.locator(`datalist[id="${list}"] option`).count();
    })
    .toBeGreaterThan(0);
  await query.fill("任意の検索語");
  await expect(query).toHaveValue("任意の検索語");
  const code = panel.getByLabel("対応計画・故障履歴コード", { exact: true });
  await code.focus();
  const list = await code.getAttribute("list");
  await expect(
    page.locator(
      `datalist[id="${list}"] option[value="B-maintenance-${suffix}"]`,
    ),
  ).toHaveCount(1);
  await page.getByLabel("設備名・コード", { exact: true }).fill("M-208");
  await page.getByRole("button", { name: "検索", exact: true }).click();
  await page
    .locator(".equipment-search-panel > .equipment-result")
    .first()
    .click();
  await page
    .locator(".maintenance-panel")
    .getByLabel("対応計画・故障履歴コード", { exact: true })
    .focus();
  await expect(page.locator(".maintenance-panel").locator("..")).toContainText(
    "この対象の登録データはありません",
  );
  report.push({ name: "candidate-retry-and-empty", result: "PASS" });
  console.log("PASS candidate-retry-and-empty");
  // A saved request survives a root change, and a late prepare cannot force a tab switch.
  await page
    .getByRole("tab", { name: "変更・承認・実行", exact: true })
    .click();
  await expect(page.getByLabel("変更要求ID", { exact: true })).toHaveValue(
    report[3].request_id,
  );
  await page
    .getByRole("tab", { name: "入力を登録・訂正", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "選択設備の対応計画・故障履歴を登録",
      exact: true,
    })
    .click();
  const editor = page.getByRole("region", {
    name: "対応計画・故障履歴の登録・訂正",
    exact: true,
  });
  await editor
    .getByLabel("対応計画・故障履歴の入力コード", { exact: true })
    .fill(`B-background-${suffix}`);
  await editor.getByLabel(/^評価・記録の期間開始/).fill("2026-10-18T09:00");
  await editor.getByLabel(/^評価・記録の期間終了/).fill("2026-10-19T09:00");
  await editor
    .getByLabel("計画・事象の内容", { exact: true })
    .fill("遅い応答の検証");
  await editor
    .getByLabel("計画・実績の出典", { exact: true })
    .fill("隔離環境の検証条件");
  let received;
  const held = new Promise((resolve) => {
    received = resolve;
  });
  let release;
  const hold = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/api/maintenance-inputs/prepare", async (route) => {
    const response = await route.fetch();
    if (!response.ok()) throw new Error("Background prepare failed");
    received();
    await hold;
    await route.fulfill({ response });
  });
  await editor
    .getByRole("button", {
      name: "対応計画・故障履歴の変更準備を作成",
      exact: true,
    })
    .click();
  await held;
  await page.getByRole("tab", { name: "質問する", exact: true }).click();
  release();
  await expect(
    page.getByRole("button", { name: "保存した変更要求を開く", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("tab", { name: "質問する", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  report.push({ name: "saved-request-and-background", result: "PASS" });
  console.log("PASS saved-request-and-background");
  await page.screenshot({ path: `${out}/b-background.png`, fullPage: true });
} catch (error) {
  await page.screenshot({ path: `${out}/b-failure.png`, fullPage: true });
  throw error;
} finally {
  await writeFile(
    `${out}/b-workflow-results.json`,
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
