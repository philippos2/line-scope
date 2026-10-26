import {
  ReadFeedback,
  readProblem,
  type ReadProblem,
} from "../features/inputs/ReadFeedback";
import {
  DocumentSearchStatus,
  type DocumentObservation,
} from "../features/evidence/DocumentSearchStatus";
import { InputAssistance } from "../features/inputs/InputAssistance";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  object,
  request,
  type Envelope,
  type JsonObject,
} from "../api/client";
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
import { ReferenceDrawer } from "../features/investigation/ReferenceDrawer";
import { rows } from "../features/investigation/readModel";
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
  const [actionDraft, setActionDraft] = useState("");
  const [stateChoice, setStateChoice] = useState("");
  const [direction, setDirection] = useState<"down" | "up" | "extra">("down");
  const [reference, setReference] = useState<
    "diagram" | "graph" | "comparison" | "documents" | "answer" | null
  >(null);
  const [savedRequest, setSavedRequest] = useState<Envelope | null>(null);
  const [step, setStep] = useState<Step>("graph");
  const [evidenceKind, setEvidenceKind] = useState<
    "graph" | "comparison" | "documents"
  >("graph");
  const [comparisonResult, setComparisonResult] = useState<Envelope | null>(
    null,
  );
  const [documentResult, setDocumentResult] = useState<Envelope | null>(null);
  const [documentBusy, setDocumentBusy] = useState(false);
  const [documentError, setDocumentError] = useState<ReadProblem | null>(null);
  const [documentObservation, setDocumentObservation] =
    useState<DocumentObservation | null>(null);
  const [connectionError, setConnectionError] = useState<ReadProblem | null>(
    null,
  );
  const [connectionOperation, setConnectionOperation] = useState<
    "login" | "logout"
  >("login");
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const disconnectPending = useRef(false);
  const [activeOperation, setActiveOperation] = useState<
    "connection" | "question" | null
  >(null);
  const documentRequest = useRef<AbortController | null>(null);
  const documentHeading = useRef<HTMLHeadingElement>(null);
  const [stateResult, setStateResult] = useState<Envelope | null>(null);
  const [comparisonStale, setComparisonStale] = useState(false);
  const [stateEpoch, setStateEpoch] = useState(0);
  const [answerEpoch, setAnswerEpoch] = useState(0);
  const [graphResult, setGraphResult] = useState<Envelope | null>(null);
  const [inputTab, setInputTab] = useState("economic");
  const workspace = useRef<HTMLElement>(null);
  const workspaceTabs = useRef<HTMLElement>(null);
  const [economicPrepared, setEconomicPrepared] = useState<
    string | undefined
  >();
  const [requestedOpen, setRequestedOpen] = useState<{ id: string } | null>(
    null,
  );
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
  const [actorRole, setActorRole] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    request("", "/session", undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setConnected(true);
          setActorRole(
            typeof value.data.role === "string" ? value.data.role : "",
          );
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
  const [questionTurns, setQuestionTurns] = useState<
    { question: string; answer: string }[]
  >([]);
  const [questionSelection, setQuestionSelection] = useState<JsonObject | null>(
    null,
  );
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
  useEffect(() => {
    const tabs = workspaceTabs.current;
    if (!connected || !tabs) return;
    const update = () =>
      tabs.parentElement?.style.setProperty(
        "--workspace-tabs-height",
        `${tabs.getBoundingClientRect().height}px`,
      );
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(tabs);
    return () => observer.disconnect();
  }, [connected]);
  useEffect(() => {
    documentRequest.current?.abort();
    setDocumentResult(null);
    setDocumentObservation(null);
    setDocumentError(null);
    setDocumentBusy(false);
    return () => documentRequest.current?.abort();
  }, [connected, equipment?.equipment_id]);
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
    setReference(null);
    setDirection("down");
    setComparisonResult(null);
    setDocumentResult(null);
    setActionDraft("");
    setStateChoice("");
    setResult(null);
    setQuestionTurns([]);
    setGraphResult(null);
    setMessage("");
    setQuestionSelection(null);
    setError("");
    freshContext.current = true;
    abort.current?.abort();
    current.current += 1;
    setBusy(false);
    return true;
  }
  async function disconnect() {
    if (disconnectPending.current) return;
    disconnectPending.current = true;
    setDisconnectBusy(true);
    setConnectionOperation("logout");
    setConnectionError(null);
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
        setConnectionError(readProblem(caught));
        return;
      }
    } finally {
      disconnectPending.current = false;
      setDisconnectBusy(false);
    }
    current.current++;
    abort.current?.abort();
    token.current = "";
    retry.current = null;
    setDraftToken("");
    setComparisonStale(false);
    setGraphMemory({});
    setReference(null);
    setDirection("down");
    setSavedRequest(null);
    dirty.current.clear();
    setEquipment(null);
    setDecisionEquipment(null);
    setComparisonResult(null);
    setDocumentResult(null);
    setGraphResult(null);
    setStateResult(null);
    setStep("graph");
    setEconomicPrepared(undefined);
    setRequestedOpen(null);
    setActionDraft("");
    freshContext.current = false;
    setConnected(false);
    setIdentity("");
    setActorRole("");
    setShowConnection(false);
    setBusy(false);
    setResult(null);
    setQuestionTurns([]);
    setSelected(null);
    setMessage("");
    setQuestionSelection(null);
    setError("");
    setStale(false);
  }
  async function perform(
    action: () => Promise<Envelope>,
    onSuccess: (value: Envelope) => void,
    operation: "connection" | "question" = "question",
  ) {
    const id = ++current.current;
    abort.current?.abort();
    abort.current = new AbortController();
    setBusy(true);
    setActiveOperation(operation);
    if (operation === "connection") setConnectionError(null);
    else setError("");
    try {
      const value = await action();
      if (id === current.current) onSuccess(value);
    } catch (caught) {
      if (id === current.current) {
        if (operation === "connection") setConnectionError(readProblem(caught));
        else
          setError(
            caught instanceof ApiError
              ? `${caught.code}${caught.requestId ? " / " + caught.requestId : ""}`
              : "REQUEST_FAILED",
          );
      }
    } finally {
      if (id === current.current) {
        setBusy(false);
        setActiveOperation(null);
      }
    }
  }

  async function connect(event: FormEvent) {
    event.preventDefault();
    const value = draftToken.trim();
    if (!value || busy || disconnectPending.current) return;
    setConnectionOperation("login");
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
        setActorRole(
          typeof session.data.role === "string" ? session.data.role : "",
        );
        setIdentity(
          typeof session.data.user_id === "string"
            ? session.data.user_id
            : "認証済み",
        );
        setResult(null);
        setQuestionTurns([]);
        setSelected(null);
        retry.current = null;
        setShowConnection(false);
        setDraftToken("");
        setGraphMemory({});
        setReference(null);
        setDirection("down");
        setSavedRequest(null);
        dirty.current.clear();
        setEquipment(null);
        setDecisionEquipment(null);
        setComparisonResult(null);
        setDocumentResult(null);
        setGraphResult(null);
        setStateResult(null);
        setStep("graph");
        setEconomicPrepared(undefined);
        setRequestedOpen(null);
        setActionDraft("");
        freshContext.current = false;
        setConnected(true);
      },
      "connection",
    );
  }
  async function investigate(event: FormEvent) {
    event.preventDefault();
    if (!connected || !message.trim()) return;
    setStale(true);
    await sendInvestigation(message, questionSelection);
  }
  async function sendInvestigation(
    text: string,
    selection: JsonObject | null = null,
  ) {
    if (!connected || busy || !text.trim()) return;
    if (!text.startsWith("関係分析 ")) setMessage(text);
    setStale(true);
    const body = {
      message: selection ? `登録入力で比較 ${JSON.stringify(selection)}` : text,
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
        if (object(value.data.answer_sections)) {
          setQuestionTurns((turns) => [
            {
              question: text,
              answer: value.answer ?? "回答を取得できませんでした。",
            },
            ...turns,
          ]);
        }
        setAnswerEpoch(executionEpoch);
        if (graphAnalyses(value).length) {
          setGraphResult(value);
        }
        if (text.startsWith("文書検索：")) {
          setDocumentResult(value);
          setDocumentObservation(null);
        }
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
    setQuestionSelection(null);
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
  const entityNames: Record<string, string> = {};
  for (const row of model.metadata) {
    if (!object(row) || !object(row.data)) continue;
    for (const kind of ["equipment", "product", "process", "resource"]) {
      const id =
          row.data[
            kind === "resource" ? "infrastructure_resource_id" : `${kind}_id`
          ],
        name = row.data[`${kind}_name`],
        code = row.data[`${kind}_code`];
      if (typeof id === "string" && typeof code === "string")
        entityNames[id] =
          typeof name === "string"
            ? name.includes(code)
              ? name
              : `${name} · ${code}`
            : code;
    }
  }
  for (const item of [
    ...model.candidateEquipment,
    ...(equipment ? [equipment] : []),
  ])
    entityNames[item.equipment_id] =
      `${item.equipment_name} · ${item.equipment_code}`;
  const evidenceResult =
    evidenceKind === "documents"
      ? documentResult
      : evidenceKind === "comparison"
        ? comparisonResult
        : (graphResult ?? model.states.down?.value ?? analysisResult);
  const referenceResult =
    reference === "comparison"
      ? comparisonResult
      : reference === "documents"
        ? documentResult
        : reference === "answer"
          ? result
          : model.states[direction]?.value;
  const snapshot = object(savedRequest?.data.canonical_snapshot)
    ? savedRequest.data.canonical_snapshot
    : null;
  const requestTargets = rows(snapshot?.targets);
  const requestEquipment = requestTargets.map((target) =>
    object(target.business_key) ? target.business_key.equipment_id : undefined,
  );
  const approvalReferenceWarning =
    step !== "execution"
      ? ""
      : !requestTargets.length
        ? "変更要求の対象をまだ確認していません。この要求対象の関係図は未取得です。"
        : requestEquipment.some((id) => typeof id !== "string")
          ? "変更要求の対象設備を特定できません。この要求対象の関係図は未取得です。"
          : !equipment ||
              requestEquipment.some((id) => id !== equipment.equipment_id)
            ? "変更要求の対象と調査起点が一致しません。この要求対象の関係図は未取得です。"
            : "";
  function referenceTime(value: Envelope | null | undefined) {
    const raw =
      value?.evidence.observed_at ??
      rows(value?.evidence.tool_results)[0]?.graph_observed_at;
    if (typeof raw !== "string" || Number.isNaN(Date.parse(raw)))
      return value ? "取得済み（時刻情報なし）" : "未取得";
    return (
      "取得時点：" +
      new Intl.DateTimeFormat("ja-JP", {
        timeZone: "Asia/Tokyo",
        dateStyle: "short",
        timeStyle: "medium",
      }).format(new Date(raw)) +
      "（日本時間）"
    );
  }
  function prepareInput(id: string) {
    dirty.current.delete("prepare");
    setActionDraft("");
    setEconomicPrepared(id);
  }
  function openPrepared(id: string) {
    setEconomicPrepared(id);
    setRequestedOpen({ id });
    setStep("execution");
  }
  async function searchDocuments() {
    if (documentBusy || !equipment) return;
    documentRequest.current?.abort();
    const controller = new AbortController();
    documentRequest.current = controller;
    setDocumentBusy(true);
    setDocumentError(null);
    setEvidenceKind("documents");
    const target = equipment;
    const epoch = executionEpoch;
    try {
      const value = await request(
        "",
        "/agent",
        {
          message: `文書検索：${equipment.equipment_code}の保全調査`,
        },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setDocumentResult(value);
        setDocumentObservation({
          equipmentId: target.equipment_id,
          equipmentLabel: `${target.equipment_name} · ${target.equipment_code}`,
          completedAt: new Date().toISOString(),
          epoch,
        });
        requestAnimationFrame(() => {
          if (documentHeading.current?.getClientRects().length)
            documentHeading.current.focus();
        });
      }
    } catch (caught) {
      if (!controller.signal.aborted) setDocumentError(readProblem(caught));
    } finally {
      if (!controller.signal.aborted) setDocumentBusy(false);
    }
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
          {connected && (
            <button
              onClick={disconnect}
              disabled={
                disconnectBusy || (busy && activeOperation === "connection")
              }
              aria-busy={disconnectBusy}
            >
              {disconnectBusy ? "接続解除中…" : "接続解除"}
            </button>
          )}
          {disconnectBusy && (
            <p role="status">
              接続解除の応答を待っています。完了まで再送できません。
            </p>
          )}
          {connected && !showConnection && (
            <ReadFeedback
              problem={connectionError}
              operation={connectionOperation === "logout" ? "接続解除" : "接続"}
              onRetry={
                connectionOperation === "logout"
                  ? () => void disconnect()
                  : () => setShowConnection(true)
              }
            />
          )}
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
            <button
              className="primary"
              disabled={busy || disconnectBusy || !draftToken.trim()}
              aria-busy={busy && activeOperation === "connection"}
              aria-describedby="connection-submit-reason"
            >
              {busy && activeOperation === "connection"
                ? "接続確認中…"
                : "接続する"}
            </button>
          </form>
          <p className="muted">
            管理者から受け取った接続tokenを入力してください。承認を行う際は、別の承認者で接続し直します。
          </p>
          <p id="connection-submit-reason" role="status">
            {disconnectBusy
              ? "接続解除が完了するまで、接続を切り替えられません。"
              : busy
                ? activeOperation === "connection"
                  ? "接続を確認しています。完了まで再送できません。"
                  : "質問への応答を待っています。完了してから接続を切り替えてください。"
                : !draftToken.trim()
                  ? "接続用の認証情報を入力すると接続できます。"
                  : "入力した認証情報で接続します。"}
          </p>
          <ReadFeedback
            problem={connectionError}
            operation={connectionOperation === "logout" ? "接続解除" : "接続"}
            onRetry={
              connectionOperation === "logout"
                ? () => void disconnect()
                : undefined
            }
          />
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
                  "[data-input-editor], #action-message, .state-change-prepare, #panel-comparison",
                )
              )
                dirty.current.add(step);
            }}
          >
            <WorkspaceHeader
              tabs={
                <nav
                  ref={workspaceTabs}
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
                className="reference-toolbar"
                aria-label="取得済みの情報を参照"
              >
                <button onClick={() => setReference("diagram")}>
                  関係図を見る
                </button>
                <button
                  onClick={() =>
                    setReference(
                      step === "comparison"
                        ? "comparison"
                        : step === "investigation"
                          ? "answer"
                          : step === "evidence"
                            ? evidenceKind
                            : "graph",
                    )
                  }
                >
                  根拠を見る
                </button>
              </div>
              {economicPrepared && step !== "execution" && (
                <button onClick={() => openPrepared(economicPrepared)}>
                  保存した変更要求を開く
                </button>
              )}
              <div
                id="panel-graph"
                role="tabpanel"
                aria-labelledby="tab-graph"
                hidden={step !== "graph"}
              >
                <EquipmentInvestigation
                  key={equipment?.equipment_id ?? "none"}
                  root={equipment}
                  direction={direction}
                  onDirection={setDirection}
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
                    setReference("graph");
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
                      画面で選択中の設備：
                      {equipment
                        ? `${equipment.equipment_name} · ${equipment.equipment_code}`
                        : "未選択（設備名・コードを質問に含めてください）"}
                    </p>
                    <p>
                      設備名・コードと、調べたい内容を質問してください。必要な確認もこの会話で行います。
                    </p>
                    {questionSelection && (
                      <p>
                        比較タブで選択した登録入力と期間を引き継いでいます。送信すると同じ条件で再比較します。質問文を編集すると通常の質問に切り替わります。
                      </p>
                    )}
                    <form onSubmit={investigate}>
                      <label htmlFor="message">
                        関係や影響について質問する
                      </label>
                      <textarea
                        id="message"
                        ref={messageInput}
                        value={message}
                        onChange={(event) => {
                          if (busy) {
                            current.current++;
                            abort.current?.abort();
                            setBusy(false);
                            setActiveOperation(null);
                          }
                          setMessage(event.target.value);
                          setQuestionSelection(null);
                        }}
                        placeholder="例：m204停止の影響範囲はどこまでか？"
                        rows={3}
                      />
                      <button
                        className="primary"
                        aria-describedby="question-submit-reason"
                        aria-busy={busy}
                        disabled={busy || !message.trim()}
                      >
                        送信
                      </button>
                      <p id="question-submit-reason" role="status">
                        {busy
                          ? "質問への応答を待っています。完了するまで再送できません。"
                          : !message.trim()
                            ? "質問が未入力のため送信できません。質問を入力してください。"
                            : "質問に設備名・コードを書いてください。対象を省略した場合は会話でお尋ねします。"}
                      </p>
                    </form>
                  </div>
                  <div className="question-response">
                    {busy && (
                      <p role="status">
                        登録情報を調べています。完了まで再送せずお待ちください。
                      </p>
                    )}
                    {error && (
                      <div>
                        <p role="alert">
                          {explanation(error.split(" / ")[0])}{" "}
                          質問を保ったまま再試行できます。
                        </p>
                        <details>
                          <summary>技術情報：質問の取得失敗</summary>
                          <p>{error}</p>
                        </details>
                      </div>
                    )}
                    {result && (
                      <section>
                        <h2>回答</h2>
                        {answerEpoch !== executionEpoch ? (
                          <p className="notice">
                            更新前の回答です。登録値の変更後は、質問を再送して確認してください。
                          </p>
                        ) : stale ? (
                          <p className="notice">
                            前回取得した回答です。今回の質問への回答はまだ取得できていません。
                          </p>
                        ) : null}
                        {result.status === "partial" && (
                          <span className="badge warning">
                            一部の情報・評価が不足しています
                          </span>
                        )}
                        {object(result.data.answer_sections) ? (
                          <div role="log" aria-label="質問と回答">
                            {questionTurns.map((turn, index) => (
                              <article key={index}>
                                <p>質問：{turn.question}</p>
                                <p className="answer">{turn.answer}</p>
                              </article>
                            ))}
                          </div>
                        ) : (
                          <p className="answer">{result.answer}</p>
                        )}
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
                            stale={stale || answerEpoch !== executionEpoch}
                          />
                        ) : row.tool === "get_capacity_input" ? (
                          <CapacityResult
                            key={index}
                            data={row.data}
                            stale={stale || answerEpoch !== executionEpoch}
                          />
                        ) : row.tool === "get_safety_input" ? (
                          <SafetyResult
                            key={index}
                            data={row.data}
                            stale={stale || answerEpoch !== executionEpoch}
                          />
                        ) : row.tool === "get_maintenance_input" ? (
                          <MaintenanceResult
                            key={index}
                            data={row.data}
                            stale={stale || answerEpoch !== executionEpoch}
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
                  names={entityNames}
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
                  onInvestigate={(text, selection) => {
                    draftInvestigation(text, false);
                    setQuestionSelection(selection ?? null);
                    setStep("investigation");
                  }}
                />
                <button onClick={() => setStep("prepare")}>
                  不足している入力を登録・訂正する
                </button>
                <button
                  onClick={() => {
                    setReference("comparison");
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
                {evidenceKind === "documents" && (
                  <section aria-label="関連文書の検索">
                    <h2>関連文書を検索する</h2>
                    <p>
                      検索対象：
                      {equipment
                        ? `${equipment.equipment_name} · ${equipment.equipment_code}`
                        : "左の検索から設備を選んでください。"}
                    </p>
                    <button
                      disabled={documentBusy || !equipment}
                      aria-busy={documentBusy}
                      onClick={() => void searchDocuments()}
                    >
                      選択設備の関連文書を検索
                    </button>
                    {documentBusy && (
                      <p role="status">
                        関連文書を検索しています。完了まで検索を再送できません。
                      </p>
                    )}
                    <ReadFeedback
                      problem={documentError}
                      operation="文書検索"
                      onRetry={() => void searchDocuments()}
                    />
                  </section>
                )}
                <h2 ref={documentHeading} tabIndex={-1}>
                  {evidenceKind === "graph"
                    ? "調査の出典と経路"
                    : evidenceKind === "comparison"
                      ? "比較の出典と経路"
                      : "関連文書の検索結果"}
                </h2>
                {evidenceResult ? (
                  <>
                    {(evidenceKind === "comparison"
                      ? comparisonStale
                      : evidenceKind === "graph"
                        ? stale || model.stale
                        : false) && (
                      <p className="notice">
                        更新前の取得結果です。対象の情報を再取得してください。
                      </p>
                    )}
                    {evidenceKind === "documents" && (
                      <>
                        {(documentBusy || documentError) && (
                          <p className="notice">
                            前回取得した検索結果です。今回の再検索は完了していません。
                          </p>
                        )}
                        <DocumentSearchStatus
                          observation={documentObservation}
                          executionEpoch={executionEpoch}
                        />
                        <p>
                          検索で得た文書抜粋です。安全性や費用の確定判断ではありません。
                        </p>
                      </>
                    )}
                    <EvidencePanel
                      result={evidenceResult}
                      documentsOnly={evidenceKind === "documents"}
                    />
                  </>
                ) : (
                  <p>
                    {evidenceKind === "graph"
                      ? "調査の根拠は未取得です。左から設備を選び、接続及び影響範囲を取得してください。"
                      : evidenceKind === "comparison"
                        ? "比較の根拠は未取得です。対応案を比べるタブで比較を実行してください。"
                        : documentBusy
                          ? "検索結果を待っています。"
                          : documentError
                            ? "検索に失敗しました。上の説明を確認し、再試行してください。"
                            : "まだ文書を検索していません。上のボタンから検索してください。"}
                  </p>
                )}
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
                  <InputAssistance
                    executionEpoch={executionEpoch}
                    key={
                      "economic:" + (decisionEquipment?.equipment_id ?? "none")
                    }
                    kind="economic"
                    equipment={decisionEquipment}
                  >
                    <EconomicPanel
                      initiallyOpen
                      key={
                        "economic:" +
                        (decisionEquipment?.equipment_id ?? "none")
                      }
                      equipment={decisionEquipment}
                      onPrepared={prepareInput}
                      onOpenPrepared={openPrepared}
                      onInvestigate={(text) => {
                        draftInvestigation(text, false);
                        setStep("investigation");
                      }}
                      executionEpoch={executionEpoch}
                    />
                  </InputAssistance>
                </div>
                <div hidden={inputTab !== "capacity"}>
                  <InputAssistance
                    executionEpoch={executionEpoch}
                    key={
                      "capacity:" + (decisionEquipment?.equipment_id ?? "none")
                    }
                    kind="capacity"
                    equipment={decisionEquipment}
                  >
                    <CapacityPanel
                      initiallyOpen
                      key={
                        "capacity:" +
                        (decisionEquipment?.equipment_id ?? "none")
                      }
                      equipment={decisionEquipment}
                      onPrepared={prepareInput}
                      onOpenPrepared={openPrepared}
                      onInvestigate={(text) => {
                        draftInvestigation(text, false);
                        setStep("investigation");
                      }}
                      executionEpoch={executionEpoch}
                    />
                  </InputAssistance>
                </div>
                <div hidden={inputTab !== "safety"}>
                  <InputAssistance
                    executionEpoch={executionEpoch}
                    key={
                      "safety:" + (decisionEquipment?.equipment_id ?? "none")
                    }
                    kind="safety"
                    equipment={decisionEquipment}
                  >
                    <SafetyPanel
                      initiallyOpen
                      key={
                        "safety:" + (decisionEquipment?.equipment_id ?? "none")
                      }
                      equipment={decisionEquipment}
                      onPrepared={prepareInput}
                      onOpenPrepared={openPrepared}
                      onInvestigate={(text) => {
                        draftInvestigation(text, false);
                        setStep("investigation");
                      }}
                      executionEpoch={executionEpoch}
                    />
                  </InputAssistance>
                </div>
                <div hidden={inputTab !== "maintenance"}>
                  <InputAssistance
                    executionEpoch={executionEpoch}
                    key={
                      "maintenance:" +
                      (decisionEquipment?.equipment_id ?? "none")
                    }
                    kind="maintenance"
                    equipment={decisionEquipment}
                  >
                    <MaintenancePanel
                      initiallyOpen
                      key={
                        "maintenance:" +
                        (decisionEquipment?.equipment_id ?? "none")
                      }
                      equipment={decisionEquipment}
                      onPrepared={prepareInput}
                      onOpenPrepared={openPrepared}
                      onInvestigate={(text) => {
                        draftInvestigation(text, false);
                        setStep("investigation");
                      }}
                      executionEpoch={executionEpoch}
                    />
                  </InputAssistance>
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
                    {!stateChoice && (
                      <p className="notice">
                        変更後の登録状態を選ぶと、変更指示の下書きを作れます。
                      </p>
                    )}
                    <button
                      disabled={!stateChoice}
                      onClick={() => {
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
                  requestedOpen={requestedOpen}
                  actor={identity}
                  actorRole={actorRole}
                  names={entityNames}
                  onSaved={setSavedRequest}
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
              {reference && (
                <ReferenceDrawer
                  title={
                    reference === "diagram"
                      ? "関係図の参照"
                      : reference === "graph"
                        ? "調査の根拠の参照"
                        : reference === "comparison"
                          ? "比較の根拠の参照"
                          : reference === "answer"
                            ? "回答の根拠の参照"
                            : "関連文書の参照"
                  }
                  onClose={() => setReference(null)}
                >
                  <p>
                    調査起点：
                    {equipment
                      ? `${equipment.equipment_name} · ${equipment.equipment_code}`
                      : "未選択"}
                  </p>
                  {reference === "diagram" ? (
                    approvalReferenceWarning ? (
                      <p className="notice">{approvalReferenceWarning}</p>
                    ) : (
                      <>
                        <p>
                          {referenceTime(model.states[direction]?.value)}
                          {model.stale ? " ／ 更新前" : ""}
                        </p>
                        {step === "execution" && (
                          <p className="notice">
                            要求対象と一致する設備の参考図です。保存された変更内容の一部ではありません。
                          </p>
                        )}
                        <EquipmentInvestigation
                          root={equipment}
                          model={model}
                          direction={direction}
                          onDirection={setDirection}
                          graphMemory={graphMemory}
                          onGraphMemory={(key, value) =>
                            setGraphMemory((old) => ({ ...old, [key]: value }))
                          }
                          referenceOnly
                          onRootChange={chooseRoot}
                          onUseEquipment={() => {}}
                          onRegister={() => {}}
                          onObservations={setGraphResult}
                        />
                      </>
                    )
                  ) : (
                    <>
                      <p>
                        対象結果：
                        {reference === "graph"
                          ? "調査"
                          : reference === "comparison"
                            ? "対応案の比較"
                            : reference === "answer"
                              ? "質問への回答"
                              : "関連文書の検索"}
                      </p>
                      {reference === "documents" && referenceResult && (
                        <DocumentSearchStatus
                          observation={documentObservation}
                          executionEpoch={executionEpoch}
                        />
                      )}
                      {reference !== "documents" && (
                        <p>
                          {referenceTime(referenceResult)}
                          {(
                            reference === "comparison"
                              ? comparisonStale
                              : reference === "graph"
                                ? model.stale
                                : reference === "answer"
                                  ? stale
                                  : false
                          )
                            ? " ／ 更新前"
                            : ""}
                        </p>
                      )}
                      {step === "execution" && (
                        <p className="notice">
                          調査・比較の参考情報です。変更要求の保存内容の根拠ではありません。
                        </p>
                      )}
                      {referenceResult ? (
                        <EvidencePanel
                          result={referenceResult}
                          documentsOnly={reference === "documents"}
                        />
                      ) : (
                        <p>この結果の根拠は未取得です。</p>
                      )}
                    </>
                  )}
                </ReferenceDrawer>
              )}
            </WorkspaceHeader>
          </main>
        </div>
      )}
    </>
  );
}
