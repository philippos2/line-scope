import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";

type Operation = "read" | "prepare" | "approve" | "reject" | "execute";
export type OperationContext = {
  operation: Operation;
  requestId?: string;
  signal?: AbortSignal;
};
export type OperationAction = (
  signal: AbortSignal,
  confirmed: (requestId: string) => void,
) => Promise<void>;
export type OperationProblem = {
  kind: "unknown" | "failed" | "confirmed-read-failed";
  operation: Operation;
  requestId?: string;
  code: string;
  diagnosticId?: string;
  explanation: string;
};
const explanations: Record<string, string> = {
  AUTHORIZATION_DENIED:
    "この操作の権限がありません。依頼者・承認者と接続中の利用者を確認してください。",
  AUTHENTICATION_REQUIRED: "接続が切れています。接続状態を確認してください。",
  INVALID_ARGUMENT:
    "入力内容を受け付けられません。対象と入力条件を確認してください。",
  INVALID_TOKEN_FORMAT: "接続情報の形式を確認してください。",
  VERSION_CONFLICT:
    "登録内容が変更されています。最新の登録値を確認してください。",
  APPROVAL_EXPIRED: "承認期限を過ぎています。保存状態を確認してください。",
  APPROVAL_INVALIDATED:
    "承認が無効になっています。保存状態と現在の権限を確認してください。",
  INVALID_UPDATE_STATE:
    "現在の要求状態では操作できません。保存状態を確認してください。",
  SNAPSHOT_MISMATCH: "保存内容が一致しません。保存状態を再取得してください。",
  APPROVAL_MISMATCH:
    "承認対象の保存内容が一致しません。保存状態を再取得してください。",
  DUPLICATE_REQUEST:
    "同じ再送キーに異なる内容が指定されています。元の送信内容を確認してください。",
  RESOURCE_NOT_FOUND:
    "指定した対象を取得できません。対象または要求IDを確認してください。",
};
// 明示的な拒否だけを成否判明として扱い、それ以外の書込エラーは安全側に倒す。
function problemFor(
  caught: unknown,
  context: OperationContext,
  confirmed: boolean,
): OperationProblem {
  const aborted =
    caught instanceof DOMException && caught.name === "AbortError";
  const code = aborted
    ? "REQUEST_INTERRUPTED"
    : caught instanceof ApiError
      ? caught.code
      : "REQUEST_FAILED";
  return {
    kind: confirmed
      ? "confirmed-read-failed"
      : context.operation !== "read" && !explanations[code]
        ? "unknown"
        : "failed",
    operation: context.operation,
    requestId: context.requestId,
    code,
    diagnosticId: caught instanceof ApiError ? caught.requestId : undefined,
    explanation:
      explanations[code] ??
      (context.operation === "read"
        ? "保存状態を取得できませんでした。接続を確認して再取得してください。"
        : "サーバの処理結果を確認できませんでした。"),
  };
}

export function useOperationFeedback() {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<OperationProblem | null>(null);
  const mounted = useRef(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    setBusy(false);
    return () => {
      mounted.current = false;
      const controller = active.current;
      active.current = null;
      controller?.abort();
    };
  }, []);
  const isPending = useCallback(() => active.current !== null, []);
  const run = useCallback(
    async (
      action: OperationAction,
      context: OperationContext = { operation: "read" },
    ) => {
      if (!mounted.current || active.current || context.signal?.aborted) return;
      const controller = new AbortController();
      active.current = controller;
      let confirmed = false;
      const state = { ...context };
      const interrupted = () => {
        if (!mounted.current || active.current !== controller) return;
        setProblem(
          problemFor(
            new DOMException("Interrupted", "AbortError"),
            state,
            confirmed,
          ),
        );
        setBusy(false);
        active.current = null;
      };
      const abort = () => controller.abort();
      controller.signal.addEventListener("abort", interrupted, { once: true });
      context.signal?.addEventListener("abort", abort, { once: true });
      setBusy(true);
      setProblem(null);
      try {
        await action(controller.signal, (requestId) => {
          if (controller.signal.aborted) return;
          confirmed = true;
          state.requestId = requestId;
        });
      } catch (caught) {
        if (mounted.current && active.current === controller)
          setProblem(problemFor(caught, state, confirmed));
      } finally {
        context.signal?.removeEventListener("abort", abort);
        controller.signal.removeEventListener("abort", interrupted);
        if (active.current === controller) {
          active.current = null;
          if (mounted.current) setBusy(false);
        }
      }
    },
    [],
  );
  return { busy, problem, run, isPending };
}

export function OperationFeedback({
  problem,
  onRead,
}: {
  problem: OperationProblem | null;
  onRead?: (id: string) => void;
}) {
  const notice = useRef<HTMLElement>(null);
  useEffect(() => {
    if (problem) notice.current?.focus({ preventScroll: true });
  }, [problem]);
  if (!problem) return null;
  const completed = {
    read: "取得",
    prepare: "変更準備の保存",
    approve: "承認",
    reject: "拒否",
    execute: "実行",
  }[problem.operation];
  return (
    <section
      className="operation-completion"
      role="alert"
      aria-label="操作結果の確認"
      ref={notice}
      tabIndex={-1}
    >
      <h3>
        {problem.kind === "unknown"
          ? "処理結果を確認できません"
          : problem.kind === "confirmed-read-failed"
            ? `${completed}は完了しましたが、保存状態を取得できません`
            : problem.operation === "read"
              ? "保存状態を取得できません"
              : "操作を完了できませんでした"}
      </h3>
      {problem.kind === "unknown" ? (
        <p>
          サーバで処理された可能性があります。未作成・未実行とは判断できません。書き込みは自動再送しません。
        </p>
      ) : problem.kind === "failed" ? (
        <p>{problem.explanation}</p>
      ) : (
        <p>
          完了した操作を再実行せず、要求IDから保存状態を再取得してください。
        </p>
      )}
      {problem.requestId ? (
        <>
          <p>
            確認する変更要求ID：<code>{problem.requestId}</code>
          </p>
          {onRead && (
            <button type="button" onClick={() => onRead(problem.requestId!)}>
              この変更要求の保存状態を確認
            </button>
          )}
        </>
      ) : problem.kind === "unknown" ? (
        <p>
          今回の変更要求IDは取得できていません。直近の別の要求を今回の結果とは判断しないでください。送信内容と再送キーはこの画面内で保持しています。接続や対象を切り替える前に結果を確認してください。同じ内容を再送する場合は、表示された操作可否を確認して明示した再送ボタンを使ってください。
        </p>
      ) : null}
      <details>
        <summary>技術情報</summary>
        <code>
          {problem.code}
          {problem.diagnosticId ? ` / ${problem.diagnosticId}` : ""}
        </code>
      </details>
    </section>
  );
}
