import { ApiError } from "../../api/client";
import { explanation } from "../investigation/readModel";

export type ReadProblem = { code: string; requestId?: string };
export function readProblem(error: unknown): ReadProblem {
  return error instanceof ApiError
    ? { code: error.code, requestId: error.requestId }
    : { code: "REQUEST_FAILED" };
}
export function ReadFeedback({
  problem,
  operation,
  onRetry,
}: {
  problem: ReadProblem | null;
  operation: string;
  onRetry?: () => void;
}) {
  if (!problem) return null;
  return (
    <div className="read-failure" role="alert">
      <p>
        {operation}を完了できませんでした。
        {problem.code === "DEPENDENCY_UNAVAILABLE"
          ? "参照先のサービスを利用できません。再試行しても続く場合は管理者へ連絡してください。"
          : explanation(problem.code)}
      </p>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          {operation}を再試行
        </button>
      )}
      <details>
        <summary>技術情報：取得失敗</summary>
        <p>{problem.code}</p>
        {problem.requestId && <p>診断用リクエストID：{problem.requestId}</p>}
      </details>
    </div>
  );
}
