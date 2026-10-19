import { nodeKey, type NodeRef } from "./model";

export type NodeLabelState = {
  status: "loading" | "ready" | "error" | "limited";
  code?: string;
};
export type NodeLabelStates = Record<string, NodeLabelState>;
export const MAX_LABEL_NODES = 100;
export const LABEL_CONCURRENCY = 4;

// Per-investigation queue: no request or callback survives its root AbortSignal.
export function createLabelLoader<T>({
  signal,
  read,
  onResult,
  onState,
  errorCode,
  limit = MAX_LABEL_NODES,
  concurrency = LABEL_CONCURRENCY,
}: {
  signal: AbortSignal;
  read: (node: NodeRef, signal: AbortSignal) => Promise<T>;
  onResult: (node: NodeRef, result: T) => void;
  onState: (node: NodeRef, state: NodeLabelState) => void;
  errorCode: (error: unknown) => string;
  limit?: number;
  concurrency?: number;
}) {
  const tracked = new Map<string, { node: NodeRef; state: NodeLabelState }>();
  const pending: NodeRef[] = [];
  let active = 0,
    admitted = 0;
  function state(node: NodeRef, value: NodeLabelState) {
    if (signal.aborted) return;
    tracked.set(nodeKey(node), { node, state: value });
    onState(node, value);
  }
  function pump() {
    while (!signal.aborted && active < concurrency && pending.length) {
      const node = pending.shift()!;
      active++;
      void read(node, signal)
        .then((result) => {
          if (signal.aborted) return;
          onResult(node, result);
          state(node, { status: "ready" });
        })
        .catch((error) =>
          state(node, { status: "error", code: errorCode(error) }),
        )
        .finally(() => {
          active--;
          pump();
        });
    }
  }
  function enqueue(nodes: NodeRef[]) {
    if (signal.aborted) return;
    for (const node of nodes) {
      if (tracked.has(nodeKey(node))) continue;
      if (admitted >= limit) {
        state(node, { status: "limited" });
        continue;
      }
      admitted++;
      state(node, { status: "loading" });
      pending.push(node);
    }
    pump();
  }
  function retry() {
    if (signal.aborted) return;
    for (const { node, state: previous } of [...tracked.values()]) {
      if (previous.status !== "error") continue;
      state(node, { status: "loading" });
      pending.push(node);
    }
    pump();
  }
  return { enqueue, retry };
}
