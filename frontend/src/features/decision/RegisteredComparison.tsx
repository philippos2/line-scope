import {
  useEffect,
  useRef,
  useState,
  useMemo,
  useCallback,
  type FormEvent,
} from "react";
import {
  ApiError,
  object,
  request,
  type JsonObject,
  type Envelope,
} from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { UpstreamDependencies } from "./UpstreamDependencies";
import { DecisionComparison } from "./DecisionComparison";
import {
  comparisonPeriod,
  inputPeriod,
  inputRecord,
} from "../investigation/workspaceModel";
import { displayPeriod } from "../investigation/EquipmentInvestigation";

const groups = [
  ["economic", "経済入力", "economic_input_id"],
  ["capacity", "能力入力", "capacity_input_id"],
  ["safety", "安全入力", "safety_input_id"],
  ["maintenance", "対応計画・履歴", "maintenance_input_id"],
] as const;
type Group = (typeof groups)[number][0];
const paths = {
  economic: "economic-inputs",
  capacity: "capacity-inputs",
  safety: "safety-inputs",
  maintenance: "maintenance-inputs",
} as const;
const blank = (): Record<Group, string[]> => ({
  economic: [],
  capacity: [],
  safety: [],
  maintenance: [],
});
export function RegisteredComparison({
  equipment,
  executionEpoch,
  onInvestigate,
  onResult,
  initialEconomic,
  initialCapacity,
  initialEconomicId,
  initialCapacityId,
  candidateIds,
  productIds,
}: {
  initialEconomic: Envelope[];
  initialCapacity: Envelope[];
  initialEconomicId: string;
  initialCapacityId: string;
  candidateIds: string[];
  productIds: string[];
  equipment: EquipmentCandidate | null;
  executionEpoch: number;
  onInvestigate: (message: string) => void;
  onResult?: (result: Envelope | null) => void;
}) {
  const [candidates, setCandidates] = useState<
    Partial<Record<Group, JsonObject>>
  >({});
  const [selected, setSelected] = useState(blank);
  const [records, setRecords] = useState<Record<string, Envelope>>({});
  const touched = useRef(new Set<Group>());
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    const values = [...initialEconomic, ...initialCapacity];
    const map: Record<string, Envelope> = {};
    for (const value of values) {
      const r = inputRecord(value);
      const id = r.economic_input_id ?? r.capacity_input_id;
      if (typeof id === "string") map[id] = value;
    }
    setRecords((old) => ({ ...old, ...map }));
    setSelected((old) => ({
      ...old,
      economic: touched.current.has("economic")
        ? old.economic
        : initialEconomicId
          ? [initialEconomicId]
          : old.economic,
      capacity: touched.current.has("capacity")
        ? old.capacity
        : initialCapacityId
          ? [initialCapacityId]
          : old.capacity,
    }));
  }, [initialEconomic, initialCapacity, initialEconomicId, initialCapacityId]);
  const selectedInputs = useMemo(
    () =>
      Object.fromEntries(
        groups.map(([group]) => [
          group,
          selected[group]
            .map((id) => records[id])
            .filter(Boolean)
            .map(inputRecord),
        ]),
      ),
    [selected, records],
  );
  const timing = comparisonPeriod(selectedInputs);
  const start = timing.period?.start ?? "",
    end = timing.period?.end ?? "";
  const [result, setResult] = useState<JsonObject | null>(null);
  const [details, setDetails] = useState<JsonObject | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [observedEpoch, setObservedEpoch] = useState(executionEpoch);
  const controller = useRef<AbortController | null>(null),
    pending = useRef(false);
  useEffect(() => () => controller.current?.abort(), []);
  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (pending.current) return;
    const active = new AbortController();
    controller.current = active;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await action(active.signal);
    } catch (caught) {
      if (!active.signal.aborted)
        setError(caught instanceof ApiError ? caught.code : "INVALID_RESPONSE");
    } finally {
      pending.current = false;
      if (!active.signal.aborted) setBusy(false);
    }
  }
  async function readDetails(
    groupsData: Partial<Record<Group, JsonObject>>,
    signal: AbortSignal,
  ) {
    const tasks = groups.flatMap(([group, , idKey]) =>
      Array.isArray(groupsData[group]?.items)
        ? (groupsData[group]!.items as unknown[])
            .filter(object)
            .map((row) => ({ group, id: String(row[idKey]) }))
        : [],
    );
    const cache: Record<string, Envelope> = {};
    let index = 0;
    await Promise.all(
      Array.from({ length: Math.min(4, tasks.length) }, async () => {
        while (index < tasks.length && !signal.aborted) {
          const task = tasks[index++];
          cache[task.id] = await request(
            "",
            `/${paths[task.group]}/${encodeURIComponent(task.id)}`,
            undefined,
            signal,
          );
        }
      }),
    );
    if (!signal.aborted) setRecords((old) => ({ ...old, ...cache }));
  }
  function search() {
    if (!equipment) return;
    setResult(null);
    onResult?.(null);
    setDetails(null);
    void run(async (signal) => {
      const values = await Promise.all(
        groups.map(async ([group]) => {
          const response = await request(
            "",
            `/${paths[group]}/search`,
            {
              filter:
                group === "economic" || group === "maintenance"
                  ? { equipment_id: equipment.equipment_id }
                  : {},
              page_size: 20,
              cursor: null,
            },
            signal,
          );
          if (
            !Array.isArray(response.data.items) ||
            !response.data.items.every(object)
          )
            throw new ApiError("INVALID_RESPONSE");
          return [group, response.data] as const;
        }),
      );
      const data = Object.fromEntries(values);
      await readDetails(data, signal);
      if (!signal.aborted) {
        setCandidates(data);
        setLoaded(true);
      }
    });
  }
  function nextPage(group: Group) {
    const cursor = candidates[group]?.next_cursor;
    if (!equipment || typeof cursor !== "string") return;
    void run(async (signal) => {
      const response = await request(
        "",
        `/${paths[group]}/search`,
        {
          filter:
            group === "economic" || group === "maintenance"
              ? { equipment_id: equipment.equipment_id }
              : {},
          page_size: 100,
          cursor,
        },
        signal,
      );
      if (
        !Array.isArray(response.data.items) ||
        !response.data.items.every(object)
      )
        throw new ApiError("INVALID_RESPONSE");
      await readDetails({ [group]: response.data }, signal);
      if (!signal.aborted)
        setCandidates((previous) => ({
          ...previous,
          [group]: {
            ...response.data,
            items: [
              ...(Array.isArray(previous[group]?.items)
                ? (previous[group]?.items as unknown[])
                : []),
              ...(response.data.items as unknown[]),
            ],
          },
        }));
    });
  }
  function inspect(group: Group, identifier: string) {
    void run(async (signal) => {
      const response = await request(
        "",
        `/${paths[group]}/${encodeURIComponent(identifier)}`,
        undefined,
        signal,
      );
      if (signal.aborted) return;
      setDetails(response.data);
    });
  }
  const eligible = useCallback(
    (group: Group, record: JsonObject) => {
      if (!equipment) return false;
      const owner = String(record.equipment_id);
      if (
        (group === "economic" || group === "maintenance") &&
        owner !== equipment.equipment_id
      )
        return false;
      if (
        group === "capacity" &&
        (owner === equipment.equipment_id ||
          !candidateIds.includes(owner) ||
          !productIds.includes(String(record.product_id)))
      )
        return false;
      if (
        group === "safety" &&
        owner !== equipment.equipment_id &&
        !candidateIds.includes(owner)
      )
        return false;
      const basis =
        selectedInputs.economic?.[0] ?? selectedInputs.capacity?.[0];
      const period = basis ? inputPeriod(basis) : null;
      const p = object(record.payload) ? record.payload : {};
      const own = inputPeriod(record);
      if (
        period &&
        !(group === "maintenance" && String(p.kind).endsWith("_RECORD"))
      ) {
        if (
          !own ||
          (group === "safety"
            ? own.start > period.start || own.end < period.end
            : own.start !== period.start || own.end !== period.end)
        )
          return false;
      }
      if (group === "safety" && !period) return false;
      const selectedCapacity = selectedInputs.capacity?.[0];
      if (
        group === "capacity" &&
        selectedCapacity &&
        object(selectedCapacity.payload) &&
        selectedCapacity.payload.quantity_unit !== p.quantity_unit
      )
        return false;
      return true;
    },
    [equipment, candidateIds, productIds, selectedInputs],
  );
  // Only complete result sets may preselect; a user's edit (including clearing) wins.
  useEffect(() => {
    if (!loaded || !equipment) return;
    setSelected((previous) => {
      let changed = false;
      const next = { ...previous };
      for (const [group, , idKey] of groups) {
        if (
          touched.current.has(group) ||
          previous[group].length ||
          candidates[group]?.next_cursor != null
        )
          continue;
        const items = Array.isArray(candidates[group]?.items)
          ? (candidates[group]!.items as unknown[]).filter(object)
          : [];
        const choices = items
          .map((row) => records[String(row[idKey])])
          .filter(Boolean)
          .map(inputRecord)
          .filter((record) => eligible(group, record));
        if (choices.length === 1) {
          next[group] = [String(choices[0][idKey])];
          changed = true;
        }
      }
      return changed ? next : previous;
    });
  }, [loaded, equipment, candidates, records, eligible]);
  const selection = {
    equipment_id: equipment?.equipment_id ?? "",
    period_start: start,
    period_end: end,
    economic_input_id: selected.economic[0] ?? null,
    capacity_input_ids: selected.capacity,
    safety_input_ids: selected.safety,
    maintenance_input_ids: selected.maintenance,
  };
  function compare(event: FormEvent) {
    event.preventDefault();
    setResult(null);
    onResult?.(null);
    void run(async (signal) => {
      const response = await request(
        "",
        "/decisions/compare",
        selection,
        signal,
      );
      if (!signal.aborted) {
        setResult(response.data);
        onResult?.(response);
        setObservedEpoch(executionEpoch);
      }
    });
  }
  const pkg =
    result && object(result.decision_package) ? result.decision_package : null;
  return (
    <details className="economic-panel registered-comparison" open>
      <summary>正式入力から対応案を比較する</summary>
      <p>
        対象設備：
        {equipment
          ? `${equipment.equipment_name}（${equipment.equipment_code}）`
          : "設備を探して候補を選択してください。"}
      </p>
      <p>
        各入力の出典・期間を確認して選択します。未選択は不明です。能力は代替候補の設備を、安全は対象設備・代替設備の入力を選択します。条件に合う候補が1件で検索が完了した場合だけ事前選択します。選び直せます。選択は設備全体の安全や運転許可を意味しません。
      </p>
      <button disabled={busy || !equipment} onClick={search}>
        比較に使う正式入力の候補を取得
      </button>
      {error && (
        <p role="alert">
          {error}。比較結果は未取得です。入力・期間・対象を確認してください。
        </p>
      )}
      {busy && <p role="status">正式入力を確認中…</p>}
      <form onSubmit={compare}>
        <fieldset disabled={busy || !equipment}>
          <legend>比較する入力と共通期間</legend>
          {groups.map(([group, label, idKey]) => (
            <section key={group} aria-label={`比較に使う${label}`}>
              <h3>{label}</h3>
              {Array.isArray(candidates[group]?.items) &&
                candidates[group]?.items.length === 0 && (
                  <p className="muted">
                    登録された候補がありません。「入力を登録・訂正」から登録できます。未選択の条件は不明として比較します。
                  </p>
                )}
              {typeof candidates[group]?.next_cursor === "string" && (
                <p className="notice">
                  未取得の候補があります。次の候補を取得してから選択できます。
                </p>
              )}
              {typeof candidates[group]?.next_cursor === "string" && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => nextPage(group)}
                >
                  次の{label}候補を取得
                </button>
              )}
              {Array.isArray(candidates[group]?.items) &&
                (candidates[group]?.items as unknown[])
                  .filter(object)
                  .map((row) => (
                    <div key={String(row[idKey])}>
                      <label>
                        <input
                          type="checkbox"
                          checked={selected[group].includes(String(row[idKey]))}
                          onChange={(event) => {
                            const id = String(row[idKey]);
                            touched.current.add(group);
                            setResult(null);
                            onResult?.(null);
                            setSelected((previous) => ({
                              ...previous,
                              [group]: event.target.checked
                                ? group === "economic"
                                  ? [id]
                                  : [...previous[group], id]
                                : previous[group].filter(
                                    (value) => value !== id,
                                  ),
                            }));
                          }}
                        />
                        {String(row.equipment_name ?? row.equipment_code)} · 第
                        {String(row.version)}版
                        {selected[group].includes(String(row[idKey])) &&
                        !touched.current.has(group)
                          ? "（事前選択・変更できます）"
                          : ""}
                        {records[String(row[idKey])] &&
                        inputPeriod(inputRecord(records[String(row[idKey])]))
                          ? ` · ${displayPeriod(inputPeriod(inputRecord(records[String(row[idKey])]))!.start, inputPeriod(inputRecord(records[String(row[idKey])]))!.end)}`
                          : ""}
                      </label>
                      <button
                        type="button"
                        onClick={() => inspect(group, String(row[idKey]))}
                      >
                        入力・出典を確認：第{String(row.version)}版
                      </button>
                    </div>
                  ))}
            </section>
          ))}
          <h3>共通比較期間（選択した入力から設定・読み取り専用）</h3>
          <p>{timing.period ? displayPeriod(start, end) : timing.error}</p>
          {groups
            .flatMap(([group]) => selectedInputs[group] ?? [])
            .map((r, i) => (
              <p key={i}>
                第{String(r.version)}版：
                {displayPeriod(inputPeriod(r)?.start, inputPeriod(r)?.end)}
              </p>
            ))}
          <p>
            比較期間は編集できません。期間が合わない場合は入力を選び直すか、「入力を登録・訂正」で期間を直してください。安全条件は全期間を覆う必要があり、履歴は過去の背景情報として扱います。
          </p>
          <button disabled={!timing.period}>選択した正式入力で比較する</button>
          <button
            type="button"
            disabled={!timing.period}
            onClick={() =>
              onInvestigate(`登録入力で比較 ${JSON.stringify(selection)}`)
            }
          >
            この選択をAgentへの問い合わせに使う
          </button>
        </fieldset>
      </form>
      {details && (
        <details open>
          <summary>確認中の入力・出典・期間</summary>
          <pre>{JSON.stringify(details, null, 2)}</pre>
        </details>
      )}
      {pkg && object(pkg.comparison) && (
        <>
          {observedEpoch !== executionEpoch && (
            <p className="notice">
              確定操作前の結果です。入力と比較を再取得してください。
            </p>
          )}
          <DecisionComparison comparison={pkg.comparison} />
          {object(pkg.upstream_dependencies) && (
            <UpstreamDependencies data={pkg.upstream_dependencies} />
          )}
          <details>
            <summary>比較期間・選択入力・Graph・Evidence</summary>
            <pre>{JSON.stringify(result, null, 2)}</pre>
          </details>
        </>
      )}
    </details>
  );
}
