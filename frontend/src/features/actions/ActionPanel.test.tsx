import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ActionPanel } from "./ActionPanel";

const requestId = "11111111-1111-4111-8111-111111111111";
const approvalId = "22222222-2222-4222-8222-222222222222";
const hash = "a".repeat(64);
const saved = {
  request_id: "response-id",
  context_id: null,
  status: "ok",
  answer: null,
  evidence: {},
  warnings: [],
  errors: [],
  data: {
    update_request_id: requestId,
    approval_id: approvalId,
    snapshot_hash: hash,
    status: "WAITING_APPROVAL",
    effective_status: "WAITING_APPROVAL",
    approval_status: "PENDING",
    canonical_snapshot: {
      requester_id: "owner",
      targets: [
        {
          target_type: "EquipmentState",
          target_id: "equipment",
          operation_type: "UPDATE",
          before: { state_code: "STOPPED" },
          after: { state_code: "RUNNING" },
        },
      ],
    },
  },
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("requires a saved Snapshot confirmation, sends its hash once, and requires reload after an uncertain write", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(saved)))
    .mockResolvedValueOnce(new Response(JSON.stringify(saved)))
    .mockRejectedValueOnce(new TypeError("network failure"));
  vi.stubGlobal("fetch", fetcher);
  render(<ActionPanel />);
  const user = userEvent.setup();
  await user.click(screen.getByText("変更準備・承認・実行"));
  await user.type(screen.getByLabelText("変更要求ID"), requestId);
  await user.click(screen.getByRole("button", { name: "保存状態を再取得" }));
  await screen.findByRole("heading", { name: "保存済みSnapshot" });
  const approve = screen.getByRole("button", { name: "Snapshotを承認" });
  expect((approve as HTMLButtonElement).disabled).toBe(true);
  await user.click(
    screen.getByLabelText("保存Snapshotと操作内容を確認しました"),
  );
  await user.click(approve);
  await screen.findByRole("alert");
  expect(fetcher).toHaveBeenCalledTimes(2);
  const [path, init] = fetcher.mock.calls[1];
  expect(path).toBe(`/api/approvals/${approvalId}/approve`);
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({ snapshot_hash: hash });
  expect(screen.queryByRole("button", { name: "Snapshotを承認" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "保存状態を再取得" }));
  await screen.findByRole("heading", { name: "保存済みSnapshot" });
  expect(
    (
      screen.getByRole("button", {
        name: "Snapshotを承認",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

it("aborts pending work when the connection view unmounts and ignores a late Prepare response", async () => {
  let finish: (value: Response) => void = () => {};
  const fetcher = vi.fn().mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const mounted = render(<ActionPanel />);
  const user = userEvent.setup();
  await user.click(screen.getByText("変更準備・承認・実行"));
  await user.type(
    screen.getByLabelText("明示的な変更指示"),
    "M-204の状態をRUNNINGに変更して",
  );
  await user.click(screen.getByRole("button", { name: "変更準備を作成" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const signal = fetcher.mock.calls[0][1].signal as AbortSignal;
  mounted.unmount();
  expect(signal.aborted).toBe(true);
  finish(new Response(JSON.stringify(saved)));
  await Promise.resolve();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("clears a previous request ID on uncertain Prepare and reuses the same retry key", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(saved)))
    .mockRejectedValueOnce(new TypeError("network failure"))
    .mockResolvedValueOnce(new Response(JSON.stringify(saved)))
    .mockResolvedValueOnce(new Response(JSON.stringify(saved)));
  vi.stubGlobal("fetch", fetcher);
  render(<ActionPanel />);
  const user = userEvent.setup();
  await user.click(screen.getByText("変更準備・承認・実行"));
  await user.type(screen.getByLabelText("変更要求ID"), requestId);
  await user.click(screen.getByRole("button", { name: "保存状態を再取得" }));
  await screen.findByRole("heading", { name: "保存済みSnapshot" });
  await user.type(
    screen.getByLabelText("明示的な変更指示"),
    "M-204の状態をRUNNINGに変更して",
  );
  await user.click(screen.getByRole("button", { name: "変更準備を作成" }));
  await screen.findByRole("alert");
  expect((screen.getByLabelText("変更要求ID") as HTMLInputElement).value).toBe(
    "",
  );
  expect(fetcher).toHaveBeenCalledTimes(2);
  await user.click(screen.getByRole("button", { name: "変更準備を作成" }));
  await screen.findByRole("heading", { name: "保存済みSnapshot" });
  expect(fetcher).toHaveBeenCalledTimes(4);
  const original = fetcher.mock.calls[1][1].headers["Idempotency-Key"];
  expect(original).toBeTruthy();
  expect(fetcher.mock.calls[2][1].headers["Idempotency-Key"]).toBe(original);
});
