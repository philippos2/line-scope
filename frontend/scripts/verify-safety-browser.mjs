import { chromium, expect } from "@playwright/test";
import { verifySafety } from "./verify-safety.mjs";
const base = process.env.LINESCOPE_BROWSER_URL;
const token = process.env.LINESCOPE_BROWSER_TOKEN;
const approver = process.env.LINESCOPE_BROWSER_APPROVER_TOKEN;
if (!base || !token || !approver)
  throw new Error("Explicit browser fixture configuration required");
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.setDefaultTimeout(10000);
  await page.goto(base);
  await page.getByLabel("Bearer token").fill(token);
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "接続解除", exact: true }),
  ).toBeVisible();
  await verifySafety(page, token, approver);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    if (
      await page.evaluate(
        () =>
          globalThis.document.documentElement.scrollWidth >
          globalThis.document.documentElement.clientWidth,
      )
    )
      throw new Error("Page overflows viewport");
    if (width !== 768)
      await page.screenshot({
        path: `/tmp/frontend-${width}.png`,
        fullPage: true,
      });
  }
  if (
    (await page.evaluate(() => localStorage.length + sessionStorage.length)) !==
    0
  )
    throw new Error("Unexpected persisted data");
  await page.getByRole("button", { name: "接続解除", exact: true }).click();
  await expect(page.getByLabel("Bearer token")).toHaveValue("");
  await expect(
    page.getByText("正式安全入力：UI-SAFETY", { exact: true }),
  ).toHaveCount(0);
  console.log(
    JSON.stringify({
      result: "PASS",
      scope:
        "Registered safety input workflow, identity switches, sources, Agent Read, responsive layouts, disconnect",
    }),
  );
} catch (error) {
  console.error(
    JSON.stringify({
      result: "FAIL",
      code: "SAFETY_BROWSER_PROBE_FAILED",
      operation:
        error instanceof Error
          ? error.message.split("\n").slice(0, 3).join(" ")
          : "UNKNOWN",
    }),
  );
  process.exitCode = 1;
} finally {
  await browser.close();
}
