import {
  EquipmentQueryInput,
  SuggestedInput,
  InputAssistance,
} from "../inputs/InputAssistance";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  object,
  request,
  type Envelope,
  type JsonObject,
} from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { EconomicEditor } from "./EconomicEditor";
import { EconomicResult } from "./EconomicResult";
import { blankInput, readInput, type EconomicInput } from "./model";

export function EconomicPanel({
  equipment,
  onPrepared,
  onOpenPrepared,
  onInvestigate,
  executionEpoch,
  initiallyOpen = false,
}: {
  equipment: EquipmentCandidate | null;
  onPrepared: (id: string) => void;
  onOpenPrepared?: (id: string) => void;
  onInvestigate: (message: string) => void;
  executionEpoch: number;
  initiallyOpen?: boolean;
}) {
  const [searched, setSearched] = useState(false);
  const [query, setQuery] = useState("");
  const [code, setCode] = useState("");
  const [rows, setRows] = useState<JsonObject[]>([]);
  const [result, setResult] = useState<Envelope | null>(null);
  const [editor, setEditor] = useState<{
    input: EconomicInput;
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
  function edit(value: EconomicInput) {
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
          };
    const cursor = next && page ? page.cursor : null;
    setRows([]);
    setPage(null);
    void run(async (signal) => {
      const value = await request(
        "",
        "/economic-inputs/search",
        { filter, page_size: 20, cursor },
        signal,
      );
      if (signal.aborted) return;
      if (!Array.isArray(value.data.items) || !value.data.items.every(object))
        throw new ApiError("INVALID_RESPONSE");
      setRows(value.data.items);
      setSearched(true);
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
        `/economic-inputs/${encodeURIComponent(identifier)}`,
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
    <details className="economic-panel" open={initiallyOpen || undefined}>
      <summary>正式な経済・損失入力</summary>
      <p>
        登録済みの費用・損失を探して確認します。登録・訂正には工場管理者による要求と別の工場管理者の承認が必要です。
      </p>
      <form onSubmit={search}>
        <label>
          経済入力の設備名・コード
          <EquipmentQueryInput
            aria-label="経済入力の設備名・コード"
            value={query}
            maxLength={100}
            disabled={busy}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label>
          経済入力コード
          <SuggestedInput
            field="input_code"
            value={code}
            maxLength={100}
            disabled={busy}
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <button disabled={busy}>登録済み経済入力を検索</button>
      </form>
      {busy && <p role="status">経済入力を取得中…</p>}
      {error && (
        <p role="alert">
          {error}。登録値を取得できません。仮値による補完は行っていません。
        </p>
      )}
      <section aria-label="経済入力の検索候補">
        {rows.map((row, index) => (
          <button
            className="object"
            key={index}
            disabled={busy || typeof row.economic_input_id !== "string"}
            onClick={() => load(String(row.economic_input_id))}
          >
            {String(row.input_code)} / {String(row.equipment_name)}（
            {String(row.equipment_code)}）/ version {String(row.version)}
          </button>
        ))}
        {page && (
          <button disabled={busy} onClick={() => search(undefined, true)}>
            次の経済入力候補を取得
          </button>
        )}
      </section>
      {!busy && !error && rows.length === 0 && (
        <p>
          {searched
            ? "該当する登録データはありません。条件を変えて検索するか、新規登録できます。"
            : "まだ検索していません。条件を指定して登録データを検索してください。"}
        </p>
      )}
      {result && selected && (
        <>
          <EconomicResult
            data={result.data}
            stale={observedEpoch !== executionEpoch}
          />
          <div className="presets">
            <button
              disabled={busy}
              onClick={() => load(selected.economic_input_id)}
            >
              登録値を再取得
            </button>
            <button
              disabled={busy || observedEpoch !== executionEpoch}
              onClick={() => edit(selected)}
            >
              この経済入力の訂正を準備
            </button>
            <button
              disabled={busy || observedEpoch !== executionEpoch}
              onClick={() =>
                onInvestigate(
                  `経済入力ID ${selected.economic_input_id} の登録済み費用と出典・比較期間・version・不明事項を確認してください。変更要求は作成しないでください。`,
                )
              }
            >
              この経済入力をAgentへ問い合わせる
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
        選択設備の経済入力を登録
      </button>
      {editor && (
        <>
          <InputAssistance
            executionEpoch={executionEpoch}
            kind="economic"
            key={editor.key}
            equipment={{
              equipment_id: editor.input.equipment_id,
              equipment_code:
                equipment?.equipment_id === editor.input.equipment_id
                  ? equipment.equipment_code
                  : String(
                      rows.find(
                        (row) =>
                          row.economic_input_id ===
                          editor.input.economic_input_id,
                      )?.equipment_code ?? "",
                    ),
              equipment_name:
                equipment?.equipment_id === editor.input.equipment_id
                  ? equipment.equipment_name
                  : String(
                      rows.find(
                        (row) =>
                          row.economic_input_id ===
                          editor.input.economic_input_id,
                      )?.equipment_name ?? "登録データの対象設備",
                    ),
            }}
          >
            <EconomicEditor
              key={editor.key}
              initial={editor.input}
              equipmentLabel={
                equipment?.equipment_id === editor.input.equipment_id
                  ? `${equipment.equipment_name} · ${equipment.equipment_code}`
                  : "登録データの対象設備"
              }
              signal={editor.signal}
              onPrepared={onPrepared}
              onOpenPrepared={onOpenPrepared}
            />
          </InputAssistance>
          <button onClick={closeEditor}>編集を閉じる</button>
        </>
      )}
    </details>
  );
}
