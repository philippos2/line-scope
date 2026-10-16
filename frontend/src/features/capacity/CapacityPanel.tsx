import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  object,
  request,
  type Envelope,
  type JsonObject,
} from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { CapacityEditor } from "./CapacityEditor";
import { CapacityResult } from "./CapacityResult";
import { blankInput, readInput, type CapacityInput } from "./model";

export function CapacityPanel({
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
  const [query, setQuery] = useState("");
  const [code, setCode] = useState("");
  const [rows, setRows] = useState<JsonObject[]>([]);
  const [result, setResult] = useState<Envelope | null>(null);
  const [editor, setEditor] = useState<{
    input: CapacityInput;
    equipmentLabel: string;
    productLabel: string;
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
  function edit(value: CapacityInput) {
    closeEditor();
    editorAbort.current = new AbortController();
    setEditor({
      input: value,
      equipmentLabel:
        value.capacity_input_id && object(result?.data.labels)
          ? `${result.data.labels.equipment_name}（${result.data.labels.equipment_code}）`
          : equipment
            ? `${equipment.equipment_name}（${equipment.equipment_code}）`
            : value.equipment_id,
      productLabel:
        value.capacity_input_id && object(result?.data.labels)
          ? `${result.data.labels.product_name}（${result.data.labels.product_code}）`
          : "",
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
          };
    const cursor = next && page ? page.cursor : null;
    setRows([]);
    setPage(null);
    void run(async (signal) => {
      const value = await request(
        "",
        "/capacity-inputs/search",
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
        `/capacity-inputs/${encodeURIComponent(identifier)}`,
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
    <details className="capacity-panel" open={initiallyOpen || undefined}>
      <summary>正式な能力・需要・納期入力</summary>
      <p>
        登録済みの能力・負荷・期限を探して確認します。登録・訂正には工場管理者による要求と別の工場管理者の承認が必要です。
      </p>
      <form onSubmit={search}>
        <label>
          能力入力の設備名・コード
          <input
            value={query}
            maxLength={100}
            disabled={busy}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label>
          能力入力コード
          <input
            value={code}
            maxLength={100}
            disabled={busy}
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <button disabled={busy}>登録済み能力入力を検索</button>
      </form>
      {busy && <p role="status">能力入力を取得中…</p>}
      {error && (
        <p role="alert">
          {error}。登録値を取得できません。仮値による補完は行っていません。
        </p>
      )}
      <section aria-label="能力入力の検索候補">
        {rows.map((row, index) => (
          <button
            className="object"
            key={index}
            disabled={busy || typeof row.capacity_input_id !== "string"}
            onClick={() => load(String(row.capacity_input_id))}
          >
            {String(row.input_code)} / {String(row.equipment_name)}（
            {String(row.equipment_code)}）/ version {String(row.version)}
          </button>
        ))}
        {page && (
          <button disabled={busy} onClick={() => search(undefined, true)}>
            次の能力入力候補を取得
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
          <CapacityResult
            data={result.data}
            stale={observedEpoch !== executionEpoch}
          />
          <div className="presets">
            <button
              disabled={busy}
              onClick={() => load(selected.capacity_input_id)}
            >
              登録値を再取得
            </button>
            <button
              disabled={busy || observedEpoch !== executionEpoch}
              onClick={() => edit(selected)}
            >
              この能力入力の訂正を準備
            </button>
            <button
              disabled={busy || observedEpoch !== executionEpoch}
              onClick={() =>
                onInvestigate(
                  `能力入力ID ${selected.capacity_input_id} の登録済み能力・不足量・条件付き復旧期限と出典・評価期間・version・不明事項を確認してください。変更要求は作成しないでください。`,
                )
              }
            >
              この能力入力をAgentへ問い合わせる
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
        選択設備の能力入力を登録
      </button>
      {editor && (
        <>
          <CapacityEditor
            key={editor.key}
            initial={editor.input}
            equipmentLabel={editor.equipmentLabel}
            productLabel={editor.productLabel}
            signal={editor.signal}
            onPrepared={onPrepared}
          />
          <button onClick={closeEditor}>編集を閉じる</button>
        </>
      )}
    </details>
  );
}
