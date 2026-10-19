// Real HTTP main scenario plus explicitly controlled failures. Never modifies registered data.
import { URL } from "node:url";
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.LINESCOPE_BROWSER_URL;
const token = process.env.LINESCOPE_BROWSER_TOKEN;
if (!base || !token)
  throw new Error("Browser URL and private token are required");
const output = process.env.LINESCOPE_BROWSER_OUTPUT ?? "/out";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = {
  checks: [],
  timings_ms: {},
  controlled: [
    "capacity-0",
    "capacity-2",
    "search",
    "downstream",
    "alternatives",
    "comparison",
    "loss",
    "names",
  ],
};
let page;
let context;
async function open(width = 1600) {
  context = await browser.newContext({ viewport: { width, height: 1100 } });
  page = await context.newPage();
  await page.goto(base);
  await page.getByLabel("Bearer token").fill(token);
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "設備を探す", exact: true }),
  ).toBeVisible();
}
async function search(value = "第1") {
  await page.getByLabel("設備名・コード", { exact: true }).fill(value);
  const start = Date.now();
  await page.getByRole("button", { name: "検索", exact: true }).click();
  await expect(
    page.locator(".equipment-search-panel > .equipment-result").first(),
  ).toBeVisible();
  report.timings_ms.search ??= Date.now() - start;
}
async function choose() {
  await page
    .locator(".equipment-search-panel > .equipment-result")
    .first()
    .click();
}
async function money() {
  await expect(page.locator(".loss-amount")).toContainText("200,000", {
    timeout: 30000,
  });
}
async function capacity() {
  await expect(page.locator(".capacity-assessment")).toContainText("80", {
    timeout: 30000,
  });
}
async function noOverflow() {
  expect(
    await page.evaluate(
      () =>
        globalThis.document.documentElement.scrollWidth <=
        globalThis.innerWidth + 1,
    ),
  ).toBe(true);
}
async function visibleWords() {
  const text = await page.locator("body").innerText();
  expect(text).not.toMatch(
    /Graph|Envelope|\bTool\b|state_code|SPOF|CURRENT|INCOMPLETE_SEARCH|経済入力|被害額|損失根拠|正本|名称を確認|名前を確認|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/,
  );
}
async function check(name, run) {
  await open(name.includes("390") ? 390 : name.includes("768") ? 768 : 1600);
  try {
    await run();
    await noOverflow();
    await visibleWords();
    await page.screenshot({ path: `${output}/${name}.png`, fullPage: true });
    report.checks.push({ name, result: "PASS" });
    console.log("PASS", name);
  } catch (error) {
    report.checks.push({ name, result: "FAIL" });
    await page.screenshot({
      path: `${output}/${name}-failure.png`,
      fullPage: true,
    });
    throw error;
  } finally {
    await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
    await context.close();
  }
}
async function control(failure) {
  let originalCapacityId;
  const secondCapacityId = "00000000-0000-4000-8000-000000000002";
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    let message;
    try {
      const body = req.postDataJSON();
      if (body?.message?.startsWith("関係分析 "))
        message = JSON.parse(body.message.slice(5));
    } catch {
      /* GET requests have no body. */
    }
    const shouldFail =
      (failure === "search" && message?.tool === "search_equipment") ||
      (failure === "downstream" &&
        message?.tool === "trace_downstream_impact") ||
      (failure === "alternatives" &&
        message?.tool === "find_alternative_paths") ||
      (failure === "comparison" && path === "/api/decisions/compare") ||
      (failure === "loss" && path === "/api/incidents/investigate");
    if (shouldFail)
      return route.fulfill({
        status: 503,
        json: {
          request_id: "controlled-failure",
          context_id: null,
          status: "error",
          answer: null,
          data: {},
          evidence: {},
          warnings: [],
          errors: [{ code: "DEPENDENCY_UNAVAILABLE" }],
        },
      });
    if (
      failure.startsWith("capacity-") &&
      path === "/api/capacity-inputs/search"
    ) {
      const response = await route.fetch(),
        data = await response.json();
      if (failure === "capacity-0") data.data.items = [];
      else {
        originalCapacityId = data.data.items[0].capacity_input_id;
        data.data.items.push({
          ...data.data.items[0],
          capacity_input_id: secondCapacityId,
          input_code: "CONTROLLED-SECOND-CAPACITY",
        });
      }
      return route.fulfill({ response, json: data });
    }
    if (
      failure === "capacity-2" &&
      path === `/api/capacity-inputs/${secondCapacityId}`
    ) {
      const response = await route.fetch({
        url: req.url().replace(secondCapacityId, originalCapacityId),
      });
      const data = await response.json();
      data.data.input = {
        ...data.data.input,
        capacity_input_id: secondCapacityId,
        input_code: "CONTROLLED-SECOND-CAPACITY",
      };
      return route.fulfill({ response, json: data });
    }
    return route.continue();
  });
}
try {
  await check("real-main-1600", async () => {
    await expect(page.locator("body")).not.toContainText("M-204");
    await expect(page.locator("body")).not.toContainText("M-208");
    await page.screenshot({ path: `${output}/initial.png`, fullPage: true });
    await search();
    const start = Date.now();
    await choose();
    await money();
    await capacity();
    report.timings_ms.selected_to_results = Date.now() - start;
    const proposal = page.locator(".capacity-assessment");
    await expect(proposal).toContainText(
      "品質・残るリスクは、この版では評価対象外です。",
    );
    await expect(proposal).toContainText(
      "今回の評価では安全条件の入力を選択していません。",
    );
    expect(await proposal.locator("dt").allTextContents()).not.toContain(
      "品質",
    );
    expect(await proposal.locator("dt").allTextContents()).not.toContain(
      "残るリスク",
    );
    await proposal.getByText("判定の出典と条件", { exact: true }).click();
    await expect(proposal).toContainText(
      "この版では、代替運転の費用を比較結果に含めていません。",
    );
    await expect(proposal).not.toContainText("確認条件を確認");
    await page.getByText("能力データを確認・選び直す", { exact: true }).click();
    const choice = page
      .locator(".input-choice")
      .filter({ hasText: "能力データを確認・選び直す" });
    await expect(choice).toContainText(
      "2026/10/18 09:00〜2026/10/19 09:00（日本時間）",
    );
    await expect(choice.locator("select")).toContainText("P-100");
    expect(await choice.locator("select").innerText()).not.toMatch(
      /S1-CAPACITY|T00:00:00/,
    );
    await page.getByText("能力データを確認・選び直す", { exact: true }).click();
    await proposal.getByText("判定の出典と条件", { exact: true }).click();
    const economicChoice = page
      .locator(".input-choice")
      .filter({ hasText: "損害額の算定データを確認・選び直す" });
    await economicChoice.locator("summary").first().click();
    await expect(economicChoice.locator("dd ul li")).toHaveText([
      "架空工場シナリオ1の登録条件（デモ仮定）",
    ]);
    await economicChoice.locator("summary").first().click();

    await expect(page.locator(".available-proposal")).toContainText(
      "吸収できる見込み",
    );
    await expect(page.locator(".available-proposal")).toContainText("P-200");
    await expect(page.locator(".alternative-proposal")).toContainText(
      "利用可能",
    );
    await expect(page.locator(".discovered-candidates")).toContainText(
      "稼働中",
    );
    await expect(
      page.locator(".react-flow__node").filter({ hasText: "M-204" }),
    ).toBeVisible();
    await expect(
      page.locator(".react-flow__node").filter({ hasText: "M-208" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "この設備が依存する先", exact: true })
      .click();
    await expect(
      page.locator(".react-flow__node").filter({ hasText: "共通電源 · R-02" }),
    ).toBeVisible();
    await expect(page.locator(".react-flow__node")).toHaveCount(2);
    await expect(page.locator(".react-flow__node")).toHaveText([
      /第1加工機 · M-204/,
      /共通電源 · R-02/,
    ]);
    await page.screenshot({ path: `${output}/upstream.png`, fullPage: true });
    await page
      .getByRole("button", { name: "止まると影響を受ける先", exact: true })
      .click();
    const expected = [
      "第1加工機 · M-204",
      "第2加工機 · M-208",
      "第1加工工程 · P-10",
      "仕上工程 · P-20",
      "OP-30",
      "OP-40",
      "製品 · P-100",
      "製品 · P-200",
    ];
    await expect(page.locator(".react-flow__node")).toHaveCount(
      expected.length,
    );
    for (const text of expected)
      await expect(
        page.locator(".react-flow__node").filter({ hasText: text }),
      ).toBeVisible();
    await page.locator(".graph-node-access summary").click();
    const list = page.locator(".node-list button");
    await expect(list).toHaveCount(expected.length);
    for (const text of expected)
      await expect(list.filter({ hasText: text })).toHaveCount(1);
    await expect(page.locator(".relationship-panel")).not.toContainText(
      "読み込み中",
    );
    await page.locator(".graph-node-access summary").click();
  });
  await check("switch-delayed-390", async () => {
    await search();
    await choose();
    await capacity();
    await money();
    // Hold a genuine response and switch while it is outstanding; the old loss must not return.
    let release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    let captured;
    const started = new Promise((resolve) => {
      captured = resolve;
    });
    await page.route("**/api/incidents/investigate", async (route) => {
      const response = await route.fetch();
      captured();
      await gate;
      try {
        await route.fulfill({ response });
      } catch {
        /* Aborted by equipment switch. */
      }
    });
    await page.route("**/api/agent", async (route) => {
      const body = route.request().postDataJSON();
      if (body?.message?.includes('"get_process"')) {
        const response = await route.fetch();
        await gate;
        try {
          await route.fulfill({ response });
        } catch {
          /* Switched roots. */
        }
      } else await route.continue();
    });
    await page.getByRole("button", { name: "再調査", exact: true }).click();
    await started;
    await expect(
      page.locator(".discovered-candidates .equipment-result"),
    ).toBeVisible();
    await page.locator(".discovered-candidates .equipment-result").click();
    release();
    await expect(
      page.locator(".react-flow__node").filter({ hasText: "OP-50" }),
    ).toBeVisible();
    await expect(page.locator(".relationship-panel")).not.toContainText(
      "OP-30",
    );
    await expect(page.locator(".relationship-panel")).not.toContainText(
      "第1加工工程",
    );
    await expect(page.locator(".selected-equipment")).toContainText("M-208");
    await expect(page.locator(".loss-estimate")).toContainText("稼働中のため", {
      timeout: 15000,
    });
    await expect(page.locator(".loss-amount")).toHaveCount(0);
    await page.screenshot({
      path: `${output}/m208-running.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "接続解除", exact: true }).click();
    await page.getByLabel("Bearer token").fill(token);
    await page.getByRole("button", { name: "接続する", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "設備を探す", exact: true }),
    ).toBeVisible();
    await expect(page.locator(".selected-equipment")).toHaveCount(0);
    await expect(page.locator(".loss-amount")).toHaveCount(0);
  });
  await check("keyboard-768", async () => {
    await page.getByLabel("設備名・コード", { exact: true }).focus();
    await page.keyboard.type("M-204");
    await page.keyboard.press("Enter");
    const result = page
      .locator(".equipment-search-panel > .equipment-result")
      .first();
    await expect(result).toBeVisible();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    await expect(result).toBeFocused();
    await page.keyboard.press("Enter");
    await money();
    const summary = page.locator(".graph-node-access summary");
    await summary.focus();
    await page.keyboard.press("Enter");
    await page.keyboard.press("Tab");
    await expect(page.locator(".node-list button").first()).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator(".selected-node-panel")).toContainText("M-204");
  });
  await check("controlled-names", async () => {
    // Controlled source variation, retaining the real response shape and all persisted data.
    await page.route("**/api/economic-inputs/*", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      const response = await route.fetch();
      const data = await response.json();
      data.data.input.payload.incident_losses.forEach((row, index) => {
        row.source = `検証用出典${index + 1}`;
      });
      await route.fulfill({ response, json: data });
    });

    await page.route("**/api/agent", async (route) => {
      const body = route.request().postDataJSON();
      if (body?.message?.includes('"get_process"'))
        return route.fulfill({
          status: 503,
          json: {
            request_id: "name-failure",
            context_id: null,
            status: "error",
            answer: null,
            data: {},
            evidence: {},
            warnings: [],
            errors: [{ code: "DEPENDENCY_UNAVAILABLE" }],
          },
        });
      await route.continue();
    });
    await search();
    await choose();
    await money();
    await capacity();
    await expect(
      page.locator(".react-flow__node").filter({ hasText: "名称取得に失敗" }),
    ).toHaveCount(2);
    await page.locator(".graph-node-access summary").click();
    await expect(
      page.locator(".node-list button").filter({ hasText: "名称取得に失敗" }),
    ).toHaveCount(2);
    await page.unroute("**/api/agent");
    await page
      .locator(".relationship-panel .read-failure")
      .getByRole("button", { name: "再試行" })
      .click();
    await expect(
      page
        .locator(".react-flow__node")
        .filter({ hasText: "第1加工工程 · P-10" }),
    ).toBeVisible();
    await expect(page.locator(".relationship-panel")).not.toContainText(
      "名称取得に失敗",
    );
    await expect(page.locator(".relationship-panel")).not.toContainText(
      "読み込み中",
    );
    await expect(page.locator(".loss-amount")).toContainText("200,000");
    const sources = page
      .locator(".input-choice")
      .filter({ hasText: "損害額の算定データを確認・選び直す" });
    await sources.locator("summary").first().click();
    await expect(sources.locator("dd ul li")).toHaveText([
      "製品 · P-100：検証用出典1",
      "製品 · P-200：検証用出典2",
    ]);
  });
  for (const failure of [
    "capacity-0",
    "capacity-2",
    "search",
    "downstream",
    "alternatives",
    "comparison",
    "loss",
  ]) {
    await check(`controlled-${failure}`, async () => {
      await control(failure);
      if (failure === "search") {
        await page.getByLabel("設備名・コード", { exact: true }).fill("第1");
        await page.getByRole("button", { name: "検索", exact: true }).click();
      } else {
        await search();
        await choose();
      }
      if (failure.startsWith("capacity-")) {
        await money();
        await expect(page.locator(".alternative-proposal")).toContainText(
          failure === "capacity-0"
            ? "未登録のため"
            : "能力データを選んでください",
          { timeout: 30000 },
        );
        await expect(page.locator(".capacity-assessment")).toHaveCount(0);
        if (failure === "capacity-2") {
          await page
            .getByText("能力データを確認・選び直す", { exact: true })
            .click();
          await page
            .getByLabel("能力データ", { exact: true })
            .selectOption({ index: 1 });
          await capacity();
        }
      } else {
        const area =
          failure === "search"
            ? ".equipment-search-panel"
            : failure === "downstream"
              ? ".relationship-panel"
              : failure === "loss"
                ? ".loss-estimate"
                : ".alternative-proposal";
        await expect(page.locator(`${area} .read-failure`).first()).toBeVisible(
          { timeout: 30000 },
        );
        await expect(
          page
            .locator(`${area} .read-failure`)
            .first()
            .getByRole("button", { name: "再試行" }),
        ).toBeVisible();
        if (failure !== "search" && failure !== "loss") await money();
        if (failure === "loss") await capacity();
        await page.unroute("**/api/**");
        await page
          .locator(`${area} .read-failure`)
          .first()
          .getByRole("button", { name: "再試行" })
          .click();
        if (failure === "search")
          await expect(
            page.locator(".equipment-search-panel > .equipment-result").first(),
          ).toBeVisible();
        else {
          await money();
          await capacity();
        }
      }
    });
  }
} finally {
  await browser.close();
}
