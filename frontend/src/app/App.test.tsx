import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import type { Envelope } from "../api/client";
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
  return user;
}
it("connects and shows actual answer and server Evidence", async () => {
  stubFetch(vi.fn().mockImplementation(() => Promise.resolve(reply())));
  render(<App />);
  const user = await connect();
  await user.type(screen.getByLabelText("問い合わせ"), "設備を調べる");
  await user.click(screen.getByRole("button", { name: "問い合わせを送信" }));
  await screen.findByText("取得した回答");
  await user.click(screen.getByRole("button", { name: "Evidence" }));
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
  await user.type(screen.getByLabelText("問い合わせ"), "調査");
  await user.click(screen.getByRole("button", { name: "問い合わせを送信" }));
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
  await user.type(screen.getByLabelText("問い合わせ"), "調査");
  await user.click(screen.getByRole("button", { name: "問い合わせを送信" }));
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
  await user.type(screen.getByLabelText("問い合わせ"), "調査");
  await user.click(screen.getByRole("button", { name: "問い合わせを送信" }));
  await screen.findByText("PARTIAL / 部分結果");
  await user.click(screen.getByRole("button", { name: "問い合わせを送信" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual({
    message: "調査",
    context_id: "c1",
  });
});
