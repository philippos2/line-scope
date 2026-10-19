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
import type { EquipmentCandidate } from "../features/equipment/EquipmentCandidates";
import { EvidencePanel } from "../features/evidence/EvidencePanel";
import { EquipmentInvestigation } from "../features/investigation/EquipmentInvestigation";
import { WorkspaceHeader } from "../features/investigation/WorkspaceHeader";
import { useEquipmentInvestigation } from "../features/investigation/useEquipmentInvestigation";
import { explanation, products } from "../features/investigation/readModel";
import type { GraphMemory } from "../features/graph/GraphCanvas";
import { graphAnalyses, type NodeRef } from "../features/graph/model";
const panels = [
  ["graph", "接続及び影響範囲"],
  ["comparison", "対応案を比べる"],
  ["investigation", "質問する"],
  ["evidence", "出典と経路"],
  ["prepare", "入力を登録・訂正"],
  ["execution", "変更・承認・実行"],
] as const;
type Step = (typeof panels)[number][0];
export function App() {
  const [actionDraftVersion, setActionDraftVersion] = useState(0);
  const [actionDraft, setActionDraft] = useState("");
  const [stateChoice, setStateChoice] = useState("");
  const [step, setStep] = useState<Step>("graph");
  const [evidenceKind, setEvidenceKind] = useState<
    "graph" | "comparison" | "documents"
  >("graph");
  const [comparisonResult, setComparisonResult] = useState<Envelope | null>(
    null,
  );
  const [documentResult, setDocumentResult] = useState<Envelope | null>(null);
  const [stateResult, setStateResult] = useState<Envelope | null>(null);
  const [comparisonStale, setComparisonStale] = useState(false);
  const [stateEpoch, setStateEpoch] = useState(0);
  const [graphResult, setGraphResult] = useState<Envelope | null>(null);
  const [inputTab, setInputTab] = useState("economic");
  const workspace = useRef<HTMLElement>(null);
  const [economicPrepared, setEconomicPrepared] = useState<
    string | undefined
  >();
  const [executionEpoch, setExecutionEpoch] = useState(0);
  const [draftToken, setDraftToken] = useState("");
  const token = useRef("");
  const freshContext = useRef(false);
  const messageInput = useRef<HTMLTextAreaElement>(null);
  const [equipment, setEquipment] = useState<EquipmentCandidate | null>(null);
  const [decisionEquipment, setDecisionEquipment] =
    useState<EquipmentCandidate | null>(null);
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
  const [, setSelected] = useState<NodeRef | null>(null);
  const [stale, setStale] = useState(false);
  const current = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const model = useEquipmentInvestigation(
    connected ? equipment : null,
    executionEpoch,
  );
  const [graphMemory, setGraphMemory] = useState<Record<string, GraphMemory>>(
    {},
  );
  const dirty = useRef(new Set<string>());
  function chooseRoot(item: EquipmentCandidate | null) {
    if (item?.equipment_id === equipment?.equipment_id) return true;
    if (
      dirty.current.size &&
      !window.confirm("編集中の入力を破棄して起点設備を変更しますか？")
    )
      return false;
    dirty.current.clear();
    setEquipment(item);
    setDecisionEquipment(item);
    setGraphMemory({});
    setComparisonResult(null);
    setDocumentResult(null);
    setEconomicPrepared(undefined);
    setActionDraft("");
    setActionDraftVersion((x) => x + 1);
    setStateChoice("");
    setResult(null);
    setGraphResult(null);
    setMessage("");
    setError("");
    freshContext.current = true;
    abort.current?.abort();
    current.current += 1;
    setBusy(false);
    return true;
  }
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
    setComparisonStale(false);
    setGraphMemory({});
    dirty.current.clear();
    setEquipment(null);
    setDecisionEquipment(null);
    setComparisonResult(null);
    setDocumentResult(null);
    setGraphResult(null);
    setStateResult(null);
    setStep("graph");
    setEconomicPrepared(undefined);
    setActionDraft("");
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
        setGraphMemory({});
        dirty.current.clear();
        setEquipment(null);
        setDecisionEquipment(null);
        setComparisonResult(null);
        setDocumentResult(null);
        setGraphResult(null);
        setStateResult(null);
        setStep("graph");
        setEconomicPrepared(undefined);
        setActionDraft("");
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
    if (!text.startsWith("関係分析 ")) setMessage(text);
    setStale(true);
    const body = {
      message:
        equipment &&
        !text.startsWith("関係分析 ") &&
        !text.startsWith("文書検索：") &&
        !text.startsWith("登録入力で比較 ")
          ? `調査対象の設備コードは${equipment.equipment_code}です。\n${text}`
          : text,
      ...(!text.startsWith("関係分析 ") &&
      !freshContext.current &&
      result?.context_id
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
        if (graphAnalyses(value).length) {
          setGraphResult(value);
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
        setStale(false);
      },
    );
  }
  function draftInvestigation(text: string, focus = true) {
    freshContext.current = true;
    setMessage(text);
    if (focus) messageInput.current?.focus();
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
  const evidenceResult =
    evidenceKind === "documents"
      ? documentResult
      : evidenceKind === "comparison"
        ? comparisonResult
        : (graphResult ?? analysisResult);
  function prepareInput(id: string) {
    dirty.current.delete("prepare");
    setActionDraft("");
    setEconomicPrepared(id);
    setStep("execution");
  }
  function investigateGraph(text: string) {
    if (busy || !equipment) return;
    const owner = equipment.equipment_id;
    void perform(
      () => request("", "/agent", { message: text }, abort.current?.signal),
      (value) => {
        if (owner === equipment.equipment_id) {
          setDocumentResult(value);
          setEvidenceKind("documents");
        }
      },
    );
  }
  return (
    <>
      <a className="skip-link" href="#workspace">
        操作画面へ移動
      </a>
      <header>
        <div className="brand-block">
          <strong>LineScope</strong>
          <span className="muted">設備調査</span>
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
        <div className="scenario-shell">
          <main
            id="workspace"
            className="ontology-workspace"
            ref={workspace}
            tabIndex={-1}
            onChangeCapture={(event) => {
              if (
                (event.target as HTMLElement).closest(
                  "#panel-prepare, #panel-execution, #panel-comparison",
                )
              )
                dirty.current.add(step);
            }}
          >
            <WorkspaceHeader
              tabs={
                <nav
                  className="context-tabs workspace-tabs"
                  aria-label="機能を選ぶ"
                  role="tablist"
                >
                  {panels.map(([key, title], index) => (
                    <button
                      key={key}
                      role="tab"
                      id={`tab-${key}`}
                      aria-controls={`panel-${key}`}
                      aria-selected={step === key}
                      tabIndex={step === key ? 0 : -1}
                      onKeyDown={(event) => {
                        if (
                          ["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                            event.key,
                          )
                        ) {
                          event.preventDefault();
                          const next =
                            event.key === "Home"
                              ? 0
                              : event.key === "End"
                                ? panels.length - 1
                                : (index +
                                    (event.key === "ArrowRight" ? 1 : -1) +
                                    panels.length) %
                                  panels.length;
                          setStep(panels[next][0]);
                          document
                            .getElementById(`tab-${panels[next][0]}`)
                            ?.focus();
                        }
                      }}
                      onClick={() => setStep(key)}
                    >
                      {title}
                    </button>
                  ))}
                </nav>
              }
              root={equipment}
              model={model}
              onChoose={chooseRoot}
              onInspect={(section) => {
                setStep("graph");
                requestAnimationFrame(() =>
                  document
                    .getElementById(
                      section === "loss"
                        ? "workspace-loss"
                        : "workspace-alternative",
                    )
                    ?.scrollIntoView({ block: "nearest" }),
                );
              }}
            >
              <div
                id="panel-graph"
                role="tabpanel"
                aria-labelledby="tab-graph"
                hidden={step !== "graph"}
              >
                <EquipmentInvestigation
                  key={equipment?.equipment_id ?? "none"}
                  root={equipment}
                  model={model}
                  graphMemory={graphMemory}
                  onGraphMemory={(key, value) =>
                    setGraphMemory((old) => ({ ...old, [key]: value }))
                  }
                  onRootChange={chooseRoot}
                  onUseEquipment={() => {
                    setDecisionEquipment(equipment);
                    setStep("comparison");
                  }}
                  onRegister={(item) => {
                    setDecisionEquipment(item);
                    setInputTab("economic");
                    setStep("prepare");
                  }}
                  onObservations={setGraphResult}
                />
                <button
                  onClick={() => {
                    setEvidenceKind("graph");
                    setStep("evidence");
                  }}
                >
                  調査の根拠を見る
                </button>
              </div>
              <section
                hidden={step !== "investigation"}
                id="panel-investigation"
                role="tabpanel"
                aria-labelledby="tab-investigation"
                aria-label="調査と回答"
              >
                <div className="query-and-answer">
                  <div className="question-input">
                    <p>
                      質問の対象：
                      {equipment
                        ? `${equipment.equipment_name} · ${equipment.equipment_code}`
                        : "未選択（設備名・コードを質問に含めるか、上の「設備を選ぶ」を使ってください）"}
                    </p>
                    <form onSubmit={investigate}>
                      <label htmlFor="message">
                        関係や影響について質問する
                      </label>
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
                        送信
                      </button>
                    </form>
                  </div>
                  <div className="question-response">
                    {busy && (
                      <p role="status">
                        質問を確認しています。応答に最大120秒程度かかる場合があります。
                      </p>
                    )}
                    {error && (
                      <p role="alert">
                        {explanation(error.split(" / ")[0])}{" "}
                        質問を保ったまま再試行できます。
                      </p>
                    )}
                    {result && (
                      <section>
                        <h2>回答</h2>
                        {result.status === "partial" && (
                          <span className="badge warning">
                            一部の情報・評価が不足しています
                          </span>
                        )}
                        <p className="answer">{result.answer}</p>
                      </section>
                    )}
                  </div>
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
                id="panel-comparison"
                role="tabpanel"
                aria-labelledby="tab-comparison"
                aria-label="対応案を比較する"
              >
                {!decisionEquipment && (
                  <p className="notice">
                    上の「設備を選ぶ」から対応案を比べる起点設備を選んでください。
                  </p>
                )}
                <RegisteredComparison
                  key={decisionEquipment?.equipment_id ?? "none"}
                  equipment={decisionEquipment}
                  executionEpoch={executionEpoch}
                  initialEconomic={model.economic}
                  initialCapacity={model.capacity}
                  initialEconomicId={model.economicId}
                  initialCapacityId={model.capacityId}
                  candidateIds={model.candidateEquipment.map(
                    (x) => x.equipment_id,
                  )}
                  productIds={products(model.states.down?.value).map(
                    (x) => x.entity_id,
                  )}
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
                <button
                  onClick={() => {
                    setEvidenceKind("comparison");
                    setStep("evidence");
                  }}
                >
                  比較の根拠を確かめる
                </button>
              </section>
              <section
                hidden={step !== "evidence"}
                id="panel-evidence"
                role="tabpanel"
                aria-labelledby="tab-evidence"
                aria-label="根拠と関連文書"
              >
                <nav aria-label="根拠の種類">
                  {(
                    [
                      ["graph", "調査"],
                      ["comparison", "比較"],
                      ["documents", "関連文書"],
                    ] as const
                  ).map(([kind, title]) => (
                    <button
                      key={kind}
                      aria-pressed={kind === evidenceKind}
                      onClick={() => setEvidenceKind(kind)}
                    >
                      {title}
                    </button>
                  ))}
                </nav>
                <h2>
                  {evidenceKind === "graph"
                    ? "調査"
                    : evidenceKind === "comparison"
                      ? "比較"
                      : "関連文書"}
                  の出典と経路
                </h2>
                {evidenceResult ? (
                  <>
                    <h2>
                      {evidenceKind === "comparison"
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
              </section>
              <section
                hidden={step !== "prepare"}
                id="panel-prepare"
                role="tabpanel"
                aria-labelledby="tab-prepare"
                aria-label="入力を登録・訂正する"
              >
                <p>
                  比較に必要な情報を登録・訂正します。準備だけでは確定せず、別の承認者による承認と元依頼者の実行が必要です。
                </p>
                <nav
                  className="input-categories"
                  aria-label="登録する情報の種類"
                >
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
                    key={
                      "economic:" + (decisionEquipment?.equipment_id ?? "none")
                    }
                    equipment={decisionEquipment}
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
                    key={
                      "capacity:" + (decisionEquipment?.equipment_id ?? "none")
                    }
                    equipment={decisionEquipment}
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
                    key={
                      "safety:" + (decisionEquipment?.equipment_id ?? "none")
                    }
                    equipment={decisionEquipment}
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
                    key={
                      "maintenance:" +
                      (decisionEquipment?.equipment_id ?? "none")
                    }
                    equipment={decisionEquipment}
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
                id="panel-execution"
                role="tabpanel"
                aria-labelledby="tab-execution"
                aria-label="変更と承認・実行"
              >
                {equipment && (
                  <div className="state-change-prepare">
                    <h2>登録状態を変更する</h2>
                    <p>
                      {equipment.equipment_name}（{equipment.equipment_code}）
                    </p>
                    <label>
                      変更後の登録状態
                      <select
                        value={stateChoice}
                        onChange={(e) => setStateChoice(e.target.value)}
                      >
                        <option value="">選んでください</option>
                        <option value="RUNNING">稼働中</option>
                        <option value="STOPPED">停止中</option>
                        <option value="UNDER_MAINTENANCE">保全中</option>
                        <option value="UNKNOWN">不明</option>
                      </select>
                    </label>
                    <button
                      disabled={!stateChoice}
                      onClick={() => {
                        setActionDraftVersion((x) => x + 1);
                        setActionDraft(
                          `設備${equipment.equipment_code}の状態を${stateChoice}に変更する準備を作って`,
                        );
                      }}
                    >
                      変更の下書きを作る
                    </button>
                  </div>
                )}
                <ol className="approval-guide">
                  <li>依頼者：変更を準備し、変更要求IDを控える。</li>
                  <li>
                    別の承認者：接続を切り替え、IDから保存内容を読み直して承認する。
                  </li>
                  <li>元の依頼者：再接続し、IDから読み直して実行する。</li>
                </ol>
                <ActionPanel
                  key={
                    (decisionEquipment?.equipment_id ??
                      equipment?.equipment_id ??
                      "none") +
                    ":" +
                    actionDraftVersion +
                    ":" +
                    actionDraft
                  }
                  initialMessage={actionDraft}
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
                <p>実行後は上の「再調査」で結果を更新してください。</p>
                <button onClick={() => setStep("comparison")}>
                  対応案の比較へ戻る
                </button>
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
            </WorkspaceHeader>
          </main>
        </div>
      )}
    </>
  );
}
