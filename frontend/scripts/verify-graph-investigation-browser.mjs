/* global document, innerWidth */
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.LINESCOPE_BROWSER_URL;
const token = process.env.LINESCOPE_BROWSER_TOKEN;
const output = process.env.LINESCOPE_BROWSER_OUTPUT;
if (!base || !token || !output)
  throw new Error("Explicit browser configuration required");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = { revision: process.env.LINESCOPE_BROWSER_REVISION, stages: [] };
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1100 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  async function agent(button) {
    await expect(button).toBeEnabled({ timeout: 150000 });
    const waiting = page.waitForResponse(
      (r) => r.url().endsWith("/api/agent") && r.request().method() === "POST",
      { timeout: 150000 },
    );
    const start = Date.now();
    await button.click();
    const response = await waiting;
    const body = await response.json();
    if (response.status() !== 200 || body.errors.length)
      throw new Error(
        `Agent failed: ${response.status()} ${JSON.stringify(body.errors)}`,
      );
    return {
      body,
      request: response.request().postDataJSON(),
      seconds: (Date.now() - start) / 1000,
    };
  }
  function mark(stage, details) {
    report.stages.push({ stage, ...details });
    console.log(JSON.stringify(report.stages.at(-1)));
  }
  await page.goto(base);
  await page.getByLabel("Bearer token").fill(token);
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await agent(
    page.getByRole("button", {
      name: "登録設備を表示して調査を始める",
      exact: true,
    }),
  );
  const initial = await agent(
    page
      .getByRole("region", { name: "設備検索の候補" })
      .getByRole("button", { name: /M-204/ }),
  );
  const products =
    initial.body.data.decision_package.impact.reached_nodes.filter(
      (n) => n.entity_type === "Product",
    );
  if (products.length < 2)
    throw new Error("Demo must expose two product subjects");
  async function selectNode(name) {
    const details = page.locator(".graph-node-access");
    if ((await details.getAttribute("open")) === null)
      await details.locator("summary").click();
    await page
      .getByLabel("Graphノードの一覧")
      .getByRole("button", { name, exact: true })
      .click();
  }
  for (const item of products.slice(0, 2)) {
    await selectNode(`製品 · ${item.entity_id.slice(0, 8)}`);
    await page
      .getByRole("button", { name: "選択ノードを追加：重要対象", exact: true })
      .click();
  }
  await page
    .getByLabel("Graphノードの一覧")
    .getByRole("button", { name: /M-204|加工機/ })
    .first()
    .click();
  await page
    .getByRole("button", { name: "選択ノードを追加：除外対象", exact: true })
    .click();
  let lastGraph;
  for (const [button, tool, field] of [
    ["共通依存を調べる", "find_common_dependencies", "common_candidates"],
    ["除外後の代替経路を調べる", "find_alternative_paths", "target_results"],
    [
      "単一障害点候補を調べる",
      "find_single_point_failure_candidates",
      "findings",
    ],
  ]) {
    const response = await agent(
      page.getByRole("button", { name: button, exact: true }),
    );
    const command = JSON.parse(
      response.request.message.slice("関係分析 ".length),
    );
    expect(command.tool).toBe(tool);
    expect(
      command.arguments.targets ?? command.arguments.important_targets,
    ).toEqual(products.slice(0, 2));
    if (tool === "find_single_point_failure_candidates")
      expect(command.arguments).not.toHaveProperty("candidate_nodes");
    const row = response.body.data.tool_results.find(
      (row) => row.tool === tool,
    );
    lastGraph = row.data;
    expect(row.data.graph_sync_state).toBe("CURRENT");
    expect(Array.isArray(row.data[field])).toBe(true);
    await expect(page.locator(".react-flow")).toBeVisible();
    await expect(
      page.getByRole("region", { name: "対象別の構造判定" }),
    ).toBeVisible();
    mark(tool, {
      seconds: response.seconds,
      complete: row.data.complete,
      determination: row.data.determination,
      subjects: row.data[field].length,
    });
  }
  await selectNode(`製品 · ${products[0].entity_id.slice(0, 8)}`);
  const attributes = await agent(
    page.getByRole("button", { name: "名称・属性を取得", exact: true }),
  );
  expect(attributes.body.data.tool_results[0].tool).toBe("get_product");
  expect(attributes.body.data.tool_results[0].data.product_id).toBe(
    products[0].entity_id,
  );
  mark("node-attributes", { seconds: attributes.seconds });
  const alternative = lastGraph.representative_paths
    .flatMap((path) => path.nodes)
    .find(
      (item) =>
        item.entity_type === "Equipment" &&
        item.entity_id !==
          initial.body.data.decision_package.equipment.equipment_id,
    );
  if (!alternative)
    throw new Error("Expected an alternate equipment in the returned Graph");
  await selectNode(`設備 · ${alternative.entity_id.slice(0, 8)}`);
  await expect(
    page.getByRole("button", {
      name: "この設備を比較・入力の対象にする",
      exact: true,
    }),
  ).toBeDisabled();
  const equipmentDetails = await agent(
    page.getByRole("button", { name: "名称・属性を取得", exact: true }),
  );
  const actualEquipment = equipmentDetails.body.data.tool_results[0].data;
  expect(actualEquipment.equipment_id).toBe(alternative.entity_id);
  await page
    .getByRole("button", {
      name: "この設備を比較・入力の対象にする",
      exact: true,
    })
    .click();
  const comparison = page.locator(".registered-comparison");
  await expect(comparison).toContainText(actualEquipment.equipment_code);
  await expect(page.locator(".react-flow")).toBeVisible();
  await expect(page.getByText(/Graph調査の起点：/)).toContainText("M-204");
  const fetching = page.waitForResponse((r) =>
    r.url().endsWith("/api/economic-inputs/search"),
  );
  await comparison
    .getByRole("button", {
      name: "比較に使う正式入力の候補を取得",
      exact: true,
    })
    .click();
  const candidateResponse = await fetching;
  expect(candidateResponse.request().postDataJSON().filter.equipment_id).toBe(
    alternative.entity_id,
  );
  await comparison
    .getByLabel("共通比較期間の開始", { exact: true })
    .fill("2030-01-01T00:00:00Z");
  await comparison
    .getByLabel("共通比較期間の終了", { exact: true })
    .fill("2030-01-02T00:00:00Z");
  const comparing = page.waitForResponse((r) =>
    r.url().endsWith("/api/decisions/compare"),
  );
  await comparison
    .getByRole("button", { name: "選択した正式入力で比較する", exact: true })
    .click();
  const compareResponse = await comparing;
  expect(compareResponse.status()).toBe(200);
  expect(compareResponse.request().postDataJSON().equipment_id).toBe(
    alternative.entity_id,
  );
  const comparisonBody = await compareResponse.json();
  expect(comparisonBody.data.decision_package.equipment.equipment_id).toBe(
    alternative.entity_id,
  );
  await page
    .getByRole("button", { name: "比較の根拠を確かめる", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "対応案比較の根拠", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".react-flow")).toBeVisible();
  await page
    .getByRole("navigation", { name: "調査に続く操作" })
    .getByRole("button", { name: "入力を登録・訂正", exact: true })
    .click();
  const economics = page.getByRole("region", {
    name: "正式な経済・損失入力",
    exact: true,
  });
  await economics
    .getByRole("button", { name: "選択設備の経済入力を登録", exact: true })
    .click();
  await expect(
    economics.getByRole("region", { name: "経済入力の登録・訂正" }),
  ).toContainText(alternative.entity_id);
  mark("graph-equipment-to-comparison-and-input", {
    equipment_code: actualEquipment.equipment_code,
    graph_origin: "M-204",
    checked_selection: true,
  });
  await selectNode("Demo machine M-204");
  await page
    .getByRole("button", {
      name: "この設備を比較・入力の対象にする",
      exact: true,
    })
    .click();
  await expect(comparison).toContainText("M-204");
  await expect(
    comparison.getByLabel("共通比較期間の開始", { exact: true }),
  ).toHaveValue("");
  await expect(
    page.getByRole("region", { name: "重要対象", exact: true }),
  ).toContainText("重要対象（2件）");
  mark("decision-target-switch-clears-old-selection", {
    graph_preserved: true,
  });
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1100 });
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      )
      .toBe(true);
  }
  await page
    .getByRole("button", { name: "全ノードを表示", exact: true })
    .click();
  await expect(page.getByLabel("関係や影響について質問する")).not.toHaveValue(
    /^関係分析 /,
  );
  expect(errors).toEqual([]);
  await page.screenshot({
    path: `${output}/graph-investigation.png`,
    fullPage: true,
  });
  report.status = "PASS";
} catch (error) {
  report.status = "FAIL";
  report.error = error.message;
  throw error;
} finally {
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
