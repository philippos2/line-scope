import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
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
import { GraphWorkspace } from "../features/graph/GraphWorkspace";
import { graphAnalyses, type NodeRef } from "../features/graph/model";
const panels = [
  ["investigation", "調査・回答"],
  ["comparison", "対応案を比べる"],
  ["evidence", "根拠を確かめる"],
  ["prepare", "入力を登録・訂正"],
  ["execution", "変更・承認・実行"],
] as const;
type Step = (typeof panels)[number][0];
export function App() {
  const [step, setStep] = useState<Step>("investigation");
  const [comparisonResult, setComparisonResult] = useState<Envelope | null>(
    null,
  );
  const [documentResult, setDocumentResult] = useState<Envelope | null>(null);
  const [stateResult, setStateResult] = useState<Envelope | null>(null);
  const [comparisonStale, setComparisonStale] = useState(false);
  const [stateEpoch, setStateEpoch] = useState(0);
  const [search, setSearch] = useState("");
  const [searchResult, setSearchResult] = useState<Envelope | null>(null);
  const [graphResult, setGraphResult] = useState<Envelope | null>(null);
  const [nodeReads, setNodeReads] = useState<unknown[]>([]);
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
    setSearchResult(null);
    setGraphResult(null);
    setNodeReads([]);
    setStateResult(null);
    setStep("investigation");
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
        setSearchResult(null);
        setGraphResult(null);
        setNodeReads([]);
        setStateResult(null);
        setStep("investigation");
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
        if (graphAnalyses(value).length) setGraphResult(value);
        if (Array.isArray(value.data.tool_results)) {
          if (
            value.data.tool_results.some(
              (row) => object(row) && row.tool === "search_equipment",
            )
          )
            setSearchResult(value);
          setNodeReads((previous) => [
            ...previous,
            ...(value.data.tool_results as unknown[]).filter(
              (row) =>
                object(row) &&
                typeof row.tool === "string" &&
                row.tool.startsWith("get_"),
            ),
          ]);
        }
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
    if (busy) return;
    setEquipment(item);
    setComparisonResult(null);
    setDocumentResult(null);
    setStateResult(null);
    setGraphResult(null);
    setNodeReads([]);
    setResult(null);
    setSelected(null);
    setStale(false);
    setStep("investigation");
    freshContext.current = true;
    void sendInvestigation(
      `設備コード${item.equipment_code}の異常について影響・修理・交換・代替を比較して`,
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
  const graphDisplayResult = useMemo(
    () =>
      graphResult
        ? {
            ...graphResult,
            data: {
              ...graphResult.data,
              tool_results: [
                ...(Array.isArray(graphResult.data.tool_results)
                  ? graphResult.data.tool_results
                  : []),
                ...nodeReads,
              ],
            },
          }
        : null,
    [graphResult, nodeReads],
  );
  const evidenceResult = comparisonResult ?? graphResult ?? analysisResult;
  function prepareInput(id: string) {
    setEconomicPrepared(id);
    setStep("execution");
  }
  function investigateGraph(text: string) {
    freshContext.current = true;
    void sendInvestigation(text);
  }
  return (
    <>
      <a className="skip-link" href="#workspace">
        操作画面へ移動
      </a>
      <header>
        <div className="brand-block">
          <strong>LineScope</strong>
          <span className="muted">関係と影響の調査</span>
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
            設備・工程・製品のつながりをたどり、影響範囲と根拠を確認します。比較や変更操作も同じ調査画面から行えます。
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
        <div className="ontology-layout">
          <aside className="object-browser">
            <h2>調査する設備を探す</h2>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                investigateGraph(
                  search.trim()
                    ? `設備名またはコードに「${search.trim()}」を含む設備を検索して候補を表示して。変更要求は作成しないでください。`
                    : "登録設備を検索して候補を表示して。検索条件は指定しません。変更要求は作成しないでください。",
                );
              }}
            >
              <label htmlFor="equipment-search">設備名・コード</label>
              <input
                id="equipment-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="名称やコードの一部"
              />
              <button className="primary" disabled={busy}>
                設備を検索
              </button>
            </form>
            {searchResult && graphResult ? (
              <EquipmentCandidates
                result={searchResult}
                disabled={busy}
                onSelect={chooseEquipment}
              />
            ) : (
              <p className="muted">
                候補を選ぶと、その設備を起点とした下流影響と上流依存を取得します。
              </p>
            )}
            {equipment && (
              <div className="focus-object">
                <span className="muted">比較・入力の対象設備</span>
                <strong>{equipment.equipment_name}</strong>
                <span>{equipment.equipment_code}</span>
              </div>
            )}
            <p className="muted">
              表示するのは取得した関係です。工場全体を網羅した一覧ではありません。
            </p>
          </aside>
          <main
            id="workspace"
            className="ontology-workspace"
            ref={workspace}
            tabIndex={-1}
          >
            {error && (
              <p className="notice" role="alert">
                {error}
              </p>
            )}
            {busy && (
              <p className="notice" role="status">
                調査中です。ローカルLLMを使う場合は最大120秒程度かかります。
              </p>
            )}
            <GraphWorkspace
              key={equipment?.equipment_id ?? "none"}
              result={graphDisplayResult}
              selected={selected}
              busy={busy}
              stale={stale}
              onSelect={setSelected}
              onInvestigate={investigateGraph}
              onRefresh={() =>
                equipment &&
                investigateGraph(
                  `設備コード${equipment.equipment_code}の異常について影響・修理・交換・代替を比較して`,
                )
              }
              onStart={() =>
                investigateGraph(
                  "登録設備を検索して候補を表示して。検索条件は指定しません。変更要求は作成しないでください。",
                )
              }
              emptyContent={
                searchResult ? (
                  <EquipmentCandidates
                    result={searchResult}
                    disabled={busy}
                    onSelect={chooseEquipment}
                  />
                ) : undefined
              }
              onEvidence={() => setStep("evidence")}
            />
            <nav className="context-tabs" aria-label="調査に続く操作">
              {panels.map(([key, title]) => (
                <button
                  key={key}
                  aria-pressed={step === key}
                  onClick={() => setStep(key)}
                >
                  {title}
                </button>
              ))}
            </nav>
            <section hidden={step !== "investigation"} aria-label="調査と回答">
              <div className="query-and-answer">
                <form onSubmit={investigate}>
                  <label htmlFor="message">関係や影響について質問する</label>
                  <textarea
                    id="message"
                    ref={messageInput}
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    placeholder="例：この設備が止まったとき、影響する工程と製品は？"
                    rows={3}
                  />
                  <button
                    className="primary"
                    disabled={busy || !message.trim()}
                  >
                    問い合わせを送信
                  </button>
                </form>
                {result && (
                  <section>
                    <h2>調査の回答</h2>
                    {result.status === "partial" && (
                      <span className="badge warning">
                        一部の情報・評価が不足しています
                      </span>
                    )}
                    <p className="answer">{result.answer}</p>
                  </section>
                )}
              </div>
              {stateResult && (
                <details>
                  <summary>取得した設備状態</summary>
                  <p>{stateResult.answer}</p>
                  {(stale || stateEpoch !== executionEpoch) && (
                    <p className="notice">再取得前の状態です。</p>
                  )}
                </details>
              )}
              {equipment && (
                <button
                  disabled={busy}
                  onClick={() =>
                    investigateGraph(
                      `Equipment ID ${equipment.equipment_id} の現在のstate_codeとversionを正本から取得して。原因や安全性を推測しないでください。変更要求は作成しないでください。`,
                    )
                  }
                >
                  現在状態を確認
                </button>
              )}
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
            </section>
            <section
              hidden={step !== "comparison"}
              aria-label="対応案を比較する"
            >
              {!equipment && (
                <p className="notice">
                  左から比較する設備を検索して選んでください。
                </p>
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
                不足している入力を登録・訂正する
              </button>
              <button onClick={() => setStep("evidence")}>
                比較の根拠を確かめる
              </button>
            </section>
            <section hidden={step !== "evidence"} aria-label="根拠と関連文書">
              {evidenceResult ? (
                <>
                  <h2>
                    {comparisonResult
                      ? "対応案比較の根拠"
                      : "関係と影響の調査根拠"}
                  </h2>
                  {(stale || comparisonStale) && (
                    <p className="notice">
                      変更前の取得結果を含みます。再調査・再比較してください。
                    </p>
                  )}
                  <EvidencePanel result={evidenceResult} />
                </>
              ) : (
                <p>調査すると、経路や登録情報の根拠を確認できます。</p>
              )}
              <h2>関連文書を検索する</h2>
              <button
                disabled={busy || !equipment}
                onClick={() =>
                  investigateGraph(
                    `文書検索：${equipment?.equipment_code}の保全調査`,
                  )
                }
              >
                選択設備の関連文書を検索
              </button>
              {documentResult && <EvidencePanel result={documentResult} />}
            </section>
            <section
              hidden={step !== "prepare"}
              aria-label="入力を登録・訂正する"
            >
              <p>
                比較に必要な情報を登録・訂正します。準備だけでは確定せず、別の承認者による承認と元依頼者の実行が必要です。
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
            </section>
            <section
              hidden={step !== "execution"}
              aria-label="変更と承認・実行"
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
              <p>
                実行後は対象を左から選び直し、関係・影響と比較を再取得してください。
              </p>
            </section>
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
