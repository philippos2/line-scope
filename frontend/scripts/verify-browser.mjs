import { chromium, expect } from "@playwright/test";
const base = process.env.LINESCOPE_BROWSER_URL;
const token = process.env.LINESCOPE_BROWSER_TOKEN;
if (!base || !token)
  throw new Error("Explicit browser fixture configuration required");
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  await page.goto(base);
  await page.getByLabel("Bearer token").fill(token);
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "接続解除", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "比較デモ", exact: true }).click();
  await page
    .getByRole("button", { name: "問い合わせを送信", exact: true })
    .click();
  await expect(
    page.getByText("PARTIAL / 部分結果", { exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("img")).toBeVisible();
  await expect(
    page.getByText(
      "MOCK_FIXTUREを含む比較デモ。費用・能力・安全条件は仮置きです。",
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "M-204", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Object詳細", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "対応案の比較", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "対応案を比較する", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("¥1,900,000", { exact: true })).toBeVisible();
  await expect(page.getByText("候補から除外", { exact: true })).toBeVisible();
  await page.screenshot({ path: "/tmp/frontend-1440.png", fullPage: true });
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "サーバが返したEvidence", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator("main").getByText(/graph_generation/),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "/tmp/frontend-390.png", fullPage: true });
  if (
    (await page.evaluate(() => localStorage.length + sessionStorage.length)) !==
    0
  )
    throw new Error("Unexpected persisted data");
  await page.getByRole("button", { name: "接続解除", exact: true }).click();
  await expect(page.getByLabel("Bearer token")).toHaveValue("");
  console.log(
    JSON.stringify({
      result: "PASS",
      scope:
        "Real browser + HTTP + PostgreSQL + Neo4j; decision inputs mocked; no LLM",
      screenshots: ["1440", "390"],
    }),
  );
} catch {
  console.error(
    JSON.stringify({ result: "FAIL", code: "FRONTEND_PROBE_FAILED" }),
  );
  process.exitCode = 1;
} finally {
  await browser.close();
}
