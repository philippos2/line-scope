import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
vi.mock("../features/graph/GraphCanvas", () => ({
  GraphCanvas: () => <div aria-label="関係図" />,
}));
const context = "00000000-0000-0000-0000-000000000021";
const response = (
  answer: string,
  outcome = "ANSWERED",
  identity: string | null = null,
) =>
  new Response(
    JSON.stringify({
      request_id: "r",
      context_id: identity,
      status: "ok",
      answer,
      data: {
        needs_input: !!identity,
        tool_results: [],
        tool_trace: [],
        answer_sections: {
          version: 1,
          read_outcome: outcome,
          facts: [],
          unavailable: [],
          scope: [],
        },
      },
      evidence: { tool_results: [] },
      errors: [],
      warnings: [],
    }),
  );
function setup(agent: (body: Record<string, unknown>) => Promise<Response>) {
  const sent: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", (url: string, init: RequestInit) => {
    if (url === "/api/session")
      return Promise.resolve(
        new Response(
          JSON.stringify({
            request_id: "r",
            status: "error",
            errors: [{ code: "AUTHENTICATION_REQUIRED" }],
          }),
          { status: 401 },
        ),
      );
    if (url === "/api/agent") {
      const body = JSON.parse(String(init.body));
      sent.push(body);
      return agent(body);
    }
    return Promise.resolve(response("接続済み"));
  });
  render(<App />);
  return sent;
}
async function connect() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Bearer token"), "demo-token");
  await user.click(screen.getByRole("button", { name: "接続する" }));
  await screen.findByRole("button", { name: "接続解除" });
  await user.click(screen.getByRole("tab", { name: "質問する" }));
  return user;
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("has one question textbox and directly presents the registered answer", async () => {
  const sent = setup(async () =>
    response("第1加工機（M-204）は登録上停止中です。"),
  );
  const user = await connect();
  const panel = screen.getByRole("tabpanel", { name: "質問する" });
  expect(within(panel).getAllByRole("textbox")).toHaveLength(1);
  expect(within(panel).queryByRole("combobox")).toBeNull();
  expect(within(panel).getAllByRole("button")).toHaveLength(1);
  await user.type(
    screen.getByLabelText("関係や影響について質問する"),
    "m204の登録状態は？",
  );
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText("第1加工機（M-204）は登録上停止中です。");
  expect(sent[0].message).toBe("m204の登録状態は？");
});
it("chooses an ambiguous target by replying in the same textbox", async () => {
  const sent = setup(async (body) =>
    body.context_id
      ? response("第1加工機（M-204）の登録状態です。")
      : response(
          "第1加工機 M-204、第2加工機 M-208。どちらですか？",
          "TARGET_AMBIGUOUS",
          context,
        ),
  );
  const user = await connect();
  const input = screen.getByLabelText("関係や影響について質問する");
  await user.type(input, "加工機の登録状態は？");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText(/どちらですか/);
  await user.clear(input);
  await user.type(input, "M204");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText("第1加工機（M-204）の登録状態です。");
  expect(sent[1]).toEqual({ message: "M204", context_id: context });
  expect(
    within(screen.getByRole("log", { name: "質問と回答" })).getAllByRole(
      "article",
    ),
  ).toHaveLength(2);
});
it("keeps unsupported scope and guidance inside the conversation", async () => {
  setup(async () =>
    response(
      "第1加工機（M-204）は確認できましたが、電話番号は照会できません。例えば『M-204の登録状態は？』と質問してください。",
      "UNSUPPORTED",
    ),
  );
  const user = await connect();
  await user.type(
    screen.getByLabelText("関係や影響について質問する"),
    "m204の製造メーカーの顧客対応電話番号は何か？",
  );
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText(/電話番号は照会できません/);
  expect(screen.queryByRole("combobox")).toBeNull();
});
it("ignores a delayed answer after the user edits the question", async () => {
  let finish: (r: Response) => void = () => {};
  setup(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const user = await connect();
  const input = screen.getByLabelText("関係や影響について質問する");
  await user.type(input, "m204の登録状態は？");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await user.clear(input);
  await user.type(input, "M208の登録状態は？");
  finish(response("古い設備の回答"));
  expect((input as HTMLTextAreaElement).value).toBe("M208の登録状態は？");
  expect(screen.queryByText("古い設備の回答")).toBeNull();
});
