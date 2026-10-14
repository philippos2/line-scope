import { afterEach, expect, it, vi } from "vitest";
import { ApiError, envelope, request } from "./client";
const valid = {
  request_id: "r1",
  context_id: null,
  status: "ok",
  answer: "確認",
  data: {},
  evidence: {},
  errors: [],
  warnings: [],
};
afterEach(() => vi.unstubAllGlobals());
it("authenticates only the fixed same-origin API and returns the envelope", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(valid)));
  vi.stubGlobal("fetch", fetcher);
  expect(
    await request("secret", "/agent", { message: "設備を調べる" }),
  ).toEqual(valid);
  expect(fetcher.mock.calls[0][0]).toBe("/api/agent");
  expect(fetcher.mock.calls[0][1]).toMatchObject({
    headers: { Authorization: "Bearer secret" },
    credentials: "omit",
    redirect: "error",
  });
});
it("does not expose a provider message or credential in API errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...valid,
          status: "error",
          errors: [
            { code: "DEPENDENCY_UNAVAILABLE", message: "password=secret" },
          ],
        }),
        { status: 503 },
      ),
    ),
  );
  await expect(
    request("secret", "/agent", { message: "調査" }),
  ).rejects.toMatchObject({
    code: "DEPENDENCY_UNAVAILABLE",
    message: "DEPENDENCY_UNAVAILABLE",
    requestId: "r1",
  });
});
it("rejects an invalid response contract", () => {
  expect(() => envelope({ ...valid, data: null })).toThrow(ApiError);
});
