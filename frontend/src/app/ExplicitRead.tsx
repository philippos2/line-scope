import { useEffect, useRef, useState } from "react";
import { ApiError, object, request, type Envelope } from "../api/client";
import type { EquipmentCandidate } from "../features/equipment/EquipmentCandidates";
import { searchEquipment } from "../features/investigation/readModel";
import {
  ReadFeedback,
  readProblem,
  type ReadProblem,
} from "../features/inputs/ReadFeedback";
import { RegisteredAnswer } from "./RegisteredAnswer";

type Entry = {
  key: string;
  label: string;
  description: string;
  min_targets: number;
  max_targets: number;
  action: "EXECUTE" | "OPEN_WORKSPACE";
  destination?: string;
};
type Catalog = { version: string; entries: Entry[] };
function catalogOf(response: Envelope): Catalog {
  const value = response.data.read_catalog;
  if (
    !object(value) ||
    typeof value.version !== "string" ||
    !Array.isArray(value.entries) ||
    !value.entries.every(
      (e) =>
        object(e) &&
        typeof e.key === "string" &&
        typeof e.label === "string" &&
        typeof e.description === "string" &&
        typeof e.min_targets === "number" &&
        typeof e.max_targets === "number" &&
        ["EXECUTE", "OPEN_WORKSPACE"].includes(String(e.action)),
    )
  )
    throw new ApiError("INVALID_RESPONSE");
  return value as Catalog;
}
export function ExplicitRead({
  question,
  equipment,
  connected,
  executionEpoch = 0,
  availableCatalog,
  suggestions,
  onInvalidateSuggestions,
  onNavigate,
}: {
  question: string;
  equipment: EquipmentCandidate | null;
  connected: boolean;
  executionEpoch?: number;
  availableCatalog?: Envelope;
  suggestions?: Envelope;
  onInvalidateSuggestions?: () => void;
  onNavigate: (destination: string, equipment: EquipmentCandidate) => void;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [key, setKey] = useState("");
  const [targets, setTargets] = useState<EquipmentCandidate[]>([]);
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<EquipmentCandidate[]>([]);
  const [searchStatus, setSearchStatus] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<ReadProblem | null>(null);
  const [operation, setOperation] = useState("");
  const [result, setResult] = useState<Envelope | null>(null);
  const [resultEpoch, setResultEpoch] = useState(0);
  const active = useRef<AbortController | null>(null);
  const lock = useRef(false);
  useEffect(() => {
    active.current?.abort();
    lock.current = false;
    setBusy(null);
    setProblem(null);
    setResult(null);
    setKey("");
    setTargets([]);
    setCandidates([]);
    setSearchStatus("");
    if (!connected) setCatalog(null);
    return () => active.current?.abort();
  }, [question, connected]);
  useEffect(() => {
    if (!availableCatalog) return;
    try {
      const received = catalogOf(availableCatalog);
      setCatalog((current) => current ?? received);
    } catch (error) {
      setProblem(readProblem(error));
    }
  }, [availableCatalog]);
  const entry = catalog?.entries.find((e) => e.key === key);
  const reason =
    key === "__none__"
      ? "参照は行いません。補助入力は保持しています。項目一覧から選び直せます。"
      : !connected
        ? "接続が必要です。"
        : busy
          ? `${busy}しています。完了まで再送できません。`
          : !entry
            ? "調べる項目を選んでください。"
            : targets.length < entry.min_targets ||
                targets.length > entry.max_targets
              ? `対象を${entry.min_targets}〜${entry.max_targets}件選んでください。`
              : "選んだ対象と項目だけを調べます。元の質問への回答ではありません。";
  async function run(
    name: string,
    work: (signal: AbortSignal) => Promise<void>,
  ) {
    if (!connected || lock.current) return;
    const controller = new AbortController();
    active.current = controller;
    lock.current = true;
    setBusy(name);
    setOperation(name);
    setProblem(null);
    try {
      await work(controller.signal);
    } catch (error) {
      if (!controller.signal.aborted) setProblem(readProblem(error));
    } finally {
      if (!controller.signal.aborted) {
        lock.current = false;
        setBusy(null);
      }
    }
  }
  function add(target: EquipmentCandidate) {
    onInvalidateSuggestions?.();
    setProblem(null);
    setTargets((values) =>
      values.some((v) => v.equipment_id === target.equipment_id)
        ? values
        : [...values, target].slice(0, 4),
    );
  }
  async function load() {
    onInvalidateSuggestions?.();
    await run("照会項目を取得", async (signal) => {
      const response = await request(
        "",
        "/agent",
        {
          message: question || "登録情報を選んで調べる",
          read_selection: { operation: "CATALOG" },
        },
        signal,
      );
      if (!signal.aborted) {
        setCatalog(catalogOf(response));
        setKey("");
      }
    });
  }
  async function search() {
    onInvalidateSuggestions?.();
    await run("設備候補を検索", async (signal) => {
      const found = await searchEquipment(query, signal);
      if (signal.aborted) return;
      setCandidates(found.items);
      setSearchStatus(
        found.errors.length
          ? "一部の設備候補を取得できません。未取得を0件とは判断していません。"
          : found.more
            ? "検索の続きがあります。名称・コードで絞れます。"
            : `${found.items.length}件の候補です。対象を明示して選んでください。`,
      );
    });
  }
  async function execute() {
    if (
      !entry ||
      !catalog ||
      busy ||
      targets.length < entry.min_targets ||
      targets.length > entry.max_targets
    )
      return;
    if (entry.action === "OPEN_WORKSPACE") {
      if (targets.length === 1 && entry.destination)
        onNavigate(entry.destination, targets[0]);
      return;
    }
    await run("選択した登録情報を取得", async (signal) => {
      const value = await request(
        "",
        "/agent",
        {
          message: question || "登録情報を選んで調べる",
          read_selection: {
            operation: "EXECUTE",
            catalog_version: catalog.version,
            key: entry.key,
            targets: targets.map((t) => ({
              entity_type: "Equipment",
              entity_id: t.equipment_id,
            })),
          },
        },
        signal,
      );
      if (!signal.aborted) {
        const selected = value.data.read_selection;
        const expectedIds = targets.map((t) => t.equipment_id).sort();
        if (
          !object(selected) ||
          selected.key !== entry.key ||
          selected.catalog_version !== catalog.version ||
          selected.original_question !==
            (question || "登録情報を選んで調べる") ||
          !Array.isArray(selected.targets) ||
          selected.targets.length !== expectedIds.length ||
          selected.targets.some(
            (t) =>
              !object(t) ||
              t.entity_type !== "Equipment" ||
              typeof t.entity_id !== "string",
          ) ||
          selected.targets
            .filter(object)
            .map((t) => String(t.entity_id))
            .sort()
            .some((id, i) => id !== expectedIds[i])
        )
          throw new ApiError("INVALID_RESPONSE");
        setResult(value);
        setResultEpoch(executionEpoch);
      }
    });
  }
  const selected =
    result && object(result.data.read_selection)
      ? result.data.read_selection
      : null;
  const at =
    selected && typeof selected.observed_at === "string"
      ? new Date(selected.observed_at)
      : null;
  const proposal = suggestions?.data.read_suggestions;
  const proposalCurrent =
    object(proposal) &&
    catalog &&
    proposal.question === question &&
    proposal.catalog_version === catalog.version;
  const proposalKeys =
    proposalCurrent && Array.isArray(proposal.candidates)
      ? proposal.candidates
          .filter(object)
          .map((value) => value.key)
          .filter(
            (value): value is string =>
              typeof value === "string" &&
              catalog.entries.some((entry) => entry.key === value),
          )
      : [];
  return (
    <section className="explicit-read" aria-label="登録情報を選んで調べる">
      <h2>登録情報を選んで調べる</h2>
      <p>
        自由文からは自動回答しません。対象と参照観点を確定してから照会します。
      </p>
      <p>元の質問とは別の照会です。対象と項目を選んで実行します。</p>
      <p>元の質問：{question || "入力なし"}</p>
      {proposalCurrent && (
        <section aria-label="未確定のAI提案">
          <h3>未確定のAI提案</h3>
          <p>元の質問：{question}</p>
          <p>
            質問に回答できる保証ではありません。参照範囲を確認して選んでください。対象設備は別に検索・選択します。
          </p>
          {proposal.status === "PROPOSED" && proposalKeys.length > 0 ? (
            proposalKeys.map((value) => {
              const candidate = catalog.entries.find(
                (entry) => entry.key === value,
              )!;
              return (
                <div key={value}>
                  <p>{candidate.description}</p>
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => {
                      setKey(value);
                      setProblem(null);
                      onInvalidateSuggestions?.();
                    }}
                  >
                    候補「{candidate.label}」を選ぶ
                  </button>
                </div>
              );
            })
          ) : (
            <p>
              {proposal.status === "NO_CANDIDATE"
                ? "参照観点の候補はありません。全項目から選ぶか、該当する観点がないを選べます。"
                : "AIの候補を利用できません。全項目から手動で選べます。"}
            </p>
          )}
          <p>
            候補を選ぶだけでは照会しません。対象・項目を確定して実行してください。
          </p>
        </section>
      )}
      <button
        type="button"
        disabled={!connected || !!busy}
        aria-busy={busy === "照会項目を取得"}
        onClick={() => void load()}
      >
        照会項目を取得
      </button>
      <label>
        調べる項目
        <select
          aria-label="調べる項目"
          value={key}
          disabled={!!busy}
          onChange={(e) => {
            onInvalidateSuggestions?.();
            setKey(e.target.value);
            setProblem(null);
          }}
        >
          <option value="">選んでください</option>
          <option value="__none__">該当する観点がない</option>
          {catalog?.entries.map((e) => (
            <option key={e.key} value={e.key}>
              {e.label}
            </option>
          ))}
        </select>
      </label>
      {catalog && (
        <>
          {entry && <p>{entry.description}</p>}
          {equipment && (
            <button
              type="button"
              disabled={
                !!busy ||
                targets.length >= 4 ||
                targets.some((t) => t.equipment_id === equipment.equipment_id)
              }
              onClick={() => add(equipment)}
            >
              画面の設備「{equipment.equipment_name} ·{" "}
              {equipment.equipment_code}」を対象に追加
            </button>
          )}
          <label>
            照会対象の設備名・コード
            <input
              disabled={!!busy}
              value={query}
              onChange={(e) => {
                onInvalidateSuggestions?.();
                setQuery(e.target.value);
              }}
            />
          </label>
          <button type="button" disabled={!!busy} onClick={() => void search()}>
            照会対象の候補を検索
          </button>
          <p role="status">{searchStatus}</p>
          {candidates.map((candidate) => (
            <button
              type="button"
              key={candidate.equipment_id}
              disabled={
                !!busy ||
                targets.length >= 4 ||
                targets.some((t) => t.equipment_id === candidate.equipment_id)
              }
              onClick={() => add(candidate)}
            >
              {candidate.equipment_name} · {candidate.equipment_code}を追加
            </button>
          ))}
          <ul aria-label="照会対象">
            {targets.map((target) => (
              <li key={target.equipment_id}>
                {target.equipment_name} · {target.equipment_code}
                <button
                  type="button"
                  disabled={!!busy}
                  onClick={() => {
                    onInvalidateSuggestions?.();
                    setProblem(null);
                    setTargets((items) =>
                      items.filter(
                        (t) => t.equipment_id !== target.equipment_id,
                      ),
                    );
                  }}
                >
                  対象から外す
                </button>
              </li>
            ))}
          </ul>
          {targets.length === 4 && <p>対象の選択上限は4件です。</p>}
          <button
            type="button"
            disabled={
              !connected ||
              !!busy ||
              !entry ||
              targets.length < entry.min_targets ||
              targets.length > entry.max_targets
            }
            aria-busy={busy === "選択した登録情報を取得"}
            onClick={() => void execute()}
          >
            {entry?.action === "OPEN_WORKSPACE"
              ? "選んだ対象で画面を開く"
              : "この項目を調べる"}
          </button>
        </>
      )}
      <p role="status">{reason}</p>
      <ReadFeedback
        problem={problem}
        operation={operation}
        onRetry={
          operation === "照会項目を取得"
            ? () => void load()
            : operation === "設備候補を検索"
              ? () => void search()
              : () => void execute()
        }
      />
      {problem && result && (
        <p>前回の選択照会の結果です。今回の取得は未完了です。</p>
      )}
      {result && selected && (
        <section aria-label="選択した照会の結果">
          <h3>選択した照会の結果</h3>
          {resultEpoch !== executionEpoch && (
            <p className="notice">
              更新前の結果です。選択した登録情報を再取得してください。
            </p>
          )}
          <p>元の質問：{String(selected.original_question ?? "")}</p>
          <p>項目：{String(selected.label ?? "")}</p>
          <p>
            対象：
            {Array.isArray(selected.target_labels)
              ? selected.target_labels.join("、")
              : "取得結果を参照してください"}
          </p>
          <p>
            取得時刻：
            {at && Number.isFinite(at.getTime())
              ? at.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" }) +
                "（日本時間）"
              : "未確認"}
          </p>
          <p>元の質問への回答ではなく、選択した項目の照会結果です。</p>
          <RegisteredAnswer response={result} />
        </section>
      )}
    </section>
  );
}
