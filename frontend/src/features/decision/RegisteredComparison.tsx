import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, object, request, type JsonObject } from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { DecisionComparison } from "./DecisionComparison";

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
}: {
  equipment: EquipmentCandidate | null;
  executionEpoch: number;
  onInvestigate: (message: string) => void;
}) {
  const [candidates, setCandidates] = useState<
    Partial<Record<Group, JsonObject>>
  >({});
  const [selected, setSelected] = useState(blank);
  const [start, setStart] = useState(""),
    [end, setEnd] = useState("");
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
  function search() {
    if (!equipment) return;
    setResult(null);
    setDetails(null);
    setSelected(blank());
    setCandidates({});
    void run(async (signal) => {
      const rows = await Promise.all(
        groups.map(async ([key]) => {
          const response = await request(
            "",
            `/${paths[key]}/search`,
            {
              filter:
                key === "economic" || key === "maintenance"
                  ? { equipment_id: equipment.equipment_id }
                  : {},
              page_size: 100,
              cursor: null,
            },
            signal,
          );
          if (
            !Array.isArray(response.data.items) ||
            !response.data.items.every(object)
          )
            throw new ApiError("INVALID_RESPONSE");
          return [key, response.data] as const;
        }),
      );
      if (!signal.aborted) setCandidates(Object.fromEntries(rows));
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
      if (
        group === "economic" &&
        object(response.data.input) &&
        object(response.data.input.payload)
      ) {
        setResult(null);
        setStart(String(response.data.input.payload.period_start));
        setEnd(String(response.data.input.payload.period_end));
      }
    });
  }
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
    void run(async (signal) => {
      const response = await request(
        "",
        "/decisions/compare",
        selection,
        signal,
      );
      if (!signal.aborted) {
        setResult(response.data);
        setObservedEpoch(executionEpoch);
      }
    });
  }
  const pkg =
    result && object(result.decision_package) ? result.decision_package : null;
  return (
    <details className="economic-panel registered-comparison">
      <summary>正式入力から対応案を比較する</summary>
      <p>
        対象設備：
        {equipment
          ? `${equipment.equipment_name}（${equipment.equipment_code}）`
          : "設備を探して候補を選択してください。"}
      </p>
      <p>
        各入力の出典・期間を確認して選択します。未選択は不明です。能力は代替候補の設備を、安全は対象設備・代替設備の入力を選択します。選択を自動で補完せず、設備全体の安全や最適案を認定しません。
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
                            setResult(null);
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
                        {String(row.input_code)} /{" "}
                        {String(row.equipment_name ?? row.equipment_code)} /
                        version {String(row.version)}
                      </label>
                      <button
                        type="button"
                        onClick={() => inspect(group, String(row[idKey]))}
                      >
                        入力・出典を確認：{String(row.input_code)}
                      </button>
                    </div>
                  ))}
            </section>
          ))}
          <label>
            共通比較期間の開始
            <input
              required
              value={start}
              onChange={(event) => {
                setStart(event.target.value);
                setResult(null);
              }}
            />
          </label>
          <label>
            共通比較期間の終了
            <input
              required
              value={end}
              onChange={(event) => {
                setEnd(event.target.value);
                setResult(null);
              }}
            />
          </label>
          <p>
            timezone付き日時を指定してください。経済入力の詳細を取得するとその評価期間を記入します。計画・能力は同じ期間、安全は全期間を覆う記録を選びます。履歴は過去の背景情報として扱います。
          </p>
          <button>選択した正式入力で比較する</button>
          <button
            type="button"
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
          <details>
            <summary>比較期間・選択入力・Graph・Evidence</summary>
            <pre>{JSON.stringify(result, null, 2)}</pre>
          </details>
        </>
      )}
    </details>
  );
}
