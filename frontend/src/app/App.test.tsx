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
});
