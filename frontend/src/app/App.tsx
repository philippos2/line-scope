import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, object, request, type Envelope } from "../api/client";
import { ActionPanel } from "../features/actions/ActionPanel";
import { MaintenancePanel } from "../features/maintenance/MaintenancePanel";
import { MaintenanceResult } from "../features/maintenance/MaintenanceResult";
import { SafetyPanel } from "../features/safety/SafetyPanel";
import { SafetyResult } from "../features/safety/SafetyResult";
import { CapacityPanel } from "../features/capacity/CapacityPanel";
import { CapacityResult } from "../features/capacity/CapacityResult";
import { EconomicPanel } from "../features/economics/EconomicPanel";
import { EconomicResult } from "../features/economics/EconomicResult";
import { RegisteredComparison } from "../features/decision/RegisteredComparison";
import {
  EquipmentCandidates,
  type EquipmentCandidate,
} from "../features/equipment/EquipmentCandidates";
import { EvidencePanel } from "../features/evidence/EvidencePanel";
import { GraphCanvas } from "../features/graph/GraphCanvas";
import {
  detail,
  graphView,
  label,
  nodeKey,
  type NodeRef,
} from "../features/graph/model";
const steps = [
  ["equipment", "設備を選ぶ", "対象設備を検索して選択します。"],
  [
    "investigation",
    "状態・影響を調べる",
    "現在状態と下流の依存関係を確認します。",
  ],
  [
    "comparison",
    "対応案を比べる",
    "登録された条件を選び、修理・交換・継続・代替を比較します。",
  ],
  ["evidence", "根拠を確かめる", "比較の出典と文書の引用を確認します。"],
  [
    "prepare",
    "変更を準備する",
    "必要な登録・訂正や変更内容を準備します。まだ確定しません。",
  ],
  [
    "execution",
    "承認・実行する",
    "別の承認者が確認し、元の依頼者が実行します。",
  ],
] as const;
type Step = (typeof steps)[number][0];
export function App() {
  const [step, setStep] = useState<Step>("equipment");
  const [comparisonResult, setComparisonResult] = useState<Envelope | null>(
    null,
  );
  const [documentResult, setDocumentResult] = useState<Envelope | null>(null);
  const [stateResult, setStateResult] = useState<Envelope | null>(null);
  const [comparisonStale, setComparisonStale] = useState(false);
  const [stateEpoch, setStateEpoch] = useState(0);
  const [search, setSearch] = useState("");
  const [inputTab, setInputTab] = useState("economic");
  const workspace = useRef<HTMLElement>(null);
  useEffect(() => {
    workspace.current?.focus();
  }, [step]);
  const [economicPrepared, setEconomicPrepared] = useState<
    string | undefined
  >();
  const [executionEpoch, setExecutionEpoch] = useState(0);
  const [draftToken, setDraftToken] = useState("");
  const token = useRef("");
  const freshContext = useRef(false);
  const messageInput = useRef<HTMLTextAreaElement>(null);
  const [equipment, setEquipment] = useState<EquipmentCandidate | null>(null);
  const retry = useRef<{ body: string; key: string } | null>(null);
  const [connected, setConnected] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [showConnection, setShowConnection] = useState(false);
  const [identity, setIdentity] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    request("", "/session", undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setConnected(true);
          setIdentity(
            typeof value.data.user_id === "string"
              ? value.data.user_id
              : "認証済み",
          );
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!controller.signal.aborted) setRestoring(false);
      });
    return () => controller.abort();
  }, []);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<Envelope | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<NodeRef | null>(null);
  const [stale, setStale] = useState(false);
  const current = useRef(0);
  const abort = useRef<AbortController | null>(null);
  async function disconnect() {
    try {
      await request(
        "",
        "/session/logout",
        undefined,
        undefined,
        undefined,
        "POST",
      );
    } catch (caught) {
      if (!(
        caught instanceof ApiError && caught.code === "AUTHENTICATION_REQUIRED"
      )) {
        setError(
          "接続解除を確認できません。通信を確認して再度解除してください。",
        );
        return;
      }
    }
    current.current++;
    abort.current?.abort();
    token.current = "";
    retry.current = null;
    setDraftToken("");
    setSearch("");
    setComparisonStale(false);
    setEquipment(null);
    setComparisonResult(null);
    setDocumentResult(null);
    setStateResult(null);
    setStep("equipment");
    setEconomicPrepared(undefined);
    freshContext.current = false;
    setConnected(false);
    setIdentity("");
    setShowConnection(false);
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
      () =>
        request(
          value,
          "/session/login",
          undefined,
          abort.current?.signal,
          undefined,
          "POST",
        ),
      (session) => {
        token.current = "";
        setIdentity(
          typeof session.data.user_id === "string"
            ? session.data.user_id
            : "認証済み",
        );
        setResult(null);
        setSelected(null);
        retry.current = null;
        setShowConnection(false);
        setDraftToken("");
        setEquipment(null);
        setComparisonResult(null);
        setDocumentResult(null);
        setStateResult(null);
        setStep("equipment");
        setEconomicPrepared(undefined);
        freshContext.current = false;
        setConnected(true);
      },
    );
  }
  async function investigate(event: FormEvent) {
    event.preventDefault();
    if (!connected || !message.trim()) return;
    setStale(true);
    await sendInvestigation(message);
  }
  async function sendInvestigation(text: string) {
    if (!connected || busy || !text.trim()) return;
    setMessage(text);
    setStale(true);
    const body = {
      message: text,
      ...(!freshContext.current && result?.context_id
        ? { context_id: result.context_id }
        : {}),
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
        freshContext.current = false;
        setResult(value);
        if (text.startsWith("文書検索：")) setDocumentResult(value);
        if (
          Array.isArray(value.data.tool_results) &&
          value.data.tool_results.some(
            (row) => object(row) && row.tool === "get_equipment_state",
          )
        ) {
          setStateResult(value);
          setStateEpoch(executionEpoch);
        }
        setEconomicPrepared(undefined);
        setSelected(null);
        setStale(false);
      },
    );
  }
  function draftInvestigation(text: string, focus = true) {
    freshContext.current = true;
    setMessage(text);
    if (focus) messageInput.current?.focus();
  }
  function chooseEquipment(item: EquipmentCandidate) {
    setEquipment(item);
    setComparisonResult(null);
    setDocumentResult(null);
    setStateResult(null);
    setResult(null);
    setStale(false);
    setStep("investigation");
    draftInvestigation(
      `Equipment ID ${item.equipment_id} の現在状態と下流の依存到達対象・経路を調べて。実停止・能力・安全性の未評価事項を示して。変更要求は作成しないでください。`,
    );
  }
  const compared = Array.isArray(result?.data.tool_results)
    ? result.data.tool_results
        .filter(object)
        .filter(
          (row) => row.tool === "compare_registered_inputs" && object(row.data),
        )
        .at(-1)
    : null;
  const comparedData =
    object(compared) && object(compared.data) ? compared.data : null;
  const analysisResult =
    result && comparedData && object(comparedData.decision_package)
      ? {
          ...result,
          data: {
            ...result.data,
            decision_package: comparedData.decision_package,
          },
          evidence: {
            ...result.evidence,
            ...(object(comparedData.evidence) ? comparedData.evidence : {}),
          },
        }
      : result;
  const view = analysisResult ? graphView(analysisResult) : null;
  const activeIndex = steps.findIndex(([key]) => key === step);
  const showQuery =
    step === "equipment" || step === "investigation" || step === "evidence";
  const evidenceResult = comparisonResult ?? analysisResult;
  function prepareInput(id: string) {
    setEconomicPrepared(id);
    setStep("execution");
  }
  return (
    <>
      <a className="skip-link" href="#workspace">
        操作画面へ移動
      </a>
      <header>
        <div className="brand-block">
          <strong>LineScope</strong>
          <span className="muted">設備の調査と対応</span>
        </div>
        <div className="connection-bar">
          <span className="badge">
            {connected ? `接続中：${identity}` : "未接続"}
          </span>
          <button onClick={() => setShowConnection(true)} disabled={restoring}>
            接続設定
          </button>
          {connected && <button onClick={disconnect}>接続解除</button>}
        </div>
      </header>
      {restoring ? (
        <main className="connect" role="status">
          接続状態を確認中…
        </main>
      ) : !connected || showConnection ? (
        <main className="connect">
          <p className="eyebrow">はじめに</p>
          <h1>LineScopeに接続する</h1>
          <p>
            設備を選び、状態と影響を調べ、対応案の比較から承認付きの変更まで進めます。
          </p>
          {connected && (
            <p>
              現在の接続：{identity}{" "}
              <button onClick={() => setShowConnection(false)}>
                操作画面へ戻る
              </button>
            </p>
          )}
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
            <button className="primary" disabled={busy || !draftToken.trim()}>
              {busy ? "確認中…" : "接続する"}
            </button>
          </form>
          <p className="muted">
            管理者から受け取った接続tokenを入力してください。承認を行う際は、別の承認者で接続し直します。
          </p>
          {error && <p role="alert">{error}</p>}
        </main>
      ) : (
        <div className="workflow-layout">
          <aside className="workflow-sidebar">
            <p className="section-label">操作の流れ</p>
            <nav aria-label="業務の工程">
              {steps.map(([key, title], index) => (
                <button
                  key={key}
                  aria-current={step === key ? "step" : undefined}
                  disabled={busy}
                  onClick={() => setStep(key)}
                >
                  <span className="step-number">{index + 1}</span>
                  <span>{title}</span>
                </button>
              ))}
            </nav>
            <p className="muted">
              承認者は「6 承認・実行する」から変更要求IDを開けます。
            </p>
          </aside>
          <main
            id="workspace"
            className="workflow-workspace"
            ref={workspace}
            tabIndex={-1}
          >
            <div className="equipment-context">
              <div>
                <span className="muted">対象設備</span>
                <strong>
                  {equipment
                    ? `${equipment.equipment_name}（${equipment.equipment_code}）`
                    : "まだ選択していません"}
                </strong>
              </div>
              {equipment && (
                <button disabled={busy} onClick={() => setStep("equipment")}>
                  設備を選び直す
                </button>
              )}
            </div>
            <div className="workflow-heading">
              <p className="eyebrow">STEP {activeIndex + 1} / 6</p>
              <h1>{steps[activeIndex][1]}</h1>
              <p>{steps[activeIndex][2]}</p>
            </div>
            {error && (
              <p className="notice" role="alert">
                {error}
              </p>
            )}
            {busy && (
              <p className="notice" role="status">
                取得中です。ローカルLLMを使う調査は最大120秒程度かかります。
              </p>
            )}
            {step === "equipment" && (
              <section className="workflow-card">
                <h2>設備名・コードから探す</h2>
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    freshContext.current = true;
                    void sendInvestigation(
                      search.trim()
                        ? `設備名またはコードに「${search.trim()}」を含む設備を検索して候補を表示して。変更要求は作成しないでください。`
                        : "登録設備を検索して候補を表示して。検索条件は指定しません。変更要求は作成しないでください。",
                    );
                  }}
                >
                  <label htmlFor="equipment-search">
                    設備名・コード（空欄なら登録設備を検索）
                  </label>
                  <div className="search-row">
                    <input
                      id="equipment-search"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="設備名やコードの一部"
                    />
                    <button className="primary" disabled={busy}>
                      設備を検索
                    </button>
                  </div>
                </form>
                {result && (
                  <EquipmentCandidates
                    result={result}
                    disabled={busy || stale}
                    onSelect={chooseEquipment}
                  />
                )}
                {!result && (
                  <p className="muted">
                    検索結果から対象を選ぶと、状態・影響の調査へ進みます。
                  </p>
                )}
              </section>
            )}
            {step === "investigation" && (
              <>
                {!equipment ? (
                  <p className="notice">
                    先に「1 設備を選ぶ」で対象を選択してください。
                  </p>
                ) : (
                  <div className="task-actions">
                    <button
                      disabled={busy}
                      onClick={() => {
                        freshContext.current = true;
                        void sendInvestigation(
                          `Equipment ID ${equipment.equipment_id} の現在のstate_codeとversionを正本から取得して。原因や安全性を推測しないでください。変更要求は作成しないでください。`,
                        );
                      }}
                    >
                      現在状態を確認
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => {
                        freshContext.current = true;
                        void sendInvestigation(
                          `Equipment ID ${equipment.equipment_id} から下流の依存到達対象を全ての通常依存関係で調べて。relation_typesにPRECEDESを含め、SUPPLIES、USES、PRODUCES、CONTROLS、DEPENDS_ONも対象とする。実停止・能力・安全性の未評価事項も示して。変更要求は作成しないでください。`,
                        );
                      }}
                    >
                      下流の影響候補を調べる
                    </button>
                  </div>
                )}
                {stateResult && (
                  <section className="workflow-card">
                    <h2>設備の登録状態</h2>
                    <p>{stateResult.answer}</p>
                    {(stale || stateEpoch !== executionEpoch) && (
                      <p className="notice">再取得前の状態です。</p>
                    )}
                  </section>
                )}
                {analysisResult && (
                  <section className="workflow-card">
                    <h2>調査結果</h2>
                    <span
                      className={`badge ${analysisResult.status === "partial" ? "warning" : ""}`}
                    >
                      {analysisResult.status === "partial"
                        ? "一部の情報・評価が不足しています"
                        : "取得済み結果"}
                    </span>
                    {(stale || stateEpoch !== executionEpoch) && (
                      <p className="notice">
                        前回取得した結果です。現在の状態は再取得してください。
                      </p>
                    )}
                    <p className="answer">{analysisResult.answer}</p>
                    {Array.isArray(result?.data.tool_results) &&
                      result.data.tool_results
                        .filter(object)
                        .map((row, index) =>
                          object(row.data) ? (
                            row.tool === "get_economic_input" ? (
                              <EconomicResult
                                key={index}
                                data={row.data}
                                stale={stale}
                              />
                            ) : row.tool === "get_capacity_input" ? (
                              <CapacityResult
                                key={index}
                                data={row.data}
                                stale={stale}
                              />
                            ) : row.tool === "get_safety_input" ? (
                              <SafetyResult
                                key={index}
                                data={row.data}
                                stale={stale}
                              />
                            ) : row.tool === "get_maintenance_input" ? (
                              <MaintenanceResult
                                key={index}
                                data={row.data}
                                stale={stale}
                              />
                            ) : null
                          ) : null,
                        )}
                    {view && (
                      <>
                        <GraphCanvas
                          view={view}
                          result={analysisResult}
                          selected={selected ? nodeKey(selected) : null}
                          onSelect={setSelected}
                        />
                        <p className="notice">
                          依存関係の到達候補です。実際の停止・能力・安全性を保証しません。探索：
                          {view.data.complete === true
                            ? "指定範囲は完了"
                            : "不完全・未確認"}
                          ／Graph同期：
                          {String(view.data.graph_sync_state ?? "未確認")}
                        </p>
                      </>
                    )}
                    {selected && (
                      <details open>
                        <summary>
                          {label(analysisResult, selected)}の詳細
                        </summary>
                        <pre>
                          {JSON.stringify(
                            detail(analysisResult, selected),
                            null,
                            2,
                          )}
                        </pre>
                      </details>
                    )}
                  </section>
                )}
              </>
            )}
            <section
              hidden={step !== "comparison"}
              aria-label="対応案を比較する工程"
            >
              {!equipment && (
                <p className="notice">先に対象設備を選んでください。</p>
              )}
              <RegisteredComparison
                key={equipment?.equipment_id ?? "none"}
                equipment={equipment}
                executionEpoch={executionEpoch}
                onResult={(value) => {
                  setComparisonResult(value);
                  setComparisonStale(false);
                }}
                onInvestigate={(text) => {
                  draftInvestigation(text, false);
                  setStep("investigation");
                }}
              />
              <button onClick={() => setStep("prepare")}>
                比較に必要な入力を登録・訂正する
              </button>
            </section>
            {step === "evidence" && (
              <>
                {evidenceResult ? (
                  <section className="workflow-card">
                    <h2>
                      {comparisonResult
                        ? "対応案比較の根拠"
                        : "直近の調査の根拠"}
                    </h2>
                    {(stale || comparisonStale) && (
                      <p className="notice">
                        変更前・前回取得の結果を含みます。再調査・再比較してください。
                      </p>
                    )}
                    <EvidencePanel result={evidenceResult} />
                  </section>
                ) : (
                  <p className="notice">
                    調査または比較を実行すると、その根拠を表示します。
                  </p>
                )}
                <section className="workflow-card">
                  <h2>関連文書を検索する</h2>
                  <p>
                    実文書の抜粋と引用元を確認します。文書は運転許可や確定判断の代わりにはなりません。
                  </p>
                  <button
                    disabled={busy || !equipment}
                    onClick={() => {
                      freshContext.current = true;
                      void sendInvestigation(
                        `文書検索：${equipment?.equipment_code}の保全調査`,
                      );
                    }}
                  >
                    選択設備の関連文書を検索
                  </button>
                  {documentResult && <EvidencePanel result={documentResult} />}
                </section>
              </>
            )}
            <section
              hidden={step !== "prepare"}
              aria-label="変更の入力を準備する工程"
            >
              <p className="notice">
                比較で不足している情報は、以下から登録・訂正できます。保存後は「6
                承認・実行する」へ進みます。
              </p>
              <nav className="input-categories" aria-label="登録する情報の種類">
                {[
                  ["economic", "費用・経済"],
                  ["capacity", "生産能力"],
                  ["safety", "安全条件"],
                  ["maintenance", "対応計画・故障履歴"],
                ].map(([key, title]) => (
                  <button
                    key={key}
                    aria-pressed={inputTab === key}
                    onClick={() => setInputTab(key)}
                  >
                    {title}
                  </button>
                ))}
              </nav>
              <div hidden={inputTab !== "economic"}>
                <EconomicPanel
                  initiallyOpen
                  key={"economic:" + (equipment?.equipment_id ?? "none")}
                  equipment={equipment}
                  onPrepared={prepareInput}
                  onInvestigate={(text) => {
                    draftInvestigation(text, false);
                    setStep("investigation");
                  }}
                  executionEpoch={executionEpoch}
                />
              </div>
              <div hidden={inputTab !== "capacity"}>
                <CapacityPanel
                  initiallyOpen
                  key={"capacity:" + (equipment?.equipment_id ?? "none")}
                  equipment={equipment}
                  onPrepared={prepareInput}
                  onInvestigate={(text) => {
                    draftInvestigation(text, false);
                    setStep("investigation");
                  }}
                  executionEpoch={executionEpoch}
                />
              </div>
              <div hidden={inputTab !== "safety"}>
                <SafetyPanel
                  initiallyOpen
                  key={"safety:" + (equipment?.equipment_id ?? "none")}
                  equipment={equipment}
                  onPrepared={prepareInput}
                  onInvestigate={(text) => {
                    draftInvestigation(text, false);
                    setStep("investigation");
                  }}
                  executionEpoch={executionEpoch}
                />
              </div>
              <div hidden={inputTab !== "maintenance"}>
                <MaintenancePanel
                  initiallyOpen
                  key={"maintenance:" + (equipment?.equipment_id ?? "none")}
                  equipment={equipment}
                  onPrepared={prepareInput}
                  onInvestigate={(text) => {
                    draftInvestigation(text, false);
                    setStep("investigation");
                  }}
                  executionEpoch={executionEpoch}
                />
              </div>
              <p>
                設備状態などの変更は、次の工程で対象と変更内容を指定して準備できます。
              </p>
              <button onClick={() => setStep("execution")}>
                変更指示を入力する
              </button>
            </section>
            <section
              hidden={step !== "execution"}
              aria-label="承認と実行の工程"
            >
              <ol className="approval-guide">
                <li>依頼者：変更を準備し、変更要求IDを控える。</li>
                <li>
                  別の承認者：接続を切り替え、IDから保存内容を読み直して承認する。
                </li>
                <li>元の依頼者：再接続し、IDから読み直して実行する。</li>
              </ol>
              <ActionPanel
                initiallyOpen
                onExecution={() => {
                  setStale(true);
                  setComparisonStale(true);
                  setExecutionEpoch((value) => value + 1);
                }}
                preparedId={
                  economicPrepared ??
                  (typeof result?.data.update_request_id === "string"
                    ? result.data.update_request_id
                    : undefined)
                }
              />
              <button onClick={() => setStep("comparison")}>
                実行後の入力で再比較する
              </button>
              <button onClick={() => setStep("investigation")}>
                実行後の状態を調べる
              </button>
            </section>
            {showQuery && (
              <details className="free-query">
                <summary>自分の言葉で問い合わせる</summary>
                <form onSubmit={investigate}>
                  <label htmlFor="message">問い合わせ</label>
                  <textarea
                    ref={messageInput}
                    id="message"
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    rows={4}
                  />
                  <button disabled={busy || !message.trim()}>
                    問い合わせを送信
                  </button>
                </form>
                <p className="muted">
                  明示的な変更指示は変更準備を作成する場合があります。承認・実行は自動で行いません。
                </p>
              </details>
            )}
            <footer className="workflow-footer">
              {activeIndex > 0 && (
                <button
                  disabled={busy}
                  onClick={() => setStep(steps[activeIndex - 1][0])}
                >
                  ← {steps[activeIndex - 1][1]}
                </button>
              )}
              {activeIndex < steps.length - 1 && (
                <button
                  className="primary"
                  disabled={busy || (!equipment && step !== "prepare")}
                  onClick={() => setStep(steps[activeIndex + 1][0])}
                >
                  次へ：{steps[activeIndex + 1][1]} →
                </button>
              )}
            </footer>
            {result && (
              <details className="technical-details">
                <summary>取得情報・処理の詳細</summary>
                <p>request_id: {result.request_id}</p>
                <pre>
                  {JSON.stringify(
                    {
                      trace: result.data.tool_trace,
                      warnings: result.warnings,
                      errors: result.errors,
                      data: result.data,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            )}
          </main>
        </div>
      )}
    </>
  );
}
