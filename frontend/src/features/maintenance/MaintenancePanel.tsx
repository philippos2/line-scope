import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  object,
  request,
  type Envelope,
  type JsonObject,
} from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { MaintenanceEditor } from "./MaintenanceEditor";
import { MaintenanceResult } from "./MaintenanceResult";
import { blankInput, readInput, kinds, type MaintenanceInput } from "./model";

export function MaintenancePanel({
  equipment,
  onPrepared,
  onInvestigate,
  executionEpoch,
  initiallyOpen = false,
}: {
  equipment: EquipmentCandidate | null;
  onPrepared: (id: string) => void;
  onInvestigate: (message: string) => void;
  executionEpoch: number;
  initiallyOpen?: boolean;
}) {
  const [kind, setKind] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [query, setQuery] = useState("");
  const [code, setCode] = useState("");
  const [rows, setRows] = useState<JsonObject[]>([]);
  const [result, setResult] = useState<Envelope | null>(null);
  const [editor, setEditor] = useState<{
    input: MaintenanceInput;
    signal: AbortSignal;
    key: number;
  } | null>(null);
  const [page, setPage] = useState<{
    cursor: string;
    filter: JsonObject;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [observedEpoch, setObservedEpoch] = useState(executionEpoch);
  const editorSequence = useRef(0);
  const active = useRef<AbortController | null>(null);
  const editorAbort = useRef<AbortController | null>(null);
  const pending = useRef(false);
  useEffect(
    () => () => {
      active.current?.abort();
      editorAbort.current?.abort();
    },
    [],
  );
  function closeEditor() {
    editorAbort.current?.abort();
    editorAbort.current = null;
    setEditor(null);
  }
  function edit(value: MaintenanceInput) {
    closeEditor();
    editorAbort.current = new AbortController();
    setEditor({
      input: value,
      signal: editorAbort.current.signal,
      key: ++editorSequence.current,
    });
  }
  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (pending.current) return;
    const controller = new AbortController();
    active.current = controller;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await action(controller.signal);
    } catch (caught) {
      if (!controller.signal.aborted)
        setError(caught instanceof ApiError ? caught.code : "INVALID_RESPONSE");
    } finally {
      pending.current = false;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  function search(event?: FormEvent, next = false) {
    event?.preventDefault();
    closeEditor();
    setResult(null);
    const filter =
      next && page
        ? page.filter
        : {
            ...(query.trim() ? { equipment_query: query.trim() } : {}),
            ...(code.trim() ? { input_code: code.trim() } : {}),
            ...(kind ? { kind } : {}),
            ...(periodStart ? { period_start: periodStart } : {}),
            ...(periodEnd ? { period_end: periodEnd } : {}),
          };
    const cursor = next && page ? page.cursor : null;
    setRows([]);
    setPage(null);
    void run(async (signal) => {
      const value = await request(
        "",
        "/maintenance-inputs/search",
        { filter, page_size: 20, cursor },
        signal,
      );
      if (signal.aborted) return;
      if (!Array.isArray(value.data.items) || !value.data.items.every(object))
        throw new ApiError("INVALID_RESPONSE");
      setRows(value.data.items);
      if (typeof value.data.next_cursor === "string")
        setPage({ cursor: value.data.next_cursor, filter });
    });
  }
  function load(identifier: string) {
    closeEditor();
    setResult(null);
    void run(async (signal) => {
      const value = await request(
        "",
        `/maintenance-inputs/${encodeURIComponent(identifier)}`,
        undefined,
        signal,
      );
      if (signal.aborted) return;
      readInput(value.data.input);
      setResult(value);
      setObservedEpoch(executionEpoch);
    });
  }
  const selected = result ? readInput(result.data.input) : null;
  return (
    <details className="maintenance-panel" open={initiallyOpen || undefined}>
      <summary>正式な対応計画・故障履歴入力</summary>
      <p>
        登録済みの修理・交換・暫定案と故障・修理履歴を探して確認します。登録・訂正には工場管理者による要求と別の工場管理者の承認が必要です。
      </p>
      <form onSubmit={search}>
        <label>
          対応計画・故障履歴の設備名・コード
          <input
            value={query}
            maxLength={100}
            disabled={busy}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label>
          対応計画・故障履歴コード
          <input
            value={code}
            maxLength={100}
            disabled={busy}
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <label>
          検索する記録分類
          <select
            value={kind}
            disabled={busy}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">すべて</option>
            {Object.entries(kinds).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          記録検索の期間開始
          <input
            value={periodStart}
            disabled={busy}
            onChange={(event) => setPeriodStart(event.target.value)}
          />
        </label>
        <label>
          記録検索の期間終了
          <input
            value={periodEnd}
            disabled={busy}
            onChange={(event) => setPeriodEnd(event.target.value)}
          />
        </label>
        <p>
          任意のtimezone付き日時を指定すると、評価・事象期間と重なる記録を取得します。
        </p>
        <button disabled={busy}>登録済み対応計画・故障履歴を検索</button>
      </form>
      {busy && <p role="status">対応計画・故障履歴を取得中…</p>}
      {error && (
        <p role="alert">
          {error}。登録値を取得できません。仮値による補完は行っていません。
        </p>
      )}
      <section aria-label="対応計画・故障履歴の検索候補">
        {rows.map((row, index) => (
          <button
            className="object"
            key={index}
            disabled={busy || typeof row.maintenance_input_id !== "string"}
            onClick={() => load(String(row.maintenance_input_id))}
          >
            {String(row.input_code)} / {String(row.equipment_name)}（
            {String(row.equipment_code)}）/ version {String(row.version)}
          </button>
        ))}
        {page && (
          <button disabled={busy} onClick={() => search(undefined, true)}>
            次の対応計画・故障履歴候補を取得
          </button>
        )}
      </section>
      {!busy && !error && rows.length === 0 && (
        <p>
          候補は未取得、または該当する登録がありません。別期間の入力を勝手に合算・選択しません。
        </p>
      )}
      {result && selected && (
        <>
          <MaintenanceResult
            data={result.data}
            stale={observedEpoch !== executionEpoch}
          />
          <div className="presets">
            <button
              disabled={busy}
              onClick={() => load(selected.maintenance_input_id)}
            >
              登録値を再取得
            </button>
            <button
              disabled={busy || observedEpoch !== executionEpoch}
              onClick={() => edit(selected)}
            >
              この対応計画・故障履歴の訂正を準備
            </button>
            <button
              disabled={busy || observedEpoch !== executionEpoch}
              onClick={() =>
                onInvestigate(
                  `対応計画・故障履歴ID ${selected.maintenance_input_id} の登録済み計画・実績と出典・評価期間・調達待ち・作業・停止時間・version・不明事項を確認してください。変更要求は作成しないでください。`,
                )
              }
            >
              この対応計画・故障履歴をAgentへ問い合わせる
            </button>
          </div>
        </>
      )}
      <p>
        新規登録の設備：
        {equipment
          ? `${equipment.equipment_name}（${equipment.equipment_code}）`
          : "未選択。設備を探し、候補を選択してください。"}
      </p>
      <button
        disabled={busy || !equipment}
        onClick={() => equipment && edit(blankInput(equipment.equipment_id))}
      >
        選択設備の対応計画・故障履歴を登録
      </button>
      {editor && (
        <>
          <MaintenanceEditor
            key={editor.key}
            initial={editor.input}
            signal={editor.signal}
            onPrepared={onPrepared}
          />
          <button onClick={closeEditor}>編集を閉じる</button>
        </>
      )}
    </details>
  );
}
