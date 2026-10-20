import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
const target = {
  entity_type: "Equipment",
  entity_id: "11111111-1111-4111-8111-111111111111",
};
const equipment = {
  equipment_id: target.entity_id,
  equipment_code: "M-204",
  equipment_name: "第1加工機",
};
vi.mock("../features/graph/GraphCanvas", () => ({
  GraphCanvas: ({ onSelect }: { onSelect: (value: typeof target) => void }) => (
    <button onClick={() => onSelect(target)}>設備ノードを選ぶ</button>
  ),
}));
// Exercise the UI's execution notification, not the approval/write backend.
vi.mock("../features/actions/ActionPanel", () => ({
  ActionPanel: ({ onExecution }: { onExecution: () => void }) => (
    <button onClick={onExecution}>更新完了を通知</button>
  ),
}));
const envelope = (data: Record<string, unknown>) =>
  new Response(
    JSON.stringify({
      request_id: "r",
      context_id: null,
      status: "ok",
      answer: "取得済み",
      data,
      evidence: { graph_generation: "g1" },
      warnings: [],
      errors: [],
    }),
  );
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("marks graph, summaries, loss and alternatives as preceding execution until investigation is refreshed", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/session") return envelope({ user_id: "manager1" });
    if (url === "/api/economic-inputs/search")
      return envelope({
        items: [{ economic_input_id: "economic" }],
        next_cursor: null,
      });
    if (url === "/api/economic-inputs/economic")
      return envelope({
        input: {
          economic_input_id: "economic",
          equipment_id: target.entity_id,
          input_code: "registered-cost",
          version: 1,
          payload: {
            period_start: "2026-10-18T00:00:00Z",
            period_end: "2026-10-19T00:00:00Z",
          },
        },
      });
    if (url === "/api/incidents/investigate")
      return envelope({
        impacts: [{ equipment_id: target.entity_id, state_code: "STOPPED" }],
        loss: { complete: true, loss_per_hour: "200000", items: [] },
      });
    if (url === "/api/agent") {
      const { message } = JSON.parse(String(init?.body));
      if (message.startsWith("関係分析 ")) {
        const { tool } = JSON.parse(message.slice(5));
        const data =
          tool === "search_equipment"
            ? { items: [equipment], next_cursor: null }
            : tool === "get_equipment"
              ? equipment
              : {
                  target,
                  graph_sync_state: "CURRENT",
                  complete: true,
                  representative_paths: [],
                  reached_nodes: [],
                };
        return envelope({ tool_results: [{ tool, data }] });
      }
      return envelope({});
    }
    throw new Error(`Unexpected read: ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "接続解除" });
  await user.type(screen.getByLabelText("設備名・コード"), "M-204");
  await user.click(screen.getByRole("button", { name: "検索" }));
  await user.click(
    await screen.findByRole("button", { name: /第1加工機.*M-204/ }),
  );
  await screen.findByRole("button", { name: "設備ノードを選ぶ" });
  await screen.findByText("200,000 円／時間");
  const summary = screen.getByRole("region", { name: "調査の要約" });
  const graph = screen.getByRole("tabpanel", { name: "接続及び影響範囲" });
  expect(summary.textContent).not.toContain("更新前");
  await user.click(screen.getByRole("tab", { name: "出典と経路" }));
  await user.click(screen.getByRole("button", { name: "関連文書" }));
  await user.click(
    screen.getByRole("button", { name: "選択設備の関連文書を検索" }),
  );
  await screen.findByRole("region", { name: "文書検索の取得状態" });
  await user.click(screen.getByRole("tab", { name: "変更・承認・実行" }));
  await user.click(screen.getByRole("button", { name: "更新完了を通知" }));
  await user.click(screen.getByRole("tab", { name: "接続及び影響範囲" }));
  expect(within(summary).getByText(/登録上.*更新前/)).toBeDefined();
  expect(
    within(summary).getByRole("button", { name: /200,000.*更新前/ }),
  ).toBeDefined();
  expect(within(summary).getByText(/未評価・提案なし.*更新前/)).toBeDefined();
  expect(
    within(graph).getByRole("region", { name: "推定損害額" }).textContent,
  ).toContain("更新前");
  expect(
    within(graph).getByRole("region", { name: "代替の提案" }).textContent,
  ).toContain("更新前");
  expect(within(graph).getAllByText(/更新前の結果/).length).toBeGreaterThan(0);
  await user.click(screen.getByRole("tab", { name: "出典と経路" }));
  expect(screen.getByText(/更新前の検索結果/)).toBeDefined();
  await user.click(
    screen.getByRole("button", { name: "選択設備の関連文書を検索" }),
  );
  await waitFor(() =>
    expect(screen.queryByText(/更新前の検索結果/)).toBeNull(),
  );
  await user.click(screen.getByRole("tab", { name: "質問する" }));
  // The answer arrived before execution, so graph refresh alone must not refresh it.
  await user.type(
    screen.getByLabelText("関係や影響について質問する"),
    "設備の状態",
  );
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText("取得済み");
  await user.click(screen.getByRole("tab", { name: "変更・承認・実行" }));
  await user.click(screen.getByRole("button", { name: "更新完了を通知" }));
  await user.click(screen.getByRole("tab", { name: "質問する" }));
  expect(screen.getByText(/更新前の回答です/)).toBeDefined();
  await user.click(screen.getByRole("button", { name: "送信" }));
  await waitFor(() =>
    expect(screen.queryByText(/更新前の回答です/)).toBeNull(),
  );
  await user.click(screen.getByRole("tab", { name: "接続及び影響範囲" }));
  const calls = fetcher.mock.calls.length;
  await user.click(screen.getByRole("button", { name: "設備ノードを選ぶ" }));
  await waitFor(() => expect(fetcher.mock.calls.length).toBeGreaterThan(calls));
  expect(summary.textContent).toContain("更新前");
  await user.click(screen.getByRole("button", { name: "再調査" }));
  await waitFor(() => expect(summary.textContent).not.toContain("更新前"));
  await screen.findByText("200,000 円／時間");
  expect(graph.textContent).not.toContain("更新前");
});
