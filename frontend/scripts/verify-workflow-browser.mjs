import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.LINESCOPE_BROWSER_URL;
const token = process.env.LINESCOPE_BROWSER_TOKEN;
const approver = process.env.LINESCOPE_BROWSER_APPROVER_TOKEN;
const output = process.env.LINESCOPE_BROWSER_OUTPUT ?? "/tmp/workflow";
if (!base || !token || !approver)
  throw new Error("Explicit browser credentials required");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const stages = [];
let phase = "login";
const code = `UI-STORY-${Date.now()}`;
const start = "2030-01-01T00:00:00Z",
  end = "2030-01-02T00:00:00Z";
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  async function mark(name, details = {}) {
    phase = name;
    stages.push({ stage: name, ...details });
    console.log(JSON.stringify(stages.at(-1)));
    await page.screenshot({
      path: `${output}/${stages.length}-${name}.png`,
      fullPage: true,
    });
  }
  async function login(value, targetPage = page) {
    await targetPage.getByLabel("Bearer token").fill(value);
    await targetPage
      .getByRole("button", { name: "接続する", exact: true })
      .click();
    await expect(
      targetPage.getByRole("navigation", { name: "調査に続く操作" }),
    ).toBeVisible();
    await targetPage
      .getByRole("button", { name: "設備単位の詳しい調査", exact: true })
      .click();
  }
  async function step(name) {
    await page
      .getByRole("navigation", { name: "調査に続く操作" })
      .getByRole("button", { name })
      .click();
  }
  async function agent(button) {
    await expect(button).toBeEnabled({ timeout: 150000 });
    const waiting = page.waitForResponse(
      (r) => r.url().endsWith("/api/agent") && r.request().method() === "POST",
      { timeout: 150000 },
    );
    const before = Date.now();
    await button.click();
    const response = await waiting,
      body = await response.json();
    if (response.status() !== 200 || body.errors.length)
      throw new Error(
        `Agent failed: ${response.status()} ${body.errors.map((x) => x.code).join(",")}`,
      );
    return { body, seconds: Math.round((Date.now() - before) / 100) / 10 };
  }
  await page.goto(base);
  await login(token);
  await mark("login");
  const discovered = await agent(
    page.getByRole("button", {
      name: "登録設備を表示して調査を始める",
      exact: true,
    }),
  );
  const initialGraph = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/agent") &&
      r
        .request()
        .postDataJSON()
        ?.message?.includes("異常について影響・修理・交換・代替を比較して"),
    { timeout: 150000 },
  );
  await page
    .getByRole("region", { name: "設備検索の候補" })
    .getByRole("button", { name: /M-204/ })
    .click();
  const firstGraphResponse = await initialGraph;
  const firstGraphBody = await firstGraphResponse.json();
  if (firstGraphResponse.status() !== 200)
    throw new Error("Initial relationship query failed");
  await expect(
    page.getByRole("heading", {
      name: "何とつながり、どこまで影響するか",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator(".react-flow")).toBeVisible({ timeout: 150000 });
  await mark("equipment-selected", { seconds: discovered.seconds });
  const state = await agent(
    page.getByRole("button", { name: "現在状態を確認", exact: true }),
  );
  if (
    !state.body.data.tool_results?.some(
      (row) => row.tool === "get_equipment_state",
    )
  )
    throw new Error("State not fetched");
  await mark("state", { seconds: state.seconds });
  const graph = firstGraphBody.data.decision_package?.impact;
  if (!graph || graph.complete !== true || graph.reached_nodes.length !== 6)
    throw new Error("Expected six downstream candidates from real graph");
  await expect(page.locator(".react-flow")).toBeVisible();
  await mark("impact", { reached: graph.reached_nodes.length });
  await page
    .getByLabel("表示するGraph分析")
    .selectOption("upstream_dependencies");
  await expect(
    page.locator(".react-flow__node.entity-InfrastructureResource"),
  ).toBeVisible();
  if (
    (await page.locator(".node-classification").allTextContents()).some(
      (text) => text.includes("影響候補"),
    )
  )
    throw new Error("Upstream dependencies were labelled as downstream impact");
  await mark("upstream");
  await page.getByLabel("表示するGraph分析").selectOption("impact");
  const productNode = page.locator(".react-flow__node.entity-Product").first();
  await productNode.click();
  await expect(
    page.locator(".react-flow__edge.path-highlight").first(),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "選択ノードと根拠経路" }),
  ).toContainText("製品");
  await expect
    .poll(async () =>
      page
        .locator(".react-flow__edge.path-highlight .react-flow__edge-path")
        .first()
        .evaluate((element) => globalThis.getComputedStyle(element).stroke),
    )
    .toBe("rgb(240, 189, 102)");
  await page
    .locator(".graph-workspace")
    .screenshot({ path: `${output}/graph-selection.png` });
  await page.getByRole("button", { name: "Graphを拡大", exact: true }).click();
  await page
    .getByRole("button", { name: "全ノードを表示", exact: true })
    .click();
  await step(/対応案を比べる/);
  await expect(page.locator(".react-flow")).toBeVisible();
  const comparison = page.locator(".registered-comparison");
  await comparison
    .getByRole("button", {
      name: "比較に使う正式入力の候補を取得",
      exact: true,
    })
    .click();
  await expect(comparison.getByText("正式入力を確認中…")).toHaveCount(0);
  await comparison
    .getByLabel("共通比較期間の開始", { exact: true })
    .fill(start);
  await comparison.getByLabel("共通比較期間の終了", { exact: true }).fill(end);
  async function compare() {
    const waiting = page.waitForResponse((r) =>
      r.url().endsWith("/api/decisions/compare"),
    );
    await comparison
      .getByRole("button", { name: "選択した正式入力で比較する", exact: true })
      .click();
    const response = await waiting,
      body = await response.json();
    if (response.status() !== 200 || body.data.source !== "REGISTERED_INPUT")
      throw new Error("Comparison failed");
    return body;
  }
  const unknown = await compare();
  if (
    unknown.data.decision_package.comparison.options.some(
      (row) => row.total_cost !== null,
    )
  )
    throw new Error("Unselected costs inferred");
  await mark("comparison-unknown");
  await step(/根拠を確かめる/);
  await expect(page.locator(".react-flow")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "対応案比較の根拠", exact: true }),
  ).toBeVisible();
  const documents = await agent(
    page.getByRole("button", { name: "選択設備の関連文書を検索", exact: true }),
  );
  if (
    documents.body.data.search_source !== "QDRANT" ||
    documents.body.data.demo_only ||
    !documents.body.evidence.citations.length
  )
    throw new Error("Real citation missing");
  await expect(
    page.getByRole("heading", {
      name: "設備状態と保全調査の参考資料（デモ）",
      exact: true,
    }),
  ).toBeVisible();
  await mark("evidence", {
    source: "QDRANT",
    citations: documents.body.evidence.citations.length,
  });
  await step(/入力を登録・訂正/);
  const economics = page.locator(".economic-panel:not(.registered-comparison)");
  if (!(await economics.evaluate((element) => element.open)))
    await economics.locator("summary").first().click();
  await economics
    .getByRole("button", { name: "選択設備の経済入力を登録", exact: true })
    .click();
  const editor = economics.getByRole("region", {
    name: "経済入力の登録・訂正",
  });
  await editor.getByLabel("入力コード", { exact: true }).fill(code);
  await editor.getByLabel("比較開始", { exact: true }).fill(start);
  await editor.getByLabel("比較終了", { exact: true }).fill(end);
  await editor.getByLabel("稼働時間", { exact: true }).fill("16");
  for (const [name, amount] of [
    ["修理", "300000"],
    ["交換", "3000000"],
    ["継続", "16000"],
  ]) {
    const option = editor.getByRole("group", { name, exact: true });
    const item = option.getByRole("group", { name: "費用項目 1", exact: true });
    await item.getByLabel("項目キー", { exact: true }).fill("direct");
    await item
      .getByRole("combobox", { name: /^費用種別/ })
      .selectOption("DIRECT");
    await item.getByLabel("直接費（JPY）", { exact: true }).fill(amount);
    await item
      .getByLabel("出典", { exact: true })
      .fill("UIシナリオ用見積。実工場の費用ではない。");
    await item.getByLabel("他の項目と重複しないことを確認した").check();
    await option.getByLabel("この期間に必要な費用項目を網羅した").check();
  }
  const preparing = page.waitForResponse((r) =>
    r.url().endsWith("/api/economic-inputs/prepare"),
  );
  await editor
    .getByRole("button", { name: "経済入力の変更準備を作成", exact: true })
    .click();
  const prepared = await (await preparing).json();
  if (prepared.status !== "ok") throw new Error("Prepare failed");
  const id = prepared.data.update_request_id;
  const action = page.locator(".action-panel");
  await action
    .getByRole("button", { name: "直近の変更要求を開く", exact: true })
    .click();
  await expect(action.getByText(/状態：WAITING_APPROVAL/)).toBeVisible();
  await expect(
    page.getByText("更新操作後の関係は未確認です。関係を再取得してください。", {
      exact: true,
    }),
  ).toHaveCount(0);
  await mark("prepared", { update_request_id: id });
  const approvalPage = await browser.newPage();
  await approvalPage.goto(base);
  await login(approver, approvalPage);
  await approvalPage
    .getByRole("navigation", { name: "調査に続く操作" })
    .getByRole("button", { name: /変更・承認・実行/ })
    .click();
  const approvalAction = approvalPage.locator(".action-panel");
  await approvalAction.getByLabel("変更要求ID", { exact: true }).fill(id);
  await approvalAction
    .getByRole("button", { name: "保存状態を再取得", exact: true })
    .click();
  await approvalAction
    .getByLabel("保存Snapshotと操作内容を確認しました")
    .check();
  await approvalAction
    .getByRole("button", { name: "Snapshotを承認", exact: true })
    .click();
  await expect(approvalAction.getByText(/状態：APPROVED/)).toBeVisible();
  await mark("approved-in-separate-session");
  await approvalPage.close();
  await action
    .getByRole("button", { name: "保存状態を再取得", exact: true })
    .click();
  await expect(action.getByText(/状態：APPROVED/)).toBeVisible();
  await action.getByLabel("保存Snapshotと操作内容を確認しました").check();
  await action
    .getByRole("button", { name: "承認済み変更を実行", exact: true })
    .click();
  await expect(action.getByText(/状態：COMPLETED/)).toBeVisible();
  await expect(
    action.getByRole("heading", {
      name: "実行応答・実行後の現在値",
      exact: true,
    }),
  ).toBeVisible();
  await mark("executed");
  const graphWarning = page.getByText(
    "更新操作後の関係は未確認です。関係を再取得してください。",
    { exact: true },
  );
  await expect(graphWarning).toBeVisible();
  await agent(
    page.getByRole("button", { name: "名称・属性を取得", exact: true }),
  );
  await expect(graphWarning).toBeVisible();
  await agent(
    page.getByRole("button", { name: "関係・影響を再取得", exact: true }),
  );
  await expect(graphWarning).toHaveCount(0);
  await expect(page.locator(".react-flow")).toBeVisible();
  await mark("graph-refreshed-after-execution");
  await step(/対応案を比べる/);
  await comparison
    .getByRole("button", {
      name: "比較に使う正式入力の候補を取得",
      exact: true,
    })
    .click();
  await comparison.getByLabel(new RegExp(code)).check();
  await comparison
    .getByRole("button", { name: `入力・出典を確認：${code}`, exact: true })
    .click();
  await expect(
    comparison.getByLabel("共通比較期間の開始", { exact: true }),
  ).toHaveValue("2030-01-01T00:00:00.000000Z");
  const updated = await compare();
  const repair = updated.data.decision_package.comparison.options.find(
    (row) => row.option === "REPAIR",
  );
  if (repair.total_cost !== "300000")
    throw new Error("Executed input was not reflected in comparison");
  await expect(
    comparison.getByText("300000 JPY", { exact: true }).first(),
  ).toBeVisible();
  await mark("recompared", {
    repair_total: repair.total_cost,
    input_code: code,
  });
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    if (
      await page.evaluate(
        () =>
          globalThis.document.documentElement.scrollWidth >
          globalThis.document.documentElement.clientWidth,
      )
    )
      throw new Error(`Overflow at ${width}`);
  }
  if (errors.length) throw new Error("Browser runtime errors");
  await writeFile(
    `${output}/report.json`,
    JSON.stringify(
      {
        result: "PASS",
        scope: "PERSISTENT_UI_END_TO_END_REAL_SERVICES",
        revision: process.env.LINESCOPE_BROWSER_REVISION ?? "UNRECORDED",
        stages,
        browser_errors: errors,
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ result: "PASS", stages: stages.length }));
} catch (error) {
  await writeFile(
    `${output}/report.json`,
    JSON.stringify(
      {
        result: "FAIL",
        phase,
        stages,
        error:
          error instanceof Error ? error.message.split("\n")[0] : "UNKNOWN",
      },
      null,
      2,
    ),
  );
  console.error(
    `Workflow failed after ${phase}: ${error instanceof Error ? error.message : "UNKNOWN"}`,
  );
  process.exitCode = 1;
} finally {
  await browser.close();
}
