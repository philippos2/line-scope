import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import { ApiError } from "../../api/client";
import { OperationFeedback, useOperationFeedback } from "./OperationFeedback";
afterEach(cleanup);

it("distinguishes an unknown Prepare from failure and never resends automatically", async () => {
  const { result } = renderHook(useOperationFeedback);
  const send = vi.fn().mockRejectedValue(new ApiError("CONNECTION_FAILED"));
  await act(() => result.current.run(send, { operation: "prepare" }));
  expect(send).toHaveBeenCalledTimes(1);
  expect(result.current.busy).toBe(false);
  expect(result.current.problem?.kind).toBe("unknown");
  render(<OperationFeedback problem={result.current.problem} />);
  expect(screen.getByText(/直近の別の要求/)).toBeTruthy();
  expect(screen.getByText(/書き込みは自動再送しません/)).toBeTruthy();
});
it("treats explicit authorization refusal as failure instead of an unknown write", async () => {
  const { result } = renderHook(useOperationFeedback);
  await act(() =>
    result.current.run(
      async () => {
        throw new ApiError("AUTHORIZATION_DENIED");
      },
      { operation: "approve", requestId: "saved" },
    ),
  );
  expect(result.current.problem?.kind).toBe("failed");
  expect(result.current.problem?.requestId).toBe("saved");
  render(<OperationFeedback problem={result.current.problem} />);
  expect(screen.getByText(/この操作の権限がありません/)).toBeTruthy();
});
it("keeps a confirmed operation separate from the following failed GET", async () => {
  const { result } = renderHook(useOperationFeedback);
  await act(() =>
    result.current.run(
      async (_signal, confirmed) => {
        confirmed("saved");
        throw new ApiError("CONNECTION_FAILED");
      },
      { operation: "approve" },
    ),
  );
  expect(result.current.problem?.kind).toBe("confirmed-read-failed");
  expect(result.current.problem?.requestId).toBe("saved");
  const read = vi.fn();
  render(<OperationFeedback problem={result.current.problem} onRead={read} />);
  expect(screen.getByRole("heading").textContent).toContain(
    "承認は完了しました",
  );
  act(() => screen.getByRole("button").click());
  expect(read).toHaveBeenCalledWith("saved");
});
it("releases busy on interruption in a mounted screen and ignores a late response", async () => {
  const { result } = renderHook(useOperationFeedback);
  const controller = new AbortController();
  let finish!: () => void;
  const received = vi.fn();
  let running!: Promise<void>;
  act(() => {
    running = result.current.run(
      async (signal) => {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        if (!signal.aborted) received();
      },
      { operation: "prepare", signal: controller.signal },
    );
  });
  expect(result.current.busy).toBe(true);
  act(() => controller.abort());
  expect(result.current.busy).toBe(false);
  expect(result.current.problem?.kind).toBe("unknown");
  await act(async () => {
    finish();
    await running;
  });
  expect(received).not.toHaveBeenCalled();
  expect(result.current.problem?.kind).toBe("unknown");
});
it("aborts on unmount without reporting a late success", async () => {
  const { result, unmount } = renderHook(useOperationFeedback);
  let finish!: () => void;
  let signal!: AbortSignal;
  const received = vi.fn();
  let running!: Promise<void>;
  act(() => {
    running = result.current.run(
      async (active) => {
        signal = active;
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        if (!active.aborted) received();
      },
      { operation: "execute", requestId: "saved" },
    );
  });
  unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => {
    finish();
    await running;
  });
  expect(received).not.toHaveBeenCalled();
});
it("keeps failed reads distinct from uncertain writes and preserves the requested ID", async () => {
  const { result } = renderHook(useOperationFeedback);
  await act(() =>
    result.current.run(
      async () => {
        throw new ApiError("CONNECTION_FAILED");
      },
      { operation: "read", requestId: "saved" },
    ),
  );
  expect(result.current.problem?.kind).toBe("failed");
  expect(result.current.problem?.requestId).toBe("saved");
  expect(result.current.isPending()).toBe(false);
});
