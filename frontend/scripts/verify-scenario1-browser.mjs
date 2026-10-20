// Maintained read-only smoke: actual scenario1 API, no mocked business responses.
import { URL } from "node:url";
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.LINESCOPE_BROWSER_URL;
const token = process.env.LINESCOPE_BROWSER_TOKEN;
if (!base || !token) throw new Error("Browser URL and private token required");
const output = process.env.LINESCOPE_BROWSER_OUTPUT ?? "/out";
await mkdir(output, { recursive: true });
const report = {
  scenario: "scenario1",
  result: "RUNNING",
  real_api: true,
  blocked: [],
  page_errors: [],
  timings_ms: {},
};
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
page.setDefaultTimeout(30000);
page.on("pageerror", (error) => report.page_errors.push(error.message));
await page.route("**/api/**", async (route) => {
  const req = route.request(),
    path = new URL(req.url()).pathname;
  if (req.method() === "GET") return route.continue();
  const readPaths = [
    "/api/session/login",
    "/api/session/logout",
    "/api/incidents/investigate",
    "/api/decisions/compare",
    "/api/economic-inputs/search",
    "/api/capacity-inputs/search",
    "/api/safety-inputs/search",
    "/api/maintenance-inputs/search",
  ];
  if (
    req.method() === "POST" &&
    (readPaths.includes(path) ||
      (path === "/api/agent" &&
        req.postDataJSON()?.message?.startsWith("関係分析 ")))
  )
    return route.continue();
  report.blocked.push({ method: req.method(), path });
  return route.abort();
});
async function search(code) {
  await page.getByLabel("設備名・コード", { exact: true }).fill(code);
  const started = Date.now();
  await page.getByRole("button", { name: "検索", exact: true }).click();
  const candidate = page
    .locator(".equipment-search-panel > .equipment-result")
    .filter({ hasText: code });
  await expect(candidate).toHaveCount(1);
  report.timings_ms[`${code}-search`] = Date.now() - started;
  await candidate.click();
}
try {
  await page.goto(base);
  await expect(page.locator(".equipment-search-panel")).toHaveCount(0);
  await page.getByLabel("Bearer token").fill(token);
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await expect(
    page.getByRole("tab", { name: "接続及び影響範囲", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".equipment-search-panel > .equipment-result"),
  ).toHaveCount(0);
  await search("M-204");
  const loss = page.getByRole("region", { name: "推定損害額", exact: true });
  const alternative = page.getByRole("region", {
    name: "代替の提案",
    exact: true,
  });
  await expect(loss.locator(".loss-amount")).toContainText("200,000");
  await expect(alternative).toContainText("M-208");
  await expect(alternative).toContainText("能力面で吸収できる見込み");
  await expect(page.locator(".capacity-assessment")).toContainText("60");
  await expect(page.locator(".capacity-assessment")).toContainText("80");
  await expect(alternative).toContainText("評価していません");
  await expect(page.locator(".relationship-panel")).not.toContainText(
    "読み込み中",
  );
  await expect(page.locator(".relationship-panel")).not.toContainText(
    /名称を確認|名前を確認|名称取得に失敗/,
  );
  for (const code of ["M-204", "P-100", "P-200"])
    await expect(
      page
        .locator(".relationship-panel .react-flow__node")
        .filter({ hasText: code })
        .first(),
    ).toBeVisible();
  await page
    .getByRole("button", { name: "この設備が依存する先", exact: true })
    .click();
  await expect(
    page
      .locator(".relationship-panel .react-flow__node")
      .filter({ hasText: "R-02" }),
  ).toBeVisible();
  await page.screenshot({
    path: `${output}/scenario1-investigation.png`,
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "M-204への対応案を比べる", exact: true })
    .click();
  const comparison = page.locator(".registered-comparison");
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/decisions/compare") && r.request().method() === "POST",
  );
  await comparison
    .getByRole("button", { name: "選択した正式入力で比較する", exact: true })
    .click();
  const compared = await response;
  expect(compared.ok()).toBe(true);
  await expect(
    comparison.getByLabel("選択した条件の比較結果", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("tab", { name: "接続及び影響範囲", exact: true })
    .click();
  await search("M-208");
  await expect(loss).toContainText("稼働中のため、停止損害の算定対象外");
  const inputLink = page.getByRole("button", {
    name: "M-208の比較用入力を確認する",
    exact: true,
  });
  await expect(inputLink).toBeVisible();
  await expect(
    page.getByText(/比較画面で対応計画などの登録状況/),
  ).toBeVisible();
  await inputLink.click();
  await expect(
    comparison.getByRole("button", {
      name: "選択した正式入力で比較する",
      exact: true,
    }),
  ).toBeDisabled();
  await comparison
    .getByRole("button", {
      name: "比較に使う正式入力の候補を取得",
      exact: true,
    })
    .click();
  await expect(comparison).toContainText("検索が完了しました");
  await expect(
    comparison.locator('input[type="checkbox"]').first(),
  ).toBeDisabled();
  await expect(comparison).toContainText(
    "この設備自身の能力データは、この比較の代替用には選択できません",
  );
  await page.screenshot({
    path: `${output}/scenario1-input-guidance.png`,
    fullPage: true,
  });
  expect(report.blocked).toHaveLength(0);
  expect(report.page_errors).toHaveLength(0);
  report.result = "PASS";
  console.log(JSON.stringify(report));
} catch (error) {
  report.result = "FAIL";
  report.error = error.message;
  await page.screenshot({
    path: `${output}/scenario1-failure.png`,
    fullPage: true,
  });
  throw error;
} finally {
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
