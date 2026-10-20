// Maintained read-only smoke: actual scenario1 API, no mocked business responses.
import { URL } from "node:url";
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.LINESCOPE_BROWSER_URL;
const token = process.env.LINESCOPE_BROWSER_TOKEN;
if (!base || !token) throw new Error("Browser URL and private token required");
const verifyReadFailures = process.env.LINESCOPE_BROWSER_READ_FAILURES === "1";
const output = process.env.LINESCOPE_BROWSER_OUTPUT ?? "/out";
await mkdir(output, { recursive: true });
const report = {
  scenario: "scenario1",
  result: "RUNNING",
  real_api: true,
  controlled_read_failures: verifyReadFailures,
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
        (req.postDataJSON()?.message?.startsWith("関係分析 ") ||
          req.postDataJSON()?.message?.startsWith("文書検索："))))
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
  if (verifyReadFailures) {
    await page.route("**/api/session/login", (route) =>
      route.fulfill({
        status: 401,
        json: {
          request_id: "read-login-error",
          context_id: null,
          status: "error",
          answer: "",
          data: {},
          evidence: {},
          warnings: [],
          errors: [{ code: "AUTHENTICATION_REQUIRED" }],
        },
      }),
    );
    await page.getByRole("button", { name: "接続する", exact: true }).click();
    await expect(page.locator(".read-failure")).toBeVisible();
    expect(await page.locator(".read-failure").innerText()).not.toContain(
      "AUTHENTICATION_REQUIRED",
    );
    await page.unroute("**/api/session/login");
  }
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await expect(
    page.getByRole("tab", { name: "接続及び影響範囲", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".equipment-search-panel > .equipment-result"),
  ).toHaveCount(0);
  if (verifyReadFailures) {
    await page
      .getByRole("tab", { name: "入力を登録・訂正", exact: true })
      .click();
    for (const [kind, tab, title] of [
      ["economic", "費用・経済", "経済入力"],
      ["capacity", "生産能力", "能力入力"],
      ["safety", "安全条件", "安全入力"],
      ["maintenance", "対応計画・故障履歴", "対応計画・故障履歴"],
    ]) {
      await page.getByRole("button", { name: tab, exact: true }).click();
      const panel = page.locator(`.${kind}-panel`);
      let fail = true;
      const pattern = `**/api/${kind}-inputs/search`;
      await page.route(pattern, (route) => {
        if (!fail) return route.fallback();
        fail = false;
        return route.fulfill({
          status: 503,
          json: {
            request_id: "read-error",
            context_id: null,
            status: "error",
            answer: "",
            data: {},
            evidence: {},
            warnings: [],
            errors: [{ code: "DEPENDENCY_UNAVAILABLE" }],
          },
        });
      });
      await panel
        .getByRole("button", { name: `登録済み${title}を検索`, exact: true })
        .click();
      await expect(panel.locator(".read-failure")).toBeVisible();
      expect(await panel.locator(".read-failure").innerText()).not.toContain(
        "DEPENDENCY_UNAVAILABLE",
      );
      await panel
        .getByRole("button", { name: `${title}の取得を再試行`, exact: true })
        .click();
      await expect(panel.locator(".read-failure")).toHaveCount(0);
      await expect(
        panel.getByRole("button", {
          name: `登録済み${title}を検索`,
          exact: true,
        }),
      ).toBeEnabled();
      await page.unroute(pattern);
    }
    await page
      .getByRole("tab", { name: "接続及び影響範囲", exact: true })
      .click();
  }
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
  await expect(comparison).toContainText(
    "金額が設定されていない項目があります",
  );
  await expect(comparison).toContainText(
    "この案の費用項目を含む算定データが選択されていません",
  );
  await expect(comparison).not.toContainText(
    "登録費用と対応計画の選択内容を確認してください",
  );
  await page.getByRole("tab", { name: "出典と経路", exact: true }).click();
  await page.getByRole("button", { name: "関連文書", exact: true }).click();
  await page
    .getByRole("button", { name: "選択設備の関連文書を検索", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "文書検索の取得状態", exact: true }),
  ).toContainText("M-204");
  await expect(
    page.getByRole("region", { name: "文書検索の取得状態", exact: true }),
  ).toContainText("日本時間");
  await page.getByRole("button", { name: "根拠を見る", exact: true }).click();
  const documentDrawer = page.getByRole("dialog", {
    name: "関連文書の参照",
    exact: true,
  });
  await expect(
    documentDrawer.getByRole("region", {
      name: "文書検索の取得状態",
      exact: true,
    }),
  ).toContainText("M-204");
  await expect(documentDrawer).not.toContainText("取得済み（時刻情報なし）");
  await documentDrawer
    .getByRole("button", { name: "参照を閉じる", exact: true })
    .click();
  if (verifyReadFailures) {
    let fail = true;
    await page.route("**/api/agent", (route) => {
      if (
        !fail ||
        !route.request().postDataJSON()?.message?.startsWith("文書検索：")
      )
        return route.fallback();
      fail = false;
      return route.fulfill({
        status: 503,
        json: {
          request_id: "document-read-error",
          context_id: null,
          status: "error",
          answer: "",
          data: {},
          evidence: {},
          warnings: [],
          errors: [{ code: "DEPENDENCY_UNAVAILABLE" }],
        },
      });
    });
    await page
      .getByRole("button", { name: "選択設備の関連文書を検索", exact: true })
      .click();
    await expect(
      page.getByText(
        "前回取得した検索結果です。今回の再検索は完了していません。",
        { exact: true },
      ),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "文書検索を再試行", exact: true })
      .click();
    await expect(
      page.getByText(
        "前回取得した検索結果です。今回の再検索は完了していません。",
        { exact: true },
      ),
    ).toHaveCount(0);
    await page.unroute("**/api/agent");
  }
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
