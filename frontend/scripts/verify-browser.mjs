import { chromium, expect } from "@playwright/test";
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
  await page.goto(base);
  await page.getByLabel("Bearer token").fill("日本語を含む不正なtoken");
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("tokenの形式が不正です");
  await page.getByLabel("Bearer token").fill(token);
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "接続解除", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "接続解除", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "接続設定", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "業務データへ接続", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "調査画面へ戻る", exact: true })
    .click();
  const cookies = await page.context().cookies();
  const session = cookies.find((cookie) => cookie.name === "linescope_session");
  if (
    !session?.httpOnly ||
    session.sameSite !== "Strict" ||
    session.value === token
  )
    throw new Error("Invalid browser session cookie");
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
    page.locator("main").getByText("Graph世代", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "計算の根拠", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("デモ入力です。正式な業務情報ではありません。", {
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({ path: "/tmp/frontend-1440.png", fullPage: true });
  await page.getByText("変更準備・承認・実行", { exact: true }).click();
  await page
    .getByLabel("明示的な変更指示")
    .fill("M-204の現在状態をRUNNINGに変更する準備を作って");
  await page
    .getByRole("button", { name: "変更準備を作成", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "保存済みSnapshot", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/状態：WAITING_APPROVAL/)).toBeVisible();
  const requestId = await page
    .getByLabel("変更要求ID", { exact: true })
    .inputValue();
  async function switchUser(secret) {
    await page.getByRole("button", { name: "接続解除", exact: true }).click();
    await page.getByLabel("Bearer token").fill(secret);
    await page.getByRole("button", { name: "接続する", exact: true }).click();
    await page.getByText("変更準備・承認・実行", { exact: true }).click();
    await page.getByLabel("変更要求ID", { exact: true }).fill(requestId);
    await page
      .getByRole("button", { name: "保存状態を再取得", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "保存済みSnapshot", exact: true }),
    ).toBeVisible();
  }
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
  await expect(
    page.getByRole("heading", {
      name: "保存された確定結果（after）",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "実行応答・実行後の現在値",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "承認済み変更を実行", exact: true }),
  ).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "/tmp/frontend-390.png", fullPage: true });
  if (
    (await page.evaluate(() => localStorage.length + sessionStorage.length)) !==
    0
  )
    throw new Error("Unexpected persisted data");
  await page.getByRole("button", { name: "接続解除", exact: true }).click();
  await expect(page.getByLabel("Bearer token")).toHaveValue("");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "接続する", exact: true }),
  ).toBeVisible();
  console.log(
    JSON.stringify({
      result: "PASS",
      scope:
        "Real browser + HTTP + PostgreSQL + Neo4j; Prepare/Approval/Execute with identity switches; decision inputs mocked; no LLM",
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
