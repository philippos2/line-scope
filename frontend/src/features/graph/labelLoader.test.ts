import { expect, it, vi } from "vitest";
import { createLabelLoader } from "./labelLoader";
it("bounds and deduplicates name reads, retries errors, and drops callbacks after root abort", async () => {
  const controller = new AbortController();
  const nodes = Array.from({ length: 6 }, (_, i) => ({
    entity_type: "Process",
    entity_id: String(i),
  }));
  const pending: {
    resolve: (v: string) => void;
    reject: (e: Error) => void;
  }[] = [];
  const read = vi.fn(
    () =>
      new Promise<string>((resolve, reject) =>
        pending.push({ resolve, reject }),
      ),
  );
  const onResult = vi.fn(),
    onState = vi.fn();
  const loader = createLabelLoader({
    signal: controller.signal,
    read,
    onResult,
    onState,
    errorCode: () => "DEPENDENCY_UNAVAILABLE",
    limit: 5,
    concurrency: 4,
  });
  loader.enqueue([...nodes, nodes[0]]);
  expect(read).toHaveBeenCalledTimes(4);
  expect(onState).toHaveBeenCalledWith(nodes[5], { status: "limited" });
  pending[0].reject(new Error("temporary failure"));
  await vi.waitFor(() => expect(read).toHaveBeenCalledTimes(5));
  expect(onState).toHaveBeenCalledWith(nodes[0], {
    status: "error",
    code: "DEPENDENCY_UNAVAILABLE",
  });
  for (const p of pending.slice(1)) p.resolve("name");
  await vi.waitFor(() => expect(onResult).toHaveBeenCalledTimes(4));
  loader.enqueue(nodes);
  expect(read).toHaveBeenCalledTimes(5);
  loader.retry();
  expect(read).toHaveBeenCalledTimes(6);
  const stateCount = onState.mock.calls.length;
  controller.abort();
  pending[5].resolve("old-root-name");
  await Promise.resolve();
  await Promise.resolve();
  expect(onResult).toHaveBeenCalledTimes(4);
  expect(onState).toHaveBeenCalledTimes(stateCount);
});
