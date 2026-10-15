import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, object, request, type Envelope } from "../../api/client";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const text = (value: unknown) => (typeof value === "string" ? value : "未確認");

export function ActionPanel({
  preparedId,
  onExecution,
}: {
  preparedId?: string;
  onExecution?: () => void;
}) {
  const [message, setMessage] = useState("");
  const [id, setId] = useState("");
  const [saved, setSaved] = useState<Envelope | null>(null);
  const [execution, setExecution] = useState<Envelope | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const retry = useRef<{ message: string; key: string } | null>(null);
  const pending = useRef(false);
  const snapshotHeading = useRef<HTMLHeadingElement>(null);
  const errorMessage = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (saved) snapshotHeading.current?.focus();
    else if (error) errorMessage.current?.focus();
  }, [saved, error]);
  useEffect(() => () => controller.current?.abort(), []);

  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (pending.current) return;
    pending.current = true;
    const active = new AbortController();
    controller.current = active;
    setBusy(true);
    setError("");
    setChecked(false);
    try {
      await action(active.signal);
    } catch (caught) {
      if (!active.signal.aborted) {
        setSaved(null);
        setError(
          `${caught instanceof ApiError ? caught.code + (caught.requestId ? " / " + caught.requestId : "") : "REQUEST_FAILED"}。要求IDが分かる場合は保存状態を再取得してください。Prepare応答が不明な場合は同じ指示のまま再送できます。書き込みは自動再送しません。`,
        );
      }
    } finally {
      if (!active.signal.aborted) setBusy(false);
      pending.current = false;
    }
  }
  async function load(requestId: string, signal: AbortSignal) {
    setSaved(null);
    const value = await request(
      "",
      `/update-requests/${encodeURIComponent(requestId)}`,
      undefined,
      signal,
    );
    if (!signal.aborted) setSaved(value);
  }
  function open(requestId: string) {
    if (!uuid.test(requestId)) return;
    setId(requestId);
    setExecution(null);
    void run((signal) => load(requestId, signal));
  }
  function prepare(event: FormEvent) {
    event.preventDefault();
    const command = message.trim();
    if (!command) return;
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
  function mutate(operation: "approve" | "reject" | "execute") {
    if (!valid || !checked) return;
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
    <details className="action-panel">
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
        <button disabled={busy || !message.trim()}>変更準備を作成</button>
      </form>
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
        <button disabled={busy || !uuid.test(id.trim())}>
          保存状態を再取得
        </button>
      </form>
      <p className="muted">
        承認者には変更要求IDを渡してください。上部の接続設定で接続解除し、別の承認者で接続してIDから読み直します。実行時は元requesterで接続し直してください。
      </p>
      {busy && <p role="status">サーバへ確認中…</p>}
      {error && (
        <p role="alert" ref={errorMessage} tabIndex={-1}>
          {error}
        </p>
      )}
      {data && (
        <section>
          <h2 ref={snapshotHeading} tabIndex={-1}>
            保存済みSnapshot
          </h2>
          <p>変更要求ID：{requestId}</p>
          <p>
            状態：{text(data.status)} / 実効状態：{text(data.effective_status)}{" "}
            / 承認：{text(data.approval_status)}
          </p>
          <p>requester：{text(snapshot?.requester_id)}</p>
          <p>
            承認日時：{text(data.approved_at)} / 承認期限：
            {text(data.expires_at)}
          </p>
          <p className="muted">Snapshot hash：{text(data.snapshot_hash)}</p>
          {targets.map((target, index) => (
            <section key={index} className="evidence-card">
              <h3>
                {text(target.target_type)} / {text(target.target_id)} /{" "}
                {text(target.operation_type)}
              </h3>
              <h4>変更前（before）</h4>
              <pre>{JSON.stringify(target.before, null, 2)}</pre>
              <h4>変更予定（proposed）</h4>
              <pre>{JSON.stringify(target.after, null, 2)}</pre>
            </section>
          ))}
          <details>
            <summary>canonical Snapshot全文</summary>
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
              disabled={busy || !checked || !valid || !pendingApproval}
              onClick={() => mutate("approve")}
            >
              Snapshotを承認
            </button>
            <button
              disabled={busy || !checked || !valid || !pendingApproval}
              onClick={() => mutate("reject")}
            >
              変更要求を拒否
            </button>
            <button
              disabled={busy || !checked || !valid || !approved}
              onClick={() => mutate("execute")}
            >
              承認済み変更を実行
            </button>
          </div>
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
