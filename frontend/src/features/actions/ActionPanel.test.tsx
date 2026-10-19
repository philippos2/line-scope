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
  await user.click(
    screen.getByRole("button", { name: "変更指示から準備を作成" }),
  );
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
  await user.click(
    screen.getByRole("button", { name: "変更指示から準備を作成" }),
  );
  await screen.findByRole("alert");
  expect((screen.getByLabelText("変更要求ID") as HTMLInputElement).value).toBe(
    "",
  );
  expect(fetcher).toHaveBeenCalledTimes(2);
  await user.click(
    screen.getByRole("button", { name: "変更指示から準備を作成" }),
  );
  await screen.findByRole("heading", { name: "保存済みSnapshot" });
  expect(fetcher).toHaveBeenCalledTimes(4);
  expect(
    (
      screen.getByRole("button", {
        name: "変更準備を作成済み",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getByText(
      "この指示の変更準備は作成済みです。保存内容と承認状態を確認してください。",
    ),
  ).toBeTruthy();
  const original = fetcher.mock.calls[1][1].headers["Idempotency-Key"];
  expect(original).toBeTruthy();
  expect(fetcher.mock.calls[2][1].headers["Idempotency-Key"]).toBe(original);
});

async function openSaved() {
  render(<ActionPanel />);
  const user = userEvent.setup();
  await user.click(screen.getByText("変更準備・承認・実行"));
  await user.type(screen.getByLabelText("変更要求ID"), requestId);
  await user.click(screen.getByRole("button", { name: "保存状態を再取得" }));
  await screen.findByRole("heading", { name: "保存済みSnapshot" });
  return user;
}

it("keeps an effectively expired approval unexecutable without relying on the browser clock", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        ...saved,
        data: {
          ...saved.data,
          status: "APPROVED",
          effective_status: "EXPIRED",
          approval_status: "APPROVED",
        },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  const user = await openSaved();
  expect(document.activeElement).toBe(
    screen.getByRole("heading", { name: "保存済みSnapshot" }),
  );
  await user.click(
    screen.getByLabelText("保存Snapshotと操作内容を確認しました"),
  );
  expect(
    (
      screen.getByRole("button", {
        name: "承認済み変更を実行",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("reads the saved rejection after a deliberate reject and disables further approval", async () => {
  const rejected = {
    ...saved,
    data: {
      ...saved.data,
      status: "REJECTED",
      effective_status: "REJECTED",
      approval_status: "REJECTED",
    },
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(saved)))
    .mockResolvedValueOnce(new Response(JSON.stringify(rejected)))
    .mockResolvedValueOnce(new Response(JSON.stringify(rejected)));
  vi.stubGlobal("fetch", fetcher);
  const user = await openSaved();
  await user.click(
    screen.getByLabelText("保存Snapshotと操作内容を確認しました"),
  );
  await user.click(screen.getByRole("button", { name: "変更要求を拒否" }));
  await screen.findByText(/状態：拒否済み/);
  expect(fetcher.mock.calls[1][0]).toBe(`/api/approvals/${approvalId}/reject`);
  expect(fetcher.mock.calls[1][1].body).toBeUndefined();
  expect(fetcher.mock.calls[2][1].method).toBe("GET");
  expect(
    (
      screen.getByRole("button", {
        name: "Snapshotを承認",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

it("surfaces a server version conflict and requires a fresh Snapshot before further writes", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(saved)))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...saved,
          status: "error",
          errors: [{ code: "VERSION_CONFLICT" }],
        }),
        { status: 409 },
      ),
    );
  vi.stubGlobal("fetch", fetcher);
  const user = await openSaved();
  await user.click(
    screen.getByLabelText("保存Snapshotと操作内容を確認しました"),
  );
  await user.click(screen.getByRole("button", { name: "Snapshotを承認" }));
  const error = await screen.findByRole("alert");
  expect(error.textContent).toContain("VERSION_CONFLICT");
  expect(document.activeElement).toBe(error);
  expect(screen.queryByRole("button", { name: "Snapshotを承認" })).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("preserves confirmed execution when current observation and the follow-up GET fail", async () => {
  const approved = {
    ...saved,
    data: {
      ...saved.data,
      status: "APPROVED",
      effective_status: "APPROVED",
      approval_status: "APPROVED",
    },
  };
  const completed = {
    ...saved,
    status: "partial",
    warnings: [{ code: "DEPENDENCY_UNAVAILABLE" }],
    data: {
      status: "COMPLETED",
      execution_result: { targets: saved.data.canonical_snapshot.targets },
      current_snapshot: null,
      observed_at: null,
    },
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(approved)))
    .mockResolvedValueOnce(new Response(JSON.stringify(completed)))
    .mockRejectedValueOnce(new TypeError("GET unavailable"));
  vi.stubGlobal("fetch", fetcher);
  const user = await openSaved();
  await user.click(
    screen.getByLabelText("保存Snapshotと操作内容を確認しました"),
  );
  await user.click(screen.getByRole("button", { name: "承認済み変更を実行" }));
  await screen.findByRole("alert");
  expect(
    screen.getByRole("heading", { name: "実行応答・実行後の現在値" }),
  ).toBeTruthy();
  expect(
    screen.getByText("DEPENDENCY_UNAVAILABLE", { exact: false }),
  ).toBeTruthy();
  expect(screen.getByText(/確定済み実行を未実行として扱いません/)).toBeTruthy();
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(fetcher.mock.calls[1][0]).toBe(
    `/api/update-requests/${requestId}/execute`,
  );
});

it("opens an explicitly requested saved request and keeps its ID when a read fails", async () => {
  const fetcher = vi
    .fn()
    .mockRejectedValueOnce(new TypeError("network failure"))
    .mockResolvedValue(new Response(JSON.stringify(saved)));
  vi.stubGlobal("fetch", fetcher);
  render(
    <ActionPanel
      initiallyOpen
      actor="owner"
      actorRole="manager"
      requestedOpen={{ id: requestId }}
    />,
  );
  await screen.findByRole("alert");
  expect((screen.getByLabelText("変更要求ID") as HTMLInputElement).value).toBe(
    requestId,
  );
  expect(
    (
      screen.getByRole("button", {
        name: "保存状態を再取得",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "保存状態を再取得" }));
  await screen.findByRole("heading", { name: "保存済みSnapshot" });
  expect(
    screen.getByRole("region", { name: "現在の担当と次の操作" }).textContent,
  ).toContain("この要求の依頼者");
  expect(
    screen.getByRole("region", { name: "現在の担当と次の操作" }).textContent,
  ).toContain("工場管理者");
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(
    fetcher.mock.calls.every(
      ([url, init]) =>
        url === `/api/update-requests/${requestId}` && init.method === "GET",
    ),
  ).toBe(true);
});
