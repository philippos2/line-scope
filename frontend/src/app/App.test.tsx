import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import type { Envelope } from "../api/client";
vi.mock("../features/graph/GraphCanvas", () => ({
  GraphCanvas: () => <div aria-label="関係図" />,
}));
const base: Envelope = {
  request_id: "r1",
  context_id: null,
  status: "ok",
  answer: "取得した回答",
  data: {},
  evidence: { source: "server" },
  warnings: [],
  errors: [],
};
const reply = (data = base) => new Response(JSON.stringify(data));
function stubFetch(fetcher: (url: string, init: RequestInit) => unknown) {
  vi.stubGlobal("fetch", (url: string, init: RequestInit) => {
    if (url === "/api/session")
      return Promise.resolve(
        new Response(
          JSON.stringify({
            ...base,
            status: "error",
            errors: [{ code: "AUTHENTICATION_REQUIRED" }],
          }),
          { status: 401 },
        ),
      );
    if (url === "/api/session/logout") return Promise.resolve(reply());
    return fetcher(url, init);
  });
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
async function connect() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Bearer token"), "secret");
  await user.click(screen.getByRole("button", { name: "接続する" }));
  await screen.findByRole("button", { name: "接続解除" });
  await user.click(screen.getByRole("tab", { name: "質問する" }));
  return user;
}
it("connects and shows actual answer and server Evidence", async () => {
  stubFetch(vi.fn().mockImplementation(() => Promise.resolve(reply())));
  render(<App />);
  const user = await connect();
  await user.type(
    screen.getByLabelText("関係や影響について質問する"),
    "設備を調べる",
  );
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText("取得した回答");
  await user.click(screen.getByRole("tab", { name: "出典と経路" }));
  expect(screen.getAllByText(/server/).length).toBeGreaterThan(0);
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});
it("disconnects while a response is pending and never restores old results", async () => {
  let finish: (r: Response) => void = () => {};
  stubFetch(
    vi
      .fn()
      .mockResolvedValueOnce(reply())
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      ),
  );
  render(<App />);
  const user = await connect();
  await user.type(screen.getByLabelText("関係や影響について質問する"), "調査");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await user.click(screen.getByRole("button", { name: "接続解除" }));
  finish(reply());
  await waitFor(() => expect(screen.queryByText("取得した回答")).toBeNull());
  expect(
    (screen.getByLabelText("Bearer token") as HTMLInputElement).value,
  ).toBe("");
});
it("renders untrusted answer text without executing HTML", async () => {
  stubFetch(
    vi
      .fn()
      .mockResolvedValueOnce(reply())
      .mockResolvedValueOnce(
        reply({ ...base, answer: "<img src=x onerror=alert(1)>" }),
      ),
  );
  render(<App />);
  const user = await connect();
  await user.type(screen.getByLabelText("関係や影響について質問する"), "調査");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText("<img src=x onerror=alert(1)>");
  expect(document.querySelector("img")).toBeNull();
});
it("passes server conversation context and clearly marks a partial result", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(reply())
    .mockResolvedValueOnce(
      reply({ ...base, context_id: "c1", status: "partial" }),
    )
    .mockResolvedValueOnce(reply());
  stubFetch(fetcher);
  render(<App />);
  const user = await connect();
  await user.type(screen.getByLabelText("関係や影響について質問する"), "調査");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText("一部の情報・評価が不足しています");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual({
    message: "調査",
    context_id: "c1",
  });
});
it("selects equipment through the common search, loads relationships directly and grounds a fresh question", async () => {
  const target = {
    equipment_id: "20800000-0000-4000-8000-000000000001",
    equipment_code: "M-208",
    equipment_name: "予備加工機",
  };
  const fetcher = vi
    .fn()
    .mockImplementation((url: string, init: RequestInit) => {
      if (url === "/api/session/login") return Promise.resolve(reply());
      if (url.endsWith("/search"))
        return Promise.resolve(
          reply({ ...base, data: { items: [], next_cursor: null } }),
        );
      const body = JSON.parse(String(init.body));
      if (body.message?.startsWith("関係分析 ")) {
        const command = JSON.parse(body.message.slice(5));
        const data =
          command.tool === "search_equipment"
            ? { items: [target], next_cursor: null }
            : {
                target: {
                  entity_type: "Equipment",
                  entity_id: target.equipment_id,
                },
                representative_paths: [],
                reached_nodes: [],
                graph_sync_state: "CURRENT",
                complete: true,
              };
        return Promise.resolve(
          reply({
            ...base,
            context_id: "read-only-context",
            data: { tool_results: [{ tool: command.tool, data }] },
          }),
        );
      }
      return Promise.resolve(reply());
    });
  stubFetch(fetcher);
  render(<App />);
  const user = await connect();
  await user.click(screen.getByRole("button", { name: "設備を選ぶ" }));
  await user.type(screen.getByLabelText("設備名・コード"), "M-208");
  await user.click(screen.getByRole("button", { name: "検索" }));
  await user.click(
    await screen.findByRole("button", { name: /予備加工機.*M-208/ }),
  );
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([, init]) =>
        String(init.body).includes("trace_downstream_impact"),
      ),
    ).toBe(true),
  );
  await user.type(
    screen.getByLabelText("関係や影響について質問する"),
    "この設備の状態は？",
  );
  await user.click(screen.getByRole("button", { name: "送信" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([, init]) =>
        String(init.body).includes("調査対象の設備コードはM-208"),
      ),
    ).toBe(true),
  );
  const call = fetcher.mock.calls.find(([, init]) =>
    String(init.body).includes("調査対象の設備コードはM-208"),
  )!;
  expect(JSON.parse(String(call[1].body)).context_id).toBeUndefined();
  const question = "第１加工機の前回のメンテナンス日時はいつか？";
  const input = screen.getByLabelText("関係や影響について質問する");
  await user.clear(input);
  await user.type(input, question);
  await user.click(screen.getByRole("button", { name: "送信" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        ([, init]) =>
          typeof init.body === "string" &&
          JSON.parse(init.body).message ===
            `調査対象の設備コードはM-208です。\n${question}`,
      ),
    ).toBe(true),
  );
  expect((input as HTMLTextAreaElement).value).toBe(question);
  await user.click(screen.getByRole("tab", { name: "接続及び影響範囲" }));
  expect(screen.getByText(/比較画面で対応計画などの登録状況/)).toBeDefined();
  await user.click(
    screen.getByRole("button", { name: "M-208の比較用入力を確認する" }),
  );
  expect(
    screen
      .getByRole("tab", { name: "対応案を比べる" })
      .getAttribute("aria-selected"),
  ).toBe("true");
});
it("retains a previous answer as previous when a subsequent question fails, then recovers explicitly", async () => {
  stubFetch(
    vi
      .fn()
      .mockResolvedValueOnce(reply())
      .mockResolvedValueOnce(reply())
      .mockRejectedValueOnce(new TypeError("network failure"))
      .mockResolvedValueOnce(reply({ ...base, answer: "今回の回答" })),
  );
  render(<App />);
  const user = await connect();
  expect(
    (screen.getByRole("button", { name: "送信" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  const input = screen.getByLabelText("関係や影響について質問する");
  await user.type(input, "最初の質問");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText("取得した回答");
  await user.clear(input);
  await user.type(input, "次の質問");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByRole("alert");
  expect(screen.getByText("取得した回答")).toBeDefined();
  expect(screen.getByText(/前回取得した回答/)).toBeDefined();
  expect((input as HTMLTextAreaElement).value).toBe("次の質問");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByText("今回の回答");
  expect(
    (screen.getByRole("button", { name: "送信" }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);
  expect(
    screen.getByRole("button", { name: "送信" }).getAttribute("aria-busy"),
  ).toBe("false");
  expect(screen.queryByText(/前回取得した回答/)).toBeNull();
});
it("explains a login rejection without exposing the code outside technical details", async () => {
  stubFetch(
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...base,
          status: "error",
          errors: [{ code: "AUTHENTICATION_REQUIRED" }],
        }),
        { status: 401 },
      ),
    ),
  );
  render(<App />);
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Bearer token"), "invalid");
  await user.click(screen.getByRole("button", { name: "接続する" }));
  await screen.findByRole("alert");
  expect(
    screen
      .getByText("AUTHENTICATION_REQUIRED")
      .closest("details")
      ?.hasAttribute("open"),
  ).toBe(false);
  expect(
    (screen.getByRole("button", { name: "接続する" }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);
});
it("does not describe a pending question as a pending login in connection settings", async () => {
  let resolve: (value: Response) => void = () => {};
  stubFetch(
    vi
      .fn()
      .mockResolvedValueOnce(reply())
      .mockImplementationOnce(
        () =>
          new Promise<Response>((done) => {
            resolve = done;
          }),
      ),
  );
  render(<App />);
  const user = await connect();
  await user.type(
    screen.getByLabelText("関係や影響について質問する"),
    "登録状態を読む",
  );
  await user.click(screen.getByRole("button", { name: "送信" }));
  await user.click(screen.getByRole("button", { name: "接続設定" }));
  expect(
    screen.getByText(/質問への応答を待っています。完了してから接続/),
  ).toBeDefined();
  expect(
    screen.getByRole("button", { name: "接続する" }).getAttribute("aria-busy"),
  ).toBe("false");
  resolve(reply());
  await waitFor(() =>
    expect(
      screen.queryByText(/質問への応答を待っています。完了してから接続/),
    ).toBeNull(),
  );
});
it("U08 rejects a read scope without reading it and ignores a late reply after editing", async () => {
  let finish: (value: Response) => void = () => {};
  const sent: Record<string, unknown>[] = [];
  const pending: Envelope = {
    ...base,
    context_id: "pending-read",
    data: {
      needs_input: true,
      read_clarification: {
        kind: "READ_SCOPE",
        status: "PENDING",
        original_question: "対象は動いてる？",
        targets: ["対象 · E-7"],
        scope: ["登録上の設備状態"],
      },
      answer_sections: { version: 1, facts: [], unavailable: [], scope: [] },
    },
  };
  stubFetch((url, init) => {
    if (url !== "/api/agent") return Promise.resolve(reply());
    const body = JSON.parse(String(init.body));
    sent.push(body);
    if (body.read_confirmation === "REJECT")
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    return Promise.resolve(reply(pending));
  });
  render(<App />);
  const user = await connect();
  const input = screen.getByLabelText("関係や影響について質問する");
  await user.type(input, "対象は動いてる？");
  await user.click(screen.getByRole("button", { name: "送信" }));
  await screen.findByRole("button", { name: "この範囲を調べる" });
  await user.click(screen.getByRole("button", { name: "違う・質問を直す" }));
  expect(document.activeElement).toBe(input);
  expect((input as HTMLTextAreaElement).value).toBe("対象は動いてる？");
  await user.type(input, "別の意味です");
  finish(reply(pending));
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "この範囲を調べる" }),
    ).toBeNull(),
  );
  expect(sent.map((body) => body.read_confirmation)).toEqual([
    undefined,
    "REJECT",
  ]);
  expect((input as HTMLTextAreaElement).value).toContain("別の意味です");
});
