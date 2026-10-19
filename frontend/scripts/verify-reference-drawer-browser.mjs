// A2: real read-only scenario, plus a controlled saved-request response for target guards.
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
const base = process.env.LINESCOPE_BROWSER_URL;
const token = process.env.LINESCOPE_BROWSER_TOKEN;
if (!base || !token) throw new Error("Private browser configuration required");
const out = process.env.LINESCOPE_BROWSER_OUTPUT ?? "/out";
await mkdir(out, { recursive: true });
const browser = await chromium.launch();
const report = [];
async function run(name, width, verify) {
  const context = await browser.newContext({
    viewport: { width, height: 1050 },
  });
  const page = await context.newPage();
  let reads = 0;
  page.on("request", (req) => {
    if (req.url().includes("/api/")) reads++;
  });
  try {
    await page.goto(base);
    await page.getByLabel("Bearer token").fill(token);
    await page.getByRole("button", { name: "接続する", exact: true }).click();
    await page.getByLabel("設備名・コード", { exact: true }).fill("M-204");
    await page.getByRole("button", { name: "検索", exact: true }).click();
    await page
      .locator(".equipment-search-panel > .equipment-result")
      .first()
      .click();
    await expect(page.locator(".loss-amount")).toContainText("200,000");
    await expect(page.locator(".capacity-assessment")).toContainText("80");
    await expect(
      page
        .locator(".relationship-panel")
        .getByText("読み込み中", { exact: false }),
    ).toHaveCount(0);
    await page.waitForTimeout(500);
    await verify(page, () => reads);
    expect(
      await page.evaluate(
        () =>
          globalThis.document.documentElement.scrollWidth <=
          globalThis.innerWidth + 1,
      ),
    ).toBe(true);
    await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
    report.push({ name, result: "PASS" });
    console.log("PASS", name);
  } catch (error) {
    await page.screenshot({
      path: `${out}/${name}-failure.png`,
      fullPage: true,
    });
    throw error;
  } finally {
    await context.close();
  }
}
try {
  await run("a2-cached-reference", 1600, async (page, reads) => {
    const graph = page.locator("#panel-graph");
    const node = graph.locator(".react-flow__node").first();
    const id = await node.getAttribute("data-id");
    const box = await node.boundingBox();
    await page.mouse.move(box.x + 30, box.y + 30);
    await page.mouse.down();
    await page.mouse.move(box.x + 80, box.y + 60, { steps: 5 });
    await page.mouse.up();
    const position = await node.getAttribute("style");
    await graph.getByLabel("関係図を拡大", { exact: true }).click();
    await page.waitForTimeout(300);
    const viewport = await graph
      .locator(".react-flow__viewport")
      .getAttribute("style");
    await page
      .getByRole("tab", { name: "対応案を比べる", exact: true })
      .click();
    const before = reads();
    await page
      .getByRole("button", { name: "関係図を見る", exact: true })
      .click();
    const drawer = page.getByRole("dialog");
    await expect(
      drawer.locator(`.react-flow__node[data-id="${id}"]`),
    ).toHaveAttribute("style", position);
    await expect(drawer.locator(".react-flow__viewport")).toHaveAttribute(
      "style",
      viewport,
    );
    const mainBox = await page.locator(".investigation-main").boundingBox();
    const drawerBox = await drawer.boundingBox();
    expect(mainBox.x + mainBox.width).toBeLessThanOrEqual(drawerBox.x);
    await page.screenshot({ path: `${out}/a2-wide-drawer.png` });
    await drawer.locator(".graph-node-access summary").click();
    const chosen = drawer
      .getByLabel("関係図の項目一覧")
      .getByRole("button")
      .first();
    await chosen.click();
    await expect(chosen).toHaveAttribute("aria-pressed", "true");
    await drawer.getByLabel("関係図を縮小", { exact: true }).click();
    await page.waitForTimeout(300);
    const changed = await drawer
      .locator(".react-flow__viewport")
      .getAttribute("style");
    await drawer.getByRole("button", { name: "参照を閉じる" }).click();
    await page
      .getByRole("tab", { name: "接続及び影響範囲", exact: true })
      .click();
    await expect(graph.locator(".react-flow__viewport")).toHaveAttribute(
      "style",
      changed,
    );
    await expect(
      graph.locator(`.react-flow__node[data-id="${id}"]`),
    ).toHaveClass(/selected/);
    await page
      .getByRole("button", { name: "調査の根拠を見る", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toContainText("対象結果：調査");
    await page.keyboard.press("Escape");
    await page
      .getByRole("tab", { name: "対応案を比べる", exact: true })
      .click();
    await page
      .getByRole("button", { name: "比較の根拠を確かめる", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toContainText(
      "この結果の根拠は未取得",
    );
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    expect(reads()).toBe(before);
    await expect(page.getByLabel("起点設備の検索")).toBeVisible();
  });
  await run("a2-overlay-resize", 390, async (page, reads) => {
    await page.getByRole("tab", { name: "質問する", exact: true }).click();
    const question = page.locator("#panel-investigation textarea").first();
    await question.fill("編集中の質問を保持する");
    const opener = page.getByRole("button", {
      name: "関係図を見る",
      exact: true,
    });
    const before = reads();
    await opener.click();
    const drawer = page.getByRole("dialog");
    expect(await drawer.evaluate((el) => el.matches(":modal"))).toBe(true);
    await page.screenshot({ path: `${out}/a2-mobile-drawer.png` });
    await drawer.getByRole("button", { name: "参照を閉じる" }).focus();
    await page.keyboard.press("Shift+Tab");
    expect(
      await drawer.evaluate((el) =>
        el.contains(globalThis.document.activeElement),
      ),
    ).toBe(true);
    for (const width of [768, 1600, 390]) {
      await page.setViewportSize({ width, height: 1050 });
      await expect(drawer).toBeVisible();
      await expect
        .poll(() => drawer.evaluate((el) => el.matches(":modal")))
        .toBe(width < 1280);
    }
    await page.keyboard.press("Escape");
    await expect(opener).toBeFocused();
    await expect(question).toHaveValue("編集中の質問を保持する");
    expect(reads()).toBe(before);
  });
  await run("a2-request-target", 1600, async (page, reads) => {
    await page
      .getByRole("tab", { name: "変更・承認・実行", exact: true })
      .click();
    const open = page.getByRole("button", {
      name: "関係図を見る",
      exact: true,
    });
    await open.click();
    await expect(page.getByRole("dialog")).toContainText(
      "変更要求の対象をまだ確認していません",
    );
    await page.keyboard.press("Escape");
    const requestId = "11111111-1111-4111-8111-111111111111";
    // The graph retains the server-returned root identifier.
    const root = await page
      .locator('#panel-graph .react-flow__node[data-id^="Equipment:"]')
      .first()
      .getAttribute("data-id");
    for (const target of [
      "22222222-2222-4222-8222-222222222222",
      root.slice("Equipment:".length),
    ]) {
      await page.route(`**/api/update-requests/${requestId}`, (route) =>
        route.fulfill({
          json: {
            request_id: requestId,
            context_id: null,
            status: "ok",
            answer: null,
            warnings: [],
            errors: [],
            evidence: {},
            data: {
              update_request_id: requestId,
              approval_id: requestId,
              snapshot_hash: "a".repeat(64),
              status: "WAITING_APPROVAL",
              approval_status: "PENDING",
              canonical_snapshot: {
                targets: [
                  {
                    target_type: "EquipmentState",
                    business_key: { equipment_id: target },
                    target_id: target,
                    operation_type: "UPDATE",
                    before: {},
                    after: {},
                  },
                ],
              },
            },
          },
        }),
      );
      await page.getByLabel("変更要求ID", { exact: true }).fill(requestId);
      await page
        .getByRole("button", { name: "保存状態を再取得", exact: true })
        .click();
      await expect(
        page.getByRole("button", { name: "承認者へ渡す変更要求IDをコピー" }),
      ).toBeVisible();
      const before = reads();
      await open.click();
      const drawer = page.getByRole("dialog");
      if (target.startsWith("2222")) {
        await expect(drawer).toContainText(
          "変更要求の対象と調査起点が一致しません",
        );
        await expect(drawer.locator(".relation-canvas")).toHaveCount(0);
      } else {
        await expect(drawer).toContainText(
          "保存された変更内容の一部ではありません",
        );
        await expect(drawer.locator(".relation-canvas")).toBeVisible();
      }
      await page.keyboard.press("Escape");
      expect(reads()).toBe(before);
      await page.unroute(`**/api/update-requests/${requestId}`);
    }
  });
} finally {
  await writeFile(`${out}/a2-results.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
