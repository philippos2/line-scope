import { useRef, useState, type FormEvent } from "react";
import { ApiError, object, request, type Envelope } from "../api/client";
import { DecisionComparison } from "../features/decision/DecisionComparison";
import { EvidencePanel } from "../features/evidence/EvidencePanel";
import { GraphCanvas } from "../features/graph/GraphCanvas";
import {
  detail,
  graphView,
  label,
  nodeKey,
  type NodeRef,
} from "../features/graph/model";
export function App() {
  const [draftToken, setDraftToken] = useState("");
  const token = useRef("");
  const retry = useRef<{ body: string; key: string } | null>(null);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<Envelope | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<NodeRef | null>(null);
  const [tab, setTab] = useState<
    "impact" | "comparison" | "evidence" | "trace"
  >("impact");
  const [stale, setStale] = useState(false);
  const current = useRef(0);
  const abort = useRef<AbortController | null>(null);
  function disconnect() {
    current.current++;
    abort.current?.abort();
    token.current = "";
    retry.current = null;
    setDraftToken("");
    setConnected(false);
    setBusy(false);
    setResult(null);
    setSelected(null);
    setMessage("");
    setError("");
    setStale(false);
  }
  async function perform(
    action: () => Promise<Envelope>,
    onSuccess: (value: Envelope) => void,
  ) {
    const id = ++current.current;
    abort.current?.abort();
    abort.current = new AbortController();
    setBusy(true);
    setError("");
    try {
      const value = await action();
      if (id === current.current) onSuccess(value);
    } catch (caught) {
      if (id === current.current)
        setError(
          caught instanceof ApiError
            ? `${caught.code === "INVALID_TOKEN_FORMAT" ? "tokenの形式が不正です。tokenファイルの値だけを貼り付けてください。" : caught.code === "CONNECTION_FAILED" ? "APIへ接続できません。ブラウザの通信制限や接続先を確認してください。" : caught.code}${caught.requestId ? " / " + caught.requestId : ""}`
            : "REQUEST_FAILED",
        );
    } finally {
      if (id === current.current) setBusy(false);
    }
  }
  async function connect(event: FormEvent) {
    event.preventDefault();
    const value = draftToken.trim();
    if (!value) return;
    await perform(
      () => request(value, "/health/ready", undefined, abort.current?.signal),
      () => {
        token.current = value;
        setDraftToken("");
        setConnected(true);
      },
    );
  }
  async function investigate(event: FormEvent) {
    event.preventDefault();
    if (!connected || !message.trim()) return;
    setStale(true);
    const body = {
      message,
      ...(result?.context_id ? { context_id: result.context_id } : {}),
    };
    const serialized = JSON.stringify(body);
    if (retry.current?.body !== serialized)
      retry.current = { body: serialized, key: crypto.randomUUID() };
    await perform(
      () =>
        request(
          token.current,
          "/agent",
          body,
          abort.current?.signal,
          retry.current!.key,
        ),
      (value) => {
        setResult(value);
        setSelected(null);
        setStale(false);
      },
    );
  }
  const view = result ? graphView(result) : null;
  const pkg =
    result && object(result.data.decision_package)
      ? result.data.decision_package
      : null;
  return (
    <>
      <header>
        <div>
          <strong>LineScope</strong>
          <span className="muted">製造オペレーション / 調査ワークスペース</span>
        </div>
        <span className="badge">
          {connected ? "PostgreSQL 確認済み" : "未接続"}
        </span>
      </header>
      {!connected ? (
        <main className="connect">
          <h1>業務データへ接続</h1>
          <p className="muted">
            サーバに登録されたBearer
            tokenで認証します。権限はサーバが判定します。
          </p>
          <form onSubmit={connect}>
            <label htmlFor="token">Bearer token</label>
            <input
              id="token"
              type="password"
              value={draftToken}
              onChange={(e) => setDraftToken(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            <button disabled={busy || !draftToken.trim()}>
              {busy ? "確認中…" : "接続する"}
            </button>
          </form>
          <p className="muted">
            tokenはメモリだけに保持し、接続解除で消去します。
          </p>
          <p role="alert">{error}</p>
        </main>
      ) : (
        <div className="layout">
          <aside>
            <div className="section-label">今回取得したOBJECT</div>
            {view?.nodes.map((item) => (
              <button
                className="object"
                key={nodeKey(item)}
                onClick={() => setSelected(item)}
                aria-pressed={
                  selected !== null && nodeKey(selected) === nodeKey(item)
                }
              >
                <strong>{label(result!, item)}</strong>
                <small>{item.entity_type}</small>
              </button>
            ))}
            {!view && <p className="muted">分析後に取得対象を表示します。</p>}
            <button onClick={disconnect}>接続解除</button>
            {selected && result && (
              <section>
                <h2>Object詳細</h2>
                <pre>{JSON.stringify(detail(result, selected), null, 2)}</pre>
              </section>
            )}
          </aside>
          <main className="workspace">
            <div className="title">
              <h1>影響と根拠を調べる</h1>
              {result && (
                <span
                  className={`badge ${result.status === "partial" ? "warning" : ""}`}
                >
                  {result.status === "partial"
                    ? "PARTIAL / 部分結果"
                    : "取得済み結果"}
                </span>
              )}
            </div>
            {pkg && (
              <p className="notice">
                MOCK_FIXTUREを含む比較デモ。費用・能力・安全条件は仮置きです。
              </p>
            )}
            {stale && result && (
              <p className="notice">
                前回の結果です。新しい調査の完了は未確認です。
              </p>
            )}
            {view && (
              <div className="metrics">
                <div>
                  Graph同期（取得時）
                  <strong>
                    {typeof view.data.graph_sync_state === "string"
                      ? view.data.graph_sync_state
                      : "未確認"}
                  </strong>
                </div>
                <div>
                  探索
                  <strong>
                    {view.data.complete === true
                      ? "探索範囲を確認済み"
                      : "不完全 / 未確認"}
                  </strong>
                </div>
                <div>
                  描画対象
                  <strong>
                    {view.nodes.length}件{view.limited ? " / 表示制限あり" : ""}
                  </strong>
                </div>
              </div>
            )}
            <nav className="tabs" aria-label="結果表示">
              {(["impact", "comparison", "evidence", "trace"] as const).map(
                (key) => (
                  <button
                    key={key}
                    aria-pressed={tab === key}
                    onClick={() => setTab(key)}
                  >
                    {key === "impact"
                      ? "影響・経路"
                      : key === "comparison"
                        ? "対応案の比較"
                        : key === "evidence"
                          ? "Evidence"
                          : "公開Tool Trace"}
                  </button>
                ),
              )}
            </nav>
            {!result ? (
              <div className="empty">
                <h2>問い合わせから調査を始める</h2>
                <p>取得した依存関係、回答、根拠を同じ画面で確認します。</p>
                <p className="muted">
                  Graph / RAG / モデルの準備状態は未確認です。
                </p>
              </div>
            ) : tab === "comparison" ? (
              pkg && object(pkg.comparison) ? (
                <DecisionComparison comparison={pkg.comparison} />
              ) : (
                <p className="muted">
                  この応答に比較結果はありません。比較デモを問い合わせると、取得した対応案を表示します。
                </p>
              )
            ) : tab === "impact" ? (
              view ? (
                <>
                  <GraphCanvas
                    view={view}
                    result={result}
                    selected={selected ? nodeKey(selected) : null}
                    onSelect={setSelected}
                  />
                  <p className="notice">
                    依存関係の到達です。実際の停止・能力・安全性・経済影響を保証しません。
                  </p>
                  {Boolean(view.data.limit_reason) && (
                    <p>探索制限：{String(view.data.limit_reason)}</p>
                  )}
                </>
              ) : (
                <p className="muted">
                  この応答に下流Graph結果はありません。回答とEvidenceを確認してください。
                </p>
              )
            ) : tab === "evidence" ? (
              <EvidencePanel result={result} />
            ) : (
              <section>
                <h2>公開Tool Trace</h2>
                <pre>
                  {JSON.stringify(result.data.tool_trace ?? [], null, 2)}
                </pre>
              </section>
            )}
            {result?.warnings.length !== undefined &&
              result.warnings.length > 0 && (
                <details>
                  <summary>注意事項</summary>
                  <pre>{JSON.stringify(result.warnings, null, 2)}</pre>
                </details>
              )}
            {result && <p className="muted">request_id: {result.request_id}</p>}
          </main>
          <aside className="agent">
            <div className="section-label">INVESTIGATOR</div>
            <form onSubmit={investigate}>
              <label htmlFor="message">問い合わせ</label>
              <textarea
                id="message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={5}
              />
              <div className="presets">
                <button
                  type="button"
                  onClick={() =>
                    setMessage(
                      "M-204が停止した場合の下流の影響対象と経路を調べて",
                    )
                  }
                >
                  下流影響を調べる
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setMessage(
                      "M-204の異常について影響・修理・交換・代替を比較して",
                    )
                  }
                >
                  比較デモ
                </button>
              </div>
              <button className="primary" disabled={busy || !message.trim()}>
                {busy ? "調査中…" : "問い合わせを送信"}
              </button>
            </form>
            <p className="muted">
              比較デモは仮置き条件を使用します。明示的な更新依頼は変更準備を作成し得ます。承認・実行は別の操作です。
            </p>
            <p role="alert">{error}</p>
            {result && (
              <section className="answer">
                <h2>回答</h2>
                <p>
                  {result.answer ??
                    "回答文はありません。構造化結果を確認してください。"}
                </p>
              </section>
            )}
            {result && (
              <details>
                <summary>構造化結果</summary>
                <pre>{JSON.stringify(result.data, null, 2)}</pre>
              </details>
            )}
          </aside>
        </div>
      )}
    </>
  );
}
