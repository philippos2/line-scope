import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
const target = {
  entity_type: "Equipment",
  entity_id: "11111111-1111-4111-8111-111111111111",
};
vi.mock("../features/graph/GraphCanvas", () => ({
  GraphCanvas: ({ onSelect }: { onSelect: (value: typeof target) => void }) => (
    <button onClick={() => onSelect(target)}>設備ノードを選ぶ</button>
  ),
}));
vi.mock("../features/actions/ActionPanel", () => ({
  ActionPanel: ({ onExecution }: { onExecution: () => void }) => (
    <button onClick={onExecution}>更新試行を通知</button>
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
      evidence: {},
      warnings: [],
      errors: [],
    }),
  );
const graph = () =>
  envelope({
    tool_results: [
      {
        tool: "trace_downstream_impact",
        data: {
          target,
          graph_sync_state: "CURRENT",
          representative_paths: [],
          complete: true,
        },
      },
    ],
  });
const notice = "更新操作後の関係は未確認です。関係を再取得してください。";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("marks only graphs predating an update and clears the warning only on graph retrieval", async () => {
  let next: () => Promise<Response> = async () => graph();
  vi.stubGlobal("fetch", (url: string) =>
    url === "/api/session"
      ? Promise.resolve(envelope({ user_id: "manager1" }))
      : next(),
  );
  render(<App />);
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "接続解除" });
  const input = screen.getByLabelText("関係や影響について質問する");
  await user.type(input, "調査");
  const send = screen.getByRole("button", { name: "問い合わせを送信" });
  await user.click(send);
  await screen.findByRole("button", { name: "設備ノードを選ぶ" });
  expect(screen.queryByText(notice)).toBeNull();
  let finish: (response: Response) => void = () => {};
  next = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  await user.click(send);
  expect(screen.queryByText(notice)).toBeNull();
  finish(
    envelope({
      tool_results: [
        { tool: "get_equipment", data: { equipment_id: target.entity_id } },
      ],
    }),
  );
  await waitFor(() => expect((send as HTMLButtonElement).disabled).toBe(false));
  next = async () => {
    throw new TypeError("network failure");
  };
  await user.click(send);
  await screen.findByRole("alert");
  expect(screen.queryByText(notice)).toBeNull();
  await user.click(screen.getByRole("button", { name: "変更・承認・実行" }));
  await user.click(screen.getByRole("button", { name: "更新試行を通知" }));
  expect(screen.getByText(notice)).not.toBeNull();
  await user.click(screen.getByRole("button", { name: "設備ノードを選ぶ" }));
  next = async () =>
    envelope({
      tool_results: [
        { tool: "get_equipment", data: { equipment_id: target.entity_id } },
      ],
    });
  await user.click(screen.getByRole("button", { name: "名称・属性を取得" }));
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "名称・属性を取得",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(screen.getByText(notice)).not.toBeNull();
  next = async () => graph();
  await user.click(screen.getByRole("button", { name: "調査・回答" }));
  await user.click(send);
  await waitFor(() => expect(screen.queryByText(notice)).toBeNull());
});
