import { PreparedInputForm } from "../inputs/PreparedInputForm";
import {
  OperationFeedback,
  useOperationFeedback,
} from "../inputs/OperationFeedback";
import {
  PrepareInputButton,
  PreparedInputNotice,
  usePreparedInput,
} from "../inputs/PreparedInputFeedback";
import { DateTimeInput } from "../inputs/DateTimeInput";
import {
  SuggestionScope,
  SuggestedInput,
  SuggestedText,
} from "../inputs/InputAssistance";
import { useRef, useState, type FormEvent } from "react";
import { ApiError, object, request, type JsonObject } from "../../api/client";
import { rateFields, type CapacityInput } from "./model";
export function CapacityEditor({
  initial,
  onPrepared,
  onOpenPrepared,
  signal,
  equipmentLabel,
  productLabel,
}: {
  initial: CapacityInput;
  equipmentLabel: string;
  productLabel: string;
  onPrepared: (id: string) => void;
  onOpenPrepared?: (id: string) => void;
  signal: AbortSignal;
}) {
  const [value, setValue] = useState(initial),
    [query, setQuery] = useState(""),
    [products, setProducts] = useState<JsonObject[]>([]),
    [productName, setProductName] = useState(productLabel),
    [cursor, setCursor] = useState<string | null>(null),
    [searched, setSearched] = useState("");
  const [productBusy, setBusy] = useState(false),
    [error, setError] = useState("");
  const pending = useRef(false),
    retry = useRef<{ serialized: string; key: string } | null>(null);
  const body = {
    capacity_input_id: value.capacity_input_id || null,
    input: {
      input_code: value.input_code,
      equipment_id: value.equipment_id,
      product_id: value.product_id,
      payload: value.payload,
    },
    supersedes_update_request_id: null,
  };
  const operation = useOperationFeedback();
  const busy = productBusy || operation.busy;
  const uncertain = operation.problem?.kind === "unknown";
  const preparation = usePreparedInput(body);
  const { serialized, alreadyPrepared } = preparation;
  function patch(key: string, text: string) {
    setValue((previous) => ({
      ...previous,
      [key]: text,
      ...(key === "product_id"
        ? {
            payload: {
              ...previous.payload,
              source: "",
              certainty: "ESTIMATED",
            },
          }
        : {}),
    }));
  }
  function payload(key: string, text: unknown) {
    setValue((previous) => ({
      ...previous,
      payload: {
        ...previous.payload,
        ...(key !== "source" && key !== "certainty"
          ? {
              source: "",
              certainty: "ESTIMATED",
              ...([
                "period_start",
                "period_end",
                "quantity_unit",
                "required_rate",
                "normal_rate",
                "used_rate",
                "reserved_rate",
              ].includes(key)
                ? {
                    loads_independent: false,
                    loads_complete: false,
                    compatible: null,
                  }
                : {}),
            }
          : {}),
        [key]: text,
      },
    }));
  }
  function recovery(key: string, text: unknown) {
    setValue((previous) => ({
      ...previous,
      payload: {
        ...previous.payload,
        source: "",
        certainty: "ESTIMATED",
        recovery: {
          ...(object(previous.payload.recovery)
            ? previous.payload.recovery
            : {}),
          [key]: text,
        },
      },
    }));
  }
  async function findProducts(next = false) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const text = next ? searched : query;
      const result = await request(
        "",
        "/capacity-inputs/products/search",
        { query: text, cursor: next ? cursor : null },
        signal,
      );
      if (signal.aborted) return;
      if (
        !Array.isArray(result.data.items) ||
        !result.data.items.every(
          (row) =>
            object(row) &&
            typeof row.product_id === "string" &&
            typeof row.product_code === "string" &&
            typeof row.product_name === "string",
        )
      )
        throw new ApiError("INVALID_RESPONSE");
      setProducts(result.data.items as JsonObject[]);
      setSearched(text);
      setCursor(
        typeof result.data.next_cursor === "string"
          ? result.data.next_cursor
          : null,
      );
    } catch (caught) {
      if (!signal.aborted)
        setError(caught instanceof ApiError ? caught.code : "INVALID_RESPONSE");
    } finally {
      pending.current = false;
      if (!signal.aborted) setBusy(false);
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (
      busy ||
      operation.isPending() ||
      alreadyPrepared ||
      signal.aborted ||
      (uncertain && retry.current?.serialized !== serialized)
    )
      return;
    if (retry.current?.serialized !== serialized)
      retry.current = { serialized, key: crypto.randomUUID() };
    void operation.run(
      async (active) => {
        const result = await request(
          "",
          "/capacity-inputs/prepare",
          { ...body, retry_key: retry.current!.key },
          active,
        );
        if (active.aborted) return;
        const id = result.data.update_request_id;
        if (typeof id !== "string") throw new ApiError("INVALID_RESPONSE");
        preparation.remember(id, result);
        onPrepared(id);
      },
      { operation: "prepare", signal },
    );
  }
  const p = value.payload,
    r = object(p.recovery) ? p.recovery : null;
  return (
    <SuggestionScope
      label="能力入力の登録・訂正"
      value={{
        equipment_id: value.equipment_id,
        product_id: value.product_id,
        payload: value.payload,
      }}
    >
      <h2>
        {value.capacity_input_id ? "能力入力を訂正する" : "能力入力を登録する"}
      </h2>
      <p>
        同一製品・数量単位・期間の毎時率を入力します。空欄は不明、0は既知のゼロです。日時は日本時間で選択します。
      </p>
      <p>対象設備：{equipmentLabel}</p>
      <p className="muted">
        値を編集した場合は、出典と確認済みの扱いを引き継ぎません。変更内容に合う出典・確度を確認してください。
      </p>
      <PreparedInputForm onSubmit={submit}>
        <fieldset disabled={busy}>
          <legend>対象と評価期間</legend>
          <label>
            能力入力の入力コード
            <SuggestedInput
              field="input_code"
              required
              maxLength={100}
              disabled={Boolean(value.capacity_input_id)}
              value={value.input_code}
              onChange={(event) => patch("input_code", event.target.value)}
            />
          </label>
          {!value.capacity_input_id && (
            <>
              <label>
                製品名・コード
                <input
                  maxLength={100}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <button type="button" onClick={() => void findProducts()}>
                製品候補を探す
              </button>
              <section aria-label="製品の検索候補">
                {products.map((row) => (
                  <button
                    type="button"
                    key={String(row.product_id)}
                    onClick={() => {
                      patch("product_id", String(row.product_id));
                      setProductName(
                        `${row.product_name}（${row.product_code}）`,
                      );
                    }}
                  >
                    {String(row.product_name)}（{String(row.product_code)}）
                  </button>
                ))}
                {cursor && (
                  <button type="button" onClick={() => void findProducts(true)}>
                    次の製品候補
                  </button>
                )}
              </section>
            </>
          )}
          <p>
            対象製品：
            {productName ||
              (value.product_id ? "登録済みの対象製品（変更不可）" : "未選択")}
          </p>
          <label>
            能力評価開始
            <DateTimeInput
              required
              value={String(p.period_start)}
              onChange={(text) => payload("period_start", text)}
            />
          </label>
          <label>
            能力評価終了
            <DateTimeInput
              required
              value={String(p.period_end)}
              onChange={(text) => payload("period_end", text)}
            />
          </label>
          <label>
            数量単位
            <SuggestedInput
              field="payload.quantity_unit"
              required
              maxLength={40}
              placeholder="例：個"
              value={String(p.quantity_unit)}
              onChange={(event) => payload("quantity_unit", event.target.value)}
            />
          </label>
        </fieldset>
        <fieldset disabled={busy}>
          <legend>能力と負荷（数量単位/hour）</legend>
          {Object.entries(rateFields).map(([key, label]) => (
            <label key={key}>
              {label}
              <SuggestedInput
                field={`payload.${key}`}
                inputMode="decimal"
                value={typeof p[key] === "string" ? p[key] : ""}
                onChange={(event) => payload(key, event.target.value || null)}
              />
            </label>
          ))}
          <label>
            <input
              type="checkbox"
              checked={p.loads_independent === true}
              onChange={(event) =>
                payload("loads_independent", event.target.checked)
              }
            />
            使用中負荷と予約負荷に重複がないことを確認した
          </label>
          <label>
            <input
              type="checkbox"
              checked={p.loads_complete === true}
              onChange={(event) =>
                payload("loads_complete", event.target.checked)
              }
            />
            この期間の負荷を網羅した
          </label>
          <label>
            製品互換性
            <select
              value={
                p.compatible === null
                  ? "unknown"
                  : p.compatible === true
                    ? "yes"
                    : "no"
              }
              onChange={(event) =>
                payload(
                  "compatible",
                  event.target.value === "unknown"
                    ? null
                    : event.target.value === "yes",
                )
              }
            >
              <option value="unknown">不明</option>
              <option value="yes">互換性を確認済み</option>
              <option value="no">非互換</option>
            </select>
          </label>
          <SuggestedText
            label="能力入力の出典"
            field="payload.source"
            required
            maxLength={1000}
            value={String(p.source)}
            onValue={(text) => payload("source", text)}
          />
          <label>
            能力入力の確度
            <select
              value={String(p.certainty)}
              onChange={(event) => payload("certainty", event.target.value)}
            >
              <option value="ESTIMATED">推定</option>
              <option value="CONFIRMED">確定</option>
            </select>
          </label>
        </fieldset>
        <fieldset disabled={busy}>
          <legend>条件付き復旧期限</legend>
          <label>
            <input
              type="checkbox"
              checked={r !== null}
              onChange={(event) =>
                payload(
                  "recovery",
                  event.target.checked
                    ? {
                        buffer: null,
                        stopped_at: "",
                        constant_flow: false,
                        no_other_allocations: false,
                        recovery_meets_demand: false,
                      }
                    : null,
                )
              }
            />
            bufferと復旧条件を入力する
          </label>
          {r && (
            <>
              <label>
                利用可能buffer
                <SuggestedInput
                  field="payload.recovery.buffer"
                  inputMode="decimal"
                  value={typeof r.buffer === "string" ? r.buffer : ""}
                  onChange={(event) =>
                    recovery("buffer", event.target.value || null)
                  }
                />
              </label>
              <label>
                停止開始日時
                <DateTimeInput
                  required
                  value={String(r.stopped_at)}
                  onChange={(text) => recovery("stopped_at", text)}
                />
              </label>
              {Object.entries({
                constant_flow: "評価期間中の需要と供給は一定",
                no_other_allocations: "bufferの他用途への引当はない",
                recovery_meets_demand: "復旧後は必要量を満たせる",
              }).map(([key, label]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={r[key] === true}
                    onChange={(event) => recovery(key, event.target.checked)}
                  />
                  {label}
                </label>
              ))}
            </>
          )}
        </fieldset>
        <PrepareInputButton
          preparation={preparation}
          busy={busy}
          preparing={operation.busy}
          label={
            uncertain
              ? "同じ内容を再送して結果を確認"
              : "能力入力の変更準備を作成"
          }
          disabledReason={
            signal.aborted
              ? "接続または対象が変わったため、この編集画面からは送信できません。保存状態や登録内容を確認してください。"
              : uncertain && retry.current?.serialized !== serialized
                ? "送信時と入力が異なるため再送できません。元の内容へ戻してください。"
                : !value.product_id
                  ? "変更準備には対象製品の選択が必要です。"
                  : ""
          }
        />
      </PreparedInputForm>
      {error && <p role="alert">{error}</p>}
      <OperationFeedback
        problem={operation.problem}
        onRead={onOpenPrepared ?? onPrepared}
      />
      <PreparedInputNotice
        preparation={preparation}
        label="能力入力"
        onOpen={onOpenPrepared ?? onPrepared}
        equipmentLabel={equipmentLabel}
      />
    </SuggestionScope>
  );
}
