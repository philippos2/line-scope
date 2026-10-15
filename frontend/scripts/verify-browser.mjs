import { chromium, expect } from "@playwright/test";
const base = process.env.LINESCOPE_BROWSER_URL;
const token = process.env.LINESCOPE_BROWSER_TOKEN;
const approver = process.env.LINESCOPE_BROWSER_APPROVER_TOKEN;
if (!base || !token || !approver)
  throw new Error("Explicit browser fixture configuration required");
async function activate(locator) {
  await locator.focus();
  await expect(locator).toBeFocused();
  await locator.press("Enter");
}
async function tabTo(page, locator) {
  for (let i = 0; i < 80; i++) {
    if (
      await locator.evaluate(
        (element) => element === globalThis.document.activeElement,
      )
    )
      return;
    await page.keyboard.press("Tab");
  }
  throw new Error("Keyboard target is unreachable");
}
const browser = await chromium.launch({ headless: true });
let phase = "connection";
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
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "調査領域へ移動" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#workspace")).toBeFocused();
  await activate(page.getByRole("button", { name: "接続設定", exact: true }));
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
  await activate(page.getByRole("button", { name: "比較デモ", exact: true }));
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "問い合わせを送信", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("PARTIAL / 部分結果", { exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("img")).toBeVisible();
  await expect(
    page.getByText(
      "MOCK_FIXTUREを含む比較デモ。費用・能力・安全条件は仮置きです。",
    ),
  ).toBeVisible();
  await activate(page.getByRole("button", { name: "影響・経路", exact: true }));
  const graphNode = page
    .getByLabel("Graphノードの一覧")
    .getByRole("button")
    .first();
  await activate(graphNode);
  await expect(graphNode).toHaveAttribute("aria-pressed", "true");
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
  await activate(
    page.locator("summary").filter({ hasText: /^変更準備・承認・実行$/ }),
  );
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
  let requestId = await page
    .getByLabel("変更要求ID", { exact: true })
    .inputValue();
  async function switchUser(secret) {
    await page.getByRole("button", { name: "接続解除", exact: true }).click();
    await page.getByLabel("Bearer token").fill(secret);
    await page.getByRole("button", { name: "接続する", exact: true }).click();
    await activate(
      page.locator("summary").filter({ hasText: /^変更準備・承認・実行$/ }),
    );
    await page.getByLabel("変更要求ID", { exact: true }).fill(requestId);
    await page
      .getByRole("button", { name: "保存状態を再取得", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "保存済みSnapshot", exact: true }),
    ).toBeVisible();
  }
  await switchUser(approver);
  await expect(
    page.getByRole("heading", { name: "保存済みSnapshot", exact: true }),
  ).toBeFocused();
  await tabTo(page, page.getByLabel("保存Snapshotと操作内容を確認しました"));
  await page.keyboard.press("Space");
  await activate(
    page.getByRole("button", { name: "Snapshotを承認", exact: true }),
  );
  await expect(page.getByText(/状態：APPROVED/)).toBeVisible();
  await switchUser(token);
  await expect(
    page.getByRole("heading", { name: "保存済みSnapshot", exact: true }),
  ).toBeFocused();
  await tabTo(page, page.getByLabel("保存Snapshotと操作内容を確認しました"));
  await page.keyboard.press("Space");
  await activate(
    page.getByRole("button", { name: "承認済み変更を実行", exact: true }),
  );
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
  phase = "category-actions";
  async function prepareAndReview(message, targetType, reject = false) {
    await page.getByLabel("明示的な変更指示").fill(message);
    await activate(
      page.getByRole("button", { name: "変更準備を作成", exact: true }),
    );
    await expect(page.getByText(/状態：WAITING_APPROVAL/)).toBeVisible();
    await expect(
      page
        .locator(".action-panel")
        .getByRole("heading", { name: new RegExp(targetType) })
        .first(),
    ).toBeVisible();
    requestId = await page
      .getByLabel("変更要求ID", { exact: true })
      .inputValue();
    await switchUser(approver);
    await tabTo(page, page.getByLabel("保存Snapshotと操作内容を確認しました"));
    await page.keyboard.press("Space");
    await activate(
      page.getByRole("button", {
        name: reject ? "変更要求を拒否" : "Snapshotを承認",
        exact: true,
      }),
    );
    await expect(
      page.getByText(reject ? /状態：REJECTED/ : /状態：APPROVED/),
    ).toBeVisible();
    await switchUser(token);
    if (reject) {
      await expect(
        page.getByRole("button", { name: "承認済み変更を実行", exact: true }),
      ).toBeDisabled();
      return;
    }
    await tabTo(page, page.getByLabel("保存Snapshotと操作内容を確認しました"));
    await page.keyboard.press("Space");
    await activate(
      page.getByRole("button", { name: "承認済み変更を実行", exact: true }),
    );
    await expect(page.getByText(/状態：COMPLETED/)).toBeVisible();
  }
  await prepareAndReview(
    "設備M-204の保全予定UI-PLANを開始2026-11-01T00:00:00Z、終了2026-11-01T01:00:00Z、状態計画済みで登録して",
    "MaintenancePlan",
  );
  await prepareAndReview(
    "生産作業OP-30の予定状態をCANCELLEDに変更して",
    "ProductionOperation",
  );
  const relation = {
    source_entity_type: "Equipment",
    source_entity_id: "20400000-0000-4000-8000-000000000001",
    target_entity_type: "Equipment",
    target_entity_id: "20800000-0000-4000-8000-000000000001",
    relation_type: "SUPPLIES",
    effective_from: "2026-10-01T00:00:00Z",
    effective_to: null,
    required: false,
    active: true,
  };
  await prepareAndReview(
    "依存関係を" + JSON.stringify(relation) + "で登録して",
    "DependencyRelation",
  );
  await prepareAndReview(
    "M-204の現在状態をSTOPPEDに変更する準備を作って",
    "EquipmentState",
    true,
  );
  await page
    .getByLabel("問い合わせ", { exact: true })
    .fill("文書検索：M-204 保全手順");
  phase = "citation";
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/agent") &&
      response.request().method() === "POST",
  );
  await activate(
    page.getByRole("button", { name: "問い合わせを送信", exact: true }),
  );
  const retrieved = await (await responsePromise).json();
  const realVector = process.env.LINESCOPE_BROWSER_VECTOR === "true";
  if (
    realVector &&
    (retrieved.data.search_source !== "QDRANT" || retrieved.data.demo_only)
  )
    throw new Error("Expected real vector retrieval");
  await activate(page.getByRole("button", { name: "Evidence", exact: true }));
  const citation = page.locator(".document-citation");
  await expect(citation).toHaveCount(1);
  await expect(
    citation.getByRole("heading", { name: "保全資料", exact: true }),
  ).toBeVisible();
  await expect(citation.locator("blockquote")).toContainText(
    '<img src="/never-fetch"',
  );
  await expect(citation.locator("img")).toHaveCount(0);
  if (await page.evaluate(() => globalThis.documentCommandExecuted === true))
    throw new Error("Document command executed");
  await page.screenshot({ path: "/tmp/frontend-1440.png", fullPage: true });
  phase = "viewport";
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
  }
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
        "Real browser + HTTP + PostgreSQL + Neo4j; Prepare/Approval/Execute across four categories and rejection with identity switches; keyboard and citation checks; decision inputs mocked; no LLM",
      screenshots: ["1440", "390"],
      retrieval:
        process.env.LINESCOPE_BROWSER_VECTOR === "true"
          ? "REAL_EMBEDDING_QDRANT"
          : "MOCK_EMBEDDING_QDRANT",
    }),
  );
} catch {
  console.error(
    JSON.stringify({ result: "FAIL", code: "FRONTEND_PROBE_FAILED", phase }),
  );
  process.exitCode = 1;
} finally {
  await browser.close();
}
