import { registeredState } from "../investigation/readModel";
import { ComparisonInputDetails } from "../decision/ComparisonInputDetails";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ApiError, object, request, type Envelope } from "../../api/client";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const text = (value: unknown) => (typeof value === "string" ? value : "未確認");

export function ActionPanel({
  preparedId,
  requestedOpen,
  initialMessage = "",
  onExecution,
  onSaved,
  initiallyOpen = false,
  actor = "",
  names = {},
}: {
  requestedOpen?: { id: string } | null;
  actor?: string;
  names?: Record<string, string>;
  initialMessage?: string;
  preparedId?: string;
  onExecution?: () => void;
  onSaved?: (value: Envelope | null) => void;
  initiallyOpen?: boolean;
}) {
  const [message, setMessage] = useState(initialMessage);
  const [preparedMessage, setPreparedMessage] = useState("");
  const [id, setId] = useState("");
  const [saved, setSaved] = useState<Envelope | null>(null);
  const [execution, setExecution] = useState<Envelope | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [diagnostic, setDiagnostic] = useState("");
  const [copied, setCopied] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const retry = useRef<{ message: string; key: string } | null>(null);
  const pending = useRef(false);
  const handledOpen = useRef<typeof requestedOpen>(null);
  const snapshotHeading = useRef<HTMLHeadingElement>(null);
  const errorMessage = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (saved) snapshotHeading.current?.focus();
    else if (error) errorMessage.current?.focus();
  }, [saved, error]);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    setMessage(initialMessage);
  }, [initialMessage]);
  useEffect(() => {
    onSaved?.(saved);
  }, [saved, onSaved]);

  const run = useCallback(
    async (action: (signal: AbortSignal) => Promise<void>) => {
      if (pending.current) return;
      pending.current = true;
      const active = new AbortController();
      controller.current = active;
      setBusy(true);
      setError("");
      setDiagnostic("");
      setChecked(false);
      try {
        await action(active.signal);
      } catch (caught) {
        if (!active.signal.aborted) {
          setSaved(null);
          const code =
            caught instanceof ApiError ? caught.code : "REQUEST_FAILED";
          const explanation =
            (
              {
                AUTHORIZATION_DENIED:
                  "この操作の権限がありません。依頼者・承認者と接続中の利用者を確認してください。",
                AUTHENTICATION_REQUIRED:
                  "接続が切れました。接続し直してください。",
                VERSION_CONFLICT:
                  "登録内容が変更されています。最新の登録値を取得し、変更準備を作り直してください。",
                APPROVAL_EXPIRED:
                  "承認期限を過ぎています。変更準備からやり直してください。",
                SNAPSHOT_MISMATCH:
                  "保存内容が一致しません。保存状態を再取得して確認してください。",
                CONNECTION_FAILED:
                  "応答を確認できませんでした。処理が確定している可能性があります。",
                DEPENDENCY_UNAVAILABLE:
                  "接続先サービスを利用できません。接続設定を確認してください。",
              } as Record<string, string>
            )[code] ??
            "処理を完了できませんでした。保存状態を再取得して確認してください。";
          setDiagnostic(
            code +
              (caught instanceof ApiError && caught.requestId
                ? ` / ${caught.requestId}`
                : ""),
          );
          setError(
            `${explanation} 要求IDが分かる場合は保存状態を再取得してください。Prepare応答が不明な場合は同じ指示のまま再送できます。書き込みは自動再送しません。`,
          );
        }
      } finally {
        if (!active.signal.aborted) setBusy(false);
        pending.current = false;
      }
    },
    [],
  );
  const load = useCallback(async (requestId: string, signal: AbortSignal) => {
    setSaved(null);
    const value = await request(
      "",
      `/update-requests/${encodeURIComponent(requestId)}`,
      undefined,
      signal,
    );
    if (!signal.aborted) setSaved(value);
  }, []);
  const open = useCallback(
    (requestId: string) => {
      if (!uuid.test(requestId)) return;
      setId(requestId);
      setCopied(false);
      setExecution(null);
      void run((signal) => load(requestId, signal));
    },
    [run, load],
  );
  useEffect(() => {
    if (
      !requestedOpen ||
      handledOpen.current === requestedOpen ||
      pending.current
    )
      return;
    handledOpen.current = requestedOpen;
    open(requestedOpen.id);
  }, [requestedOpen, open, busy]);
  const alreadyPrepared =
    Boolean(message.trim()) && preparedMessage === message.trim();
  function prepare(event: FormEvent) {
    event.preventDefault();
    const command = message.trim();
    if (!command || pending.current || alreadyPrepared) return;
    if (retry.current?.message !== command)
      retry.current = { message: command, key: crypto.randomUUID() };
    setId("");
    setSaved(null);
    setExecution(null);
    void run(async (signal) => {
      const value = await request(
        "",
        "/agent",
        { message: command },
        signal,
        retry.current!.key,
      );
      if (signal.aborted) return;
      const requestId = value.data.update_request_id;
      if (typeof requestId !== "string" || !uuid.test(requestId)) {
        setError(
          value.answer ??
            "変更準備は作成されていません。対象と変更内容を明示してください。",
        );
        return;
      }
      setId(requestId);
      setPreparedMessage(command);
      await load(requestId, signal);
    });
  }
  const data = saved?.data;
  const snapshot =
    data && object(data.canonical_snapshot) ? data.canonical_snapshot : null;
  const targets =
    snapshot && Array.isArray(snapshot.targets)
      ? snapshot.targets.filter(object)
      : [];
  const requestId = data ? text(data.update_request_id) : "";
  const approvalId = data ? text(data.approval_id) : "";
  const valid =
    snapshot !== null &&
    targets.length > 0 &&
    uuid.test(requestId) &&
    uuid.test(approvalId) &&
    typeof data?.snapshot_hash === "string" &&
    /^[0-9a-f]{64}$/.test(data.snapshot_hash);
  const pendingApproval =
    data?.status === "WAITING_APPROVAL" && data.approval_status === "PENDING";
  const approved =
    data?.effective_status === "APPROVED" &&
    data.approval_status === "APPROVED";
  const requester =
    typeof snapshot?.requester_id === "string" ? snapshot.requester_id : "";
  const inputCategory = targets.some((target) =>
    [
      "EconomicInput",
      "CapacityInput",
      "SafetyInput",
      "MaintenanceInput",
    ].includes(String(target.target_type)),
  );
  const ownRestrictedRequest = Boolean(
    actor && actor === requester && inputCategory,
  );
  const otherRequester = Boolean(actor && requester && actor !== requester);
  const approvalReason = busy
    ? "処理が終わるまでお待ちください。"
    : !valid
      ? "保存状態を再取得してください。"
      : !pendingApproval
        ? "この要求は承認待ちではありません。保存状態を確認してください。"
        : ownRestrictedRequest
          ? "この入力の依頼者は承認できません。別の工場管理者で接続してください。"
          : !checked
            ? "保存内容と操作内容を確認し、確認欄にチェックしてください。"
            : "サーバが操作権限を確認して承認します。";
  const executeReason = busy
    ? "処理が終わるまでお待ちください。"
    : !valid
      ? "保存状態を再取得してください。"
      : !approved
        ? "実行には有効な承認が必要です。承認後に保存状態を再取得してください。"
        : otherRequester
          ? "実行できるのは元の依頼者です。依頼者で接続し直してください。"
          : !checked
            ? "承認された保存内容を確認し、確認欄にチェックしてください。"
            : "元の依頼者として実行します。サーバが期限・権限・版を再確認します。";
  const stateName = (value: unknown) =>
    ({
      WAITING_APPROVAL: "承認待ち",
      APPROVED: "承認済み",
      COMPLETED: "実行済み",
      EXPIRED: "期限切れ",
      REJECTED: "拒否済み",
      INVALIDATED: "無効",
      SUPERSEDED: "置換済み",
      FAILED: "実行失敗",
      PENDING: "承認待ち",
      CONSUMED: "承認使用済み",
    })[String(value)] ?? "状態を確認できません";
  function mutate(operation: "approve" | "reject" | "execute") {
    if (
      !valid ||
      !checked ||
      (operation === "execute"
        ? otherRequester || !approved
        : ownRestrictedRequest || !pendingApproval)
    )
      return;
    const hash = data!.snapshot_hash;
    setSaved(null);
    setExecution(null);
    if (operation === "execute") onExecution?.();
    void run(async (signal) => {
      const value =
        operation === "execute"
          ? await request(
              "",
              `/update-requests/${requestId}/execute`,
              undefined,
              signal,
              undefined,
              "POST",
            )
          : await request(
              "",
              `/approvals/${approvalId}/${operation}`,
              operation === "approve" ? { snapshot_hash: hash } : undefined,
              signal,
              undefined,
              "POST",
            );
      if (signal.aborted) return;
      if (operation === "execute") setExecution(value);
      await load(requestId, signal);
    });
  }
  return (
    <details className="action-panel" open={initiallyOpen || undefined}>
      <summary>変更準備・承認・実行</summary>
      <p>
        分析・変更準備・承認・実行は別操作です。操作権限と承認期限はサーバが判定します。
      </p>
      <form onSubmit={prepare}>
        <label htmlFor="action-message">明示的な変更指示</label>
        <textarea
          id="action-message"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          disabled={busy}
          placeholder="例：M-204の現在状態をRUNNINGに変更する準備を作って"
        />
        <button
          disabled={busy || !message.trim() || alreadyPrepared}
          aria-describedby="action-prepare-reason"
        >
          {alreadyPrepared ? "変更準備を作成済み" : "変更指示から準備を作成"}
        </button>
        <p id="action-prepare-reason" role="status">
          {busy
            ? "処理が完了するまで操作できません。"
            : alreadyPrepared
              ? "この指示の変更準備は作成済みです。保存内容と承認状態を確認してください。"
              : !message.trim()
                ? "変更準備には対象と変更内容の入力が必要です。"
                : "変更準備だけでは登録値は変わりません。"}
        </p>
      </form>
      {!message.trim() && (
        <p className="notice">
          変更準備には、対象と変更内容を入力するか、上の登録状態から下書きを作ってください。
        </p>
      )}
      <p className="muted">
        Prepareでは業務値を変更しません。同じ指示の再送には同じ再送キーを使用します。
      </p>
      {preparedId && uuid.test(preparedId) && (
        <button disabled={busy} onClick={() => open(preparedId)}>
          直近の変更要求を開く
        </button>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          open(id.trim());
        }}
      >
        <label htmlFor="action-id">変更要求ID</label>
        <input
          id="action-id"
          value={id}
          disabled={busy}
          onChange={(event) => {
            setId(event.target.value);
            setSaved(null);
            setExecution(null);
            setChecked(false);
          }}
        />
        <button
          disabled={busy || !uuid.test(id.trim())}
          aria-describedby="saved-request-reason"
        >
          保存状態を再取得
        </button>
      </form>
      {(busy || !uuid.test(id.trim())) && (
        <p className="notice" id="saved-request-reason">
          {busy
            ? "処理中のため、保存状態の再取得はできません。"
            : !id.trim()
              ? "変更要求IDが空のため、保存状態を取得できません。IDを入力するか、直近の変更要求を開いてください。設備の選択は不要です。"
              : "変更要求IDの形式を確認してください。有効なIDを入力すると保存状態を取得できます。"}
        </p>
      )}
      <p className="muted">
        承認者には変更要求IDを渡してください。上部の接続設定で接続解除し、別の承認者で接続してIDから読み直します。実行時は元requesterで接続し直してください。
      </p>
      {busy && <p role="status">サーバへ確認中…</p>}
      {error && (
        <div role="alert" ref={errorMessage} tabIndex={-1}>
          <p>{error}</p>
          {diagnostic && (
            <details>
              <summary>技術情報</summary>
              <code>{diagnostic}</code>
            </details>
          )}
        </div>
      )}
      {data && (
        <section>
          <h2 ref={snapshotHeading} tabIndex={-1}>
            保存済みSnapshot
          </h2>
          <p>変更要求ID：{requestId}</p>
          <button
            type="button"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(requestId);
                setCopied(true);
              } catch {
                setError(
                  "コピーできませんでした。上の変更要求IDを選択してコピーしてください。",
                );
              }
            }}
          >
            {copied
              ? "変更要求IDをコピーしました"
              : "承認者へ渡す変更要求IDをコピー"}
          </button>
          <p>
            状態：{stateName(data.effective_status ?? data.status)} / 承認：
            {stateName(data.approval_status)}
          </p>
          <p>
            依頼者：{requester || "取得できません"}
            {actor === requester ? "（接続中の利用者）" : ""}
          </p>
          <p>
            承認日時：{text(data.approved_at)} / 承認期限：
            {text(data.expires_at)}
          </p>

          {targets.map((target, index) => (
            <section key={index} className="evidence-card">
              <h3>
                変更対象 {index + 1}：
                {names[
                  String(
                    object(target.business_key)
                      ? target.business_key.equipment_id
                      : "",
                  )
                ] ?? (inputCategory ? "登録入力" : "設備・運用データ")}
              </h3>
              {(
                [
                  ["before", "変更前"],
                  ["after", "変更予定"],
                ] as const
              ).map(([key, title]) => {
                const value = object(target[key]) ? target[key] : null;
                return (
                  <section key={key}>
                    <h4>{title}</h4>
                    {!value ? (
                      <p>新規登録（変更前の登録なし）</p>
                    ) : object(value.payload) ? (
                      <ComparisonInputDetails record={value} names={names} />
                    ) : (
                      <p>
                        {typeof value.state_code === "string"
                          ? `登録状態：${registeredState(value.state_code)}`
                          : "詳細は保存内容の技術情報で確認してください。"}
                        {typeof value.version === "number"
                          ? ` ／ 第${value.version}版`
                          : ""}
                      </p>
                    )}
                  </section>
                );
              })}
            </section>
          ))}
          <details>
            <summary>技術情報：保存内容の原文</summary>
            <pre>{JSON.stringify(snapshot, null, 2)}</pre>
          </details>
          <label>
            <input
              type="checkbox"
              checked={checked}
              disabled={busy}
              onChange={(event) => setChecked(event.target.checked)}
            />
            保存Snapshotと操作内容を確認しました
          </label>
          <div className="presets">
            <button
              disabled={
                busy ||
                !checked ||
                !valid ||
                !pendingApproval ||
                ownRestrictedRequest
              }
              aria-describedby="approval-reason"
              onClick={() => mutate("approve")}
            >
              Snapshotを承認
            </button>
            <button
              disabled={
                busy ||
                !checked ||
                !valid ||
                !pendingApproval ||
                ownRestrictedRequest
              }
              aria-describedby="approval-reason"
              onClick={() => mutate("reject")}
            >
              変更要求を拒否
            </button>
            <button
              disabled={
                busy || !checked || !valid || !approved || otherRequester
              }
              aria-describedby="execute-reason"
              onClick={() => mutate("execute")}
            >
              承認済み変更を実行
            </button>
          </div>
          <p id="approval-reason">承認・拒否：{approvalReason}</p>
          <p id="execute-reason">実行：{executeReason}</p>
          {data.execution_result != null && (
            <section>
              <h3>保存された確定結果（after）</h3>
              <pre>{JSON.stringify(data.execution_result, null, 2)}</pre>
            </section>
          )}
        </section>
      )}
      {execution && (
        <section>
          <h2>実行応答・実行後の現在値</h2>
          <p>
            確定afterと現在観測は別です。現在値を取得できなくても、確定済み実行を未実行として扱いません。
          </p>
          <h3>現在値（current）・観測時刻</h3>
          <p>観測日時：{text(execution.data.observed_at)}</p>
          <pre>
            {JSON.stringify(execution.data.current_snapshot ?? null, null, 2)}
          </pre>
          <details>
            <summary>実行応答全文</summary>
            <pre>{JSON.stringify(execution.data, null, 2)}</pre>
          </details>
          {execution.warnings.length > 0 && (
            <pre>{JSON.stringify(execution.warnings, null, 2)}</pre>
          )}
        </section>
      )}
    </details>
  );
}
