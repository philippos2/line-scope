import { useEffect, useRef, useState } from "react";
import { ApiError, object, request, type Envelope } from "../../api/client";
import { readInput, type EconomicInput } from "../economics/model";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { GraphWorkspace } from "../graph/GraphWorkspace";
import { detail, graphView, type NodeRef } from "../graph/model";
import { incidentGraph, lossReasons, money } from "./model";

export function IncidentWorkspace({
  executionEpoch,
  onUseEquipment,
  onInvestigate,
  onPrepareState,
}: {
  onPrepareState: (equipment: EquipmentCandidate, state: string) => void;
  executionEpoch: number;
  onUseEquipment: (equipment: EquipmentCandidate) => void;
  onInvestigate: (text: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [inputs, setInputs] = useState<
    { record: EconomicInput; equipment: EquipmentCandidate }[]
  >([]);
  const [selection, setSelection] = useState<string[]>([]);
  const [start, setStart] = useState(""),
    [end, setEnd] = useState("");
  const [result, setResult] = useState<Envelope | null>(null);
  const [graph, setGraph] = useState<Envelope | null>(null);
  const [selected, setSelected] = useState<NodeRef | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [stateChoices, setStateChoices] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false),
    [truncated, setTruncated] = useState(false);
  const [observedEpoch, setObservedEpoch] = useState(executionEpoch);
  const active = useRef<AbortController | null>(null),
    pending = useRef(false);
  useEffect(() => () => active.current?.abort(), []);
  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (pending.current) return;
    const controller = new AbortController();
    active.current = controller;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await action(controller.signal);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof ApiError ? e.code : "INVALID_RESPONSE");
    } finally {
      pending.current = false;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  function clearResult() {
    setResult(null);
    setGraph(null);
    setSelected(null);
  }
  function load() {
    clearResult();
    setSelection([]);
    setInputs([]);
    setLoaded(false);
    setStart("");
    setEnd("");
    void run(async (signal) => {
      const found = await request(
        "",
        "/economic-inputs/search",
        {
          filter: query.trim() ? { equipment_query: query.trim() } : {},
          page_size: 10,
          cursor: null,
        },
        signal,
      );
      if (!Array.isArray(found.data.items)) throw new Error("INVALID_RESPONSE");
      const rows = await Promise.all(
        found.data.items.filter(object).map(async (row) => {
          if (
            typeof row.economic_input_id !== "string" ||
            typeof row.equipment_id !== "string" ||
            typeof row.equipment_code !== "string" ||
            typeof row.equipment_name !== "string"
          )
            throw new Error("INVALID_RESPONSE");
          const response = await request(
            "",
            `/economic-inputs/${row.economic_input_id}`,
            undefined,
            signal,
          );
          return {
            record: readInput(response.data.input),
            equipment: {
              equipment_id: row.equipment_id,
              equipment_code: row.equipment_code,
              equipment_name: row.equipment_name,
            },
          };
        }),
      );
      if (!signal.aborted) {
        setInputs(rows);
        setLoaded(true);
        setTruncated(found.data.next_cursor !== null);
      }
    });
  }
  function toggle(record: EconomicInput, checked: boolean) {
    clearResult();
    setSelection((old) =>
      checked
        ? [
            ...old.filter(
              (id) =>
                inputs.find((row) => row.record.economic_input_id === id)
                  ?.record.equipment_id !== record.equipment_id,
            ),
            record.economic_input_id,
          ]
        : old.filter((id) => id !== record.economic_input_id),
    );
    if (checked && selection.length === 0) {
      setStart(record.payload.period_start);
      setEnd(record.payload.period_end);
    }
  }
  function investigate() {
    clearResult();
    void run(async (signal) => {
      const equipment = inputs.filter((row) =>
        selection.includes(row.record.economic_input_id),
      );
      const response = await request(
        "",
        "/incidents/investigate",
        {
          equipment_ids: equipment.map((row) => row.record.equipment_id),
          economic_input_ids: selection,
          period_start: start,
          period_end: end,
        },
        signal,
      );
      const display = incidentGraph(response);
      const fields: Record<string, [string, string]> = {
        Equipment: ["get_equipment", "equipment_id"],
        Process: ["get_process", "process_id"],
        Product: ["get_product", "product_id"],
        ProductionOperation: [
          "get_production_operation",
          "production_operation_id",
        ],
        InfrastructureResource: [
          "get_infrastructure_resource",
          "infrastructure_resource_id",
        ],
      };
      const subjects = graphView(display)?.nodes.slice(0, 30) ?? [];
      const metadata = await Promise.allSettled(
        subjects.map(async (item) => {
          const tool = fields[item.entity_type];
          if (!tool) return [];
          const found = await request(
            "",
            "/agent",
            {
              message: `関係分析 ${JSON.stringify({ tool: tool[0], arguments: { [tool[1]]: item.entity_id } })}`,
            },
            signal,
          );
          return Array.isArray(found.data.tool_results)
            ? found.data.tool_results
            : [];
        }),
      );
      display.data.tool_results = [
        ...(Array.isArray(display.data.tool_results)
          ? display.data.tool_results
          : []),
        ...metadata.flatMap((row) =>
          row.status === "fulfilled" ? row.value : [],
        ),
      ];
      if (!signal.aborted) {
        setResult(response);
        setGraph(display);
        setObservedEpoch(executionEpoch);
      }
    });
  }
  function selectNode(item: NodeRef) {
    setSelected(item);
    const tools: Record<string, [string, string]> = {
      Equipment: ["get_equipment", "equipment_id"],
      Process: ["get_process", "process_id"],
      Product: ["get_product", "product_id"],
      ProductionOperation: [
        "get_production_operation",
        "production_operation_id",
      ],
      InfrastructureResource: [
        "get_infrastructure_resource",
        "infrastructure_resource_id",
      ],
    };
    const entry = tools[item.entity_type];
    if (!entry || !graph || busy) return;
    void run(async (signal) => {
      const response = await request(
        "",
        "/agent",
        {
          message: `関係分析 ${JSON.stringify({ tool: entry[0], arguments: { [entry[1]]: item.entity_id } })}`,
        },
        signal,
      );
      if (!signal.aborted)
        setGraph((old) =>
          old
            ? {
                ...old,
                data: {
                  ...old.data,
                  tool_results: [
                    ...(Array.isArray(old.data.tool_results)
                      ? old.data.tool_results
                      : []),
                    ...(Array.isArray(response.data.tool_results)
                      ? response.data.tool_results
                      : []),
                  ],
                },
              }
            : null,
        );
    });
  }
  function adoptEquipment(item: NodeRef) {
    if (!graph) return;
    const row = detail(graph, item);
    if (
      typeof row.equipment_id === "string" &&
      typeof row.equipment_code === "string" &&
      typeof row.equipment_name === "string"
    )
      onUseEquipment(row as unknown as EquipmentCandidate);
  }
  const loss = result && object(result.data.loss) ? result.data.loss : null;
  const impacts =
    result && Array.isArray(result.data.impacts)
      ? result.data.impacts.filter(object)
      : [];
  const old = observedEpoch !== executionEpoch;
  return (
    <section className="incident-workspace" aria-label="工場トラブルの調査">
      <div className="incident-entry">
        <p className="eyebrow">
          1 対象と根拠を選ぶ → 2 影響と被害額を把握 → 3 対応を判断
        </p>
        <h1>工場のトラブルは、どこに影響しているか</h1>
        <p>
          経済入力のある設備と根拠を選び、関係Graphと時間当たりの損失を一緒に調べます。工場全体の一覧ではなく、状態は調査時に確認します。
        </p>
        <details className="incident-controls" open={!result}>
          <summary>対象・損失根拠・評価期間を確認／変更</summary>
          <label>
            設備名・コードで根拠を絞る
            <input
              value={query}
              maxLength={100}
              disabled={busy}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <button className="primary" disabled={busy} onClick={load}>
            設備と損失根拠を確認する
          </button>
          {loaded && inputs.length === 0 && (
            <p className="notice">
              登録された経済入力がありません。設備単位の調査、または正式入力の登録へ進んでください。
            </p>
          )}
          {truncated && (
            <p className="notice">
              先頭10件の候補です。続きは未取得です。設備名・コードで絞って再取得してください。
            </p>
          )}
          <div className="incident-candidates">
            {inputs.map(({ record, equipment }) => (
              <label
                key={record.economic_input_id}
                className="incident-candidate"
              >
                <input
                  type="checkbox"
                  disabled={busy}
                  checked={selection.includes(record.economic_input_id)}
                  onChange={(e) => toggle(record, e.target.checked)}
                />
                <span>
                  <strong>
                    {equipment.equipment_name}（{equipment.equipment_code}）
                  </strong>
                  <small>
                    {record.input_code} ／ version {record.version}
                  </small>
                  <small>
                    適用：{record.payload.period_start} 〜{" "}
                    {record.payload.period_end}
                  </small>
                  {!record.payload.incident_losses && (
                    <small>調査用の停止損失根拠は未登録です</small>
                  )}
                </span>
              </label>
            ))}
          </div>
          {loaded && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                investigate();
              }}
            >
              <div className="incident-period">
                <label>
                  損失評価の開始
                  <input
                    required
                    value={start}
                    onChange={(e) => {
                      setStart(e.target.value);
                      clearResult();
                    }}
                    disabled={busy}
                  />
                </label>
                <label>
                  損失評価の終了
                  <input
                    required
                    value={end}
                    onChange={(e) => {
                      setEnd(e.target.value);
                      clearResult();
                    }}
                    disabled={busy}
                  />
                </label>
              </div>
              <p className="muted">
                最初に選んだ根拠の期間を記入しています。異なる期間の根拠は完全合計を算出できません。設備ごとに根拠は1件だけ選びます。
              </p>
              <button className="primary" disabled={busy || !selection.length}>
                選択した設備の影響と被害額を調べる
              </button>
            </form>
          )}
        </details>
        {busy && <p role="status">正本データと関係を確認しています…</p>}
        {error && (
          <p role="alert" className="notice">
            {error}。対象・接続・根拠を確認して再取得してください。
          </p>
        )}
      </div>
      <div className="incident-results">
        <GraphWorkspace
          result={graph}
          selected={selected}
          busy={busy}
          stale={!!result && old}
          onSelect={selectNode}
          onUseEquipment={adoptEquipment}
          onInvestigate={onInvestigate}
          onEvidence={() => {
            const panel = document.getElementById("incident-evidence");
            panel?.setAttribute("open", "");
            panel?.scrollIntoView({ behavior: "smooth" });
          }}
          emptyContent={
            <p>上の一覧で対象と根拠を選び、影響と被害額を調べてください。</p>
          }
          onStart={load}
          onRefresh={investigate}
        />
        <aside className="incident-loss" aria-label="推定被害額">
          <p className="eyebrow">ECONOMIC IMPACT</p>
          <h2>推定被害額</h2>
          <p className="incident-amount">
            {loss && !old ? money(loss.loss_per_hour) : "未算出"}
          </p>
          <p>
            選択設備の影響製品に対する、登録条件での停止損失の推定です。工場全体の実損害ではありません。
          </p>
          {!loss && (
            <p className="notice">
              対象と損失根拠を選び「影響と被害額を調べる」を押してください。未取得を0円とは表示しません。
            </p>
          )}
          {loss && old && (
            <p className="notice">
              変更確定前の結果です。影響と被害額を再取得してください。
            </p>
          )}
          {loss && !old && (
            <>
              <p>
                判明分の小計：
                <strong>{money(loss.known_subtotal_per_hour)}</strong>
              </p>
              <p className="badge">
                {loss.complete === true
                  ? "選択した登録範囲内で算定"
                  : "入力不足・条件未確認"}
              </p>
              <p>
                評価期間：{start} 〜 {end}
              </p>
              {Array.isArray(loss.missing_information) &&
                loss.missing_information.filter(object).map((row, i) => (
                  <p className="notice" key={i}>
                    {lossReasons[String(row.reason)] ?? String(row.reason)}
                  </p>
                ))}
              <details>
                <summary>損失の内訳と出典</summary>
                {Array.isArray(loss.items) &&
                  loss.items.filter(object).map((row) => (
                    <article key={String(row.scope_key)}>
                      <strong>{String(row.scope_key)}</strong>
                      <p>
                        {money(row.loss_per_hour)} ／{" "}
                        {row.included_in_subtotal === true
                          ? "1回計上"
                          : "小計から除外"}
                      </p>
                      <p>{String(row.source)}</p>
                      <p>
                        {row.excluded_reason
                          ? lossReasons[String(row.excluded_reason)]
                          : "共有する同一損失は重複計上していません"}
                      </p>
                    </article>
                  ))}
              </details>
            </>
          )}
          {impacts.map((row) =>
            object(row.equipment) ? (
              <article key={String(row.equipment_id)}>
                <strong>
                  {String(row.equipment.equipment_code)}：
                  {String(row.state_code)}
                </strong>
                <p>{String(row.equipment.equipment_name)}</p>
                <button
                  disabled={busy}
                  onClick={() =>
                    adoptEquipment({
                      entity_type: "Equipment",
                      entity_id: String(row.equipment_id),
                    })
                  }
                >
                  この設備の対応案を比べる
                </button>
                <details>
                  <summary>この設備の登録状態を変更する</summary>
                  <label>
                    変更後の登録状態（{String(row.equipment.equipment_code)}）
                    <select
                      aria-label={`変更後の登録状態（${String(row.equipment.equipment_code)}）`}
                      value={stateChoices[String(row.equipment_id)] ?? ""}
                      disabled={busy}
                      onChange={(e) =>
                        setStateChoices((old) => ({
                          ...old,
                          [String(row.equipment_id)]: e.target.value,
                        }))
                      }
                    >
                      <option value="">状態を選ぶ</option>
                      <option value="UNDER_MAINTENANCE">保全中</option>
                      <option value="STOPPED">停止</option>
                      <option value="RUNNING">稼働中</option>
                      <option value="UNKNOWN">不明</option>
                    </select>
                  </label>
                  <button
                    disabled={busy || !stateChoices[String(row.equipment_id)]}
                    onClick={() => {
                      if (object(row.equipment))
                        onPrepareState(
                          row.equipment as unknown as EquipmentCandidate,
                          stateChoices[String(row.equipment_id)],
                        );
                    }}
                  >
                    状態変更の準備へ
                  </button>
                  <small>
                    登録状態の変更です。修理完了や安全な運転を認定しません。
                  </small>
                </details>
              </article>
            ) : null,
          )}
          {result && (
            <details id="incident-evidence">
              <summary>計算条件・入力version・Graphの根拠</summary>
              <pre>{JSON.stringify(result.evidence, null, 2)}</pre>
            </details>
          )}
          {result && (
            <button disabled={busy} onClick={investigate}>
              影響と被害額を再取得する
            </button>
          )}
        </aside>
      </div>
    </section>
  );
}
