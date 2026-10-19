import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { ApiError, object, request, type JsonObject } from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { rows, searchEquipment, explanation } from "../investigation/readModel";
import { displayPeriod } from "../investigation/EquipmentInvestigation";

type Kind = "economic" | "capacity" | "safety" | "maintenance";
const Context = createContext<{
  records: JsonObject[];
  load: () => void;
  scope?: JsonObject;
}>({ records: [], load: () => {} });
export function InputAssistance({
  kind,
  equipment,
  children,
  executionEpoch = 0,
}: {
  executionEpoch?: number;
  kind: Kind;
  equipment: EquipmentCandidate | null;
  children: ReactNode;
}) {
  const [observedEpoch, setObservedEpoch] = useState(executionEpoch);
  const stale = observedEpoch !== executionEpoch;
  const [records, setRecords] = useState<JsonObject[]>([]);
  const [status, setStatus] = useState("未取得");
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  const loaded = useRef(false);
  useEffect(() => () => active.current?.abort(), []);
  async function load(force = false) {
    if (busy || (loaded.current && !force && !stale)) return;
    const controller = new AbortController();
    active.current = controller;
    loaded.current = true;
    setBusy(true);
    setStatus("入力候補を取得しています…");
    try {
      const result = await request(
        "",
        `/${kind}-inputs/search`,
        {
          filter: equipment ? { equipment_id: equipment.equipment_id } : {},
          page_size: 20,
          cursor: null,
        },
        controller.signal,
      );
      if (!Array.isArray(result.data.items) || !result.data.items.every(object))
        throw new ApiError("INVALID_RESPONSE");
      const items = rows(result.data.items);
      const details: JsonObject[] = [];
      // Bound concurrent detail reads and total work to the current page.
      for (let i = 0; i < items.length; i += 4) {
        const batch = await Promise.allSettled(
          items.slice(i, i + 4).map(async (row) => {
            const id = row[`${kind}_input_id`];
            if (typeof id !== "string") throw new ApiError("INVALID_RESPONSE");
            const full = await request(
              "",
              `/${kind}-inputs/${encodeURIComponent(id)}`,
              undefined,
              controller.signal,
            );
            if (!object(full.data.input))
              throw new ApiError("INVALID_RESPONSE");
            return { ...row, ...full.data.input };
          }),
        );
        if (controller.signal.aborted) return;
        for (const item of batch)
          if (item.status === "fulfilled") details.push(item.value);
      }
      if (controller.signal.aborted) return;
      setRecords(details);
      setObservedEpoch(executionEpoch);
      setStatus(
        details.length < items.length
          ? "一部の候補を取得できませんでした。取得済みの候補は使えます。"
          : result.data.next_cursor
            ? "先頭20件の候補です。続きは未取得です。対象を絞って検索してください。"
            : details.length
              ? `${details.length}件の登録データから入力候補を取得しました。`
              : "この対象の登録データはありません。手入力できます。",
      );
    } catch (error) {
      if (!controller.signal.aborted) {
        loaded.current = false;
        setStatus(
          `${explanation(error instanceof ApiError ? error.code : "REQUEST_FAILED")} 候補を再取得できます。`,
        );
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <Context.Provider
      value={{ records: stale ? [] : records, load: () => void load() }}
    >
      <section className="input-assistance" aria-label="入力候補の案内">
        <p>
          候補の対象：
          {equipment
            ? `${equipment.equipment_name} · ${equipment.equipment_code}`
            : "取得できる登録設備"}
        </p>
        <button type="button" disabled={busy} onClick={() => void load(true)}>
          入力候補を取得・更新
        </button>
        <p role="status">
          {stale
            ? "更新前の候補です。再取得してください。入力中の値は保持しています。"
            : status}
        </p>
        <p className="muted">
          登録済みの参考値です。適用できるかを確認して選択してください。既存コードで新規登録する場合は重複に注意してください。
        </p>
      </section>
      {children}
    </Context.Provider>
  );
}
export function SuggestionScope({
  value,
  children,
  label,
  fieldset = false,
}: {
  value: JsonObject;
  children: ReactNode;
  label?: string;
  fieldset?: boolean;
}) {
  const context = useContext(Context);
  return (
    <Context.Provider value={{ ...context, scope: value }}>
      {fieldset ? (
        <fieldset>{children}</fieldset>
      ) : label ? (
        <section aria-label={label} data-input-editor>
          {children}
        </section>
      ) : (
        children
      )}
    </Context.Provider>
  );
}
function valuesAt(value: unknown, parts: string[]): string[] {
  if (!parts.length) return typeof value === "string" && value ? [value] : [];
  const [key, ...rest] = parts;
  if (key === "*")
    return Array.isArray(value)
      ? value.flatMap((item) => valuesAt(item, rest))
      : [];
  return object(value) ? valuesAt(value[key], rest) : [];
}
function sameMoment(first: unknown, second: unknown) {
  if (
    typeof first !== "string" ||
    typeof second !== "string" ||
    Number.isNaN(Date.parse(first)) ||
    Date.parse(first) !== Date.parse(second)
  )
    return false;
  const fraction = (value: string) =>
    (value.match(/\.(\d+)/)?.[1] ?? "").padEnd(9, "0");
  return fraction(first) === fraction(second);
}
function useOptions(field: string, numeric = false) {
  const context = useContext(Context);
  const scope = context.scope;
  const payload = object(scope?.payload) ? scope.payload : {};
  const options = context.records.flatMap((record) => {
    const p = object(record.payload) ? record.payload : {};
    if (
      scope?.product_id &&
      record.product_id &&
      record.product_id !== scope.product_id
    )
      return [];
    if (numeric && record.product_id && !scope?.product_id) return [];
    if (scope?.kind && p.kind !== scope.kind) return [];
    if (
      numeric &&
      (!payload.period_start ||
        !payload.period_end ||
        !sameMoment(p.period_start, payload.period_start) ||
        !sameMoment(p.period_end, payload.period_end) ||
        ("quantity_unit" in p &&
          (!payload.quantity_unit ||
            p.quantity_unit !== payload.quantity_unit)))
    )
      return [];
    const provenance = (source: unknown) =>
      `${record.equipment_name ?? "登録設備"}／${record.input_code} 第${record.version}版／${displayPeriod(p.period_start, p.period_end)}／出典：${typeof source === "string" ? source : "記録内の出典"}`;
    if (field.startsWith("loss.")) {
      const [, productId, key] = field.split(".");
      return rows(p.incident_losses)
        .filter((item) => item.product_id === productId)
        .flatMap((item) =>
          valuesAt(item, [key]).map((value) => ({
            value,
            source: provenance(item.source),
          })),
        );
    }
    if (field.startsWith("cost.")) {
      return rows(p.options)
        .filter((option) => option.option === scope?.option)
        .flatMap((option) =>
          rows(option.items)
            .filter((item) => item.kind === scope?.cost_kind)
            .flatMap((item) =>
              valuesAt(item, [field.slice(5)]).map((value) => ({
                value,
                source: provenance(item.source),
              })),
            ),
        );
    }
    return valuesAt(record, field.split(".")).map((value) => ({
      value,
      source: provenance(p.source),
    }));
  });
  return {
    ...context,
    options: options
      .filter(
        (item, i) =>
          options.findIndex(
            (other) =>
              other.value === item.value && other.source === item.source,
          ) === i,
      )
      .slice(0, 40),
  };
}
export function SuggestedInput({
  field,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { field: string }) {
  const id = useId();
  const { options, load } = useOptions(field, props.inputMode === "decimal");
  return (
    <>
      <input
        {...props}
        list={id}
        onFocus={(event) => {
          load();
          props.onFocus?.(event);
        }}
      />
      <datalist id={id}>
        {options.map((o) => (
          <option
            key={`${o.value}:${o.source}`}
            value={o.value}
            label={o.source}
          />
        ))}
      </datalist>
    </>
  );
}
export function SuggestedText({
  field,
  label,
  onValue,
  ...props
}: Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "onChange"> & {
  field: string;
  label: string;
  onValue: (value: string) => void;
}) {
  const { options, load } = useOptions(field);
  return (
    <div className="suggested-text">
      <label>
        {label}
        <textarea
          {...props}
          onChange={(event) => onValue(event.target.value)}
          onFocus={(event) => {
            load();
            props.onFocus?.(event);
          }}
        />
      </label>
      <label>
        参考候補（任意）
        <select
          aria-label={`${label}の参考候補`}
          value=""
          onFocus={load}
          disabled={props.disabled}
          onChange={(event) => {
            const text = event.target.value;
            if (text) onValue(text);
          }}
        >
          <option value="">登録値から選ぶ（任意）</option>
          {options.map((o) => (
            <option key={`${o.value}:${o.source}`} value={o.value}>
              {o.value} — {o.source}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
export function EquipmentQueryInput(
  props: InputHTMLAttributes<HTMLInputElement>,
) {
  const [items, setItems] = useState<EquipmentCandidate[]>([]),
    [notice, setNotice] = useState("");
  const controller = useRef<AbortController | null>(null);
  const id = useId();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  async function find(query = String(props.value ?? "")) {
    controller.current?.abort();
    const active = new AbortController();
    controller.current = active;
    try {
      const found = await searchEquipment(query, active.signal);
      if (!active.signal.aborted) {
        setItems(found.items);
        setNotice(
          found.errors.length
            ? "一部の設備候補を取得できません。再度欄を選ぶと再検索します。"
            : found.more
              ? "ほかにも設備があります。名称やコードで絞り込めます。"
              : found.items.length
                ? "設備名またはコードを候補から選べます。"
                : "該当する設備候補はありません。検索語は手入力できます。",
        );
      }
    } catch {
      if (!active.signal.aborted)
        setNotice("設備候補を取得できません。再度欄を選ぶと再検索します。");
    }
  }
  useEffect(
    () => () => {
      controller.current?.abort();
      clearTimeout(timer.current);
    },
    [],
  );
  return (
    <>
      <input
        {...props}
        list={id}
        aria-describedby={`${id}-notice`}
        onFocus={(event) => {
          void find();
          props.onFocus?.(event);
        }}
        onChange={(event) => {
          controller.current?.abort();
          clearTimeout(timer.current);
          setItems([]);
          setNotice("設備候補を検索しています…");
          const query = event.target.value;
          timer.current = setTimeout(() => void find(query), 250);
          props.onChange?.(event);
        }}
      />
      <datalist id={id}>
        {items.map((item) => (
          <option
            key={item.equipment_id}
            value={item.equipment_code}
            label={item.equipment_name}
          />
        ))}
      </datalist>
      <small className="muted" id={`${id}-notice`}>
        {notice}
      </small>
    </>
  );
}
