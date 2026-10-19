import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { object, type Envelope } from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { GraphInvestigation } from "../graph/GraphInvestigation";
import { GraphFindings } from "../graph/GraphFindings";
import { GraphCanvas } from "../graph/GraphCanvas";
import {
  detail,
  graphView,
  label,
  node,
  nodeKey,
  typeLabel,
} from "../graph/model";
import { money, lossReasons } from "../incidents/model";
import {
  candidates,
  displayGraph,
  errorCode,
  lossSourceLines,
  explanation,
  generation,
  registeredState,
  rows,
  products,
  searchEquipment,
  toolData,
  type ReadState,
} from "./readModel";
import {
  AlternativeAssessment,
  availabilityLabel,
  availabilityReason,
} from "./AlternativeAssessment";
import { useEquipmentInvestigation } from "./useEquipmentInvestigation";

export function displayPeriod(start: unknown, end: unknown) {
  const formatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const format = (value: unknown) => {
    const date = new Date(String(value));
    return Number.isNaN(date.getTime())
      ? "日時を取得できません"
      : formatter.format(date);
  };
  return `${format(start)}〜${format(end)}（日本時間）`;
}
function Failure({ code, retry }: { code?: string; retry: () => void }) {
  return code ? (
    <div className="read-failure" role="alert">
      <p>
        {code === "PERIOD_MISMATCH"
          ? "期間が異なります。算定データの登録・訂正が必要です。"
          : explanation(code)}
      </p>
      <button onClick={retry}>再試行</button>
      <details>
        <summary>技術情報</summary>
        <code>{code}</code>
      </details>
    </div>
  ) : null;
}
function InputChoice({
  kind,
  values,
  value,
  onChange,
  loading,
  error,
  retry,
  productTitle,
}: {
  productTitle: (id: string) => string;
  kind: "economic" | "capacity";
  values: Envelope[];
  value: string;
  onChange: (v: string) => void;
  loading?: boolean;
  error?: string;
  retry: () => void;
}) {
  const name = kind === "economic" ? "損害額の算定データ" : "能力データ";
  const selected = values.find(
    (v) => object(v.data.input) && v.data.input[`${kind}_input_id`] === value,
  );
  const record = selected?.data.input;
  const p = object(record) && object(record.payload) ? record.payload : null;
  return (
    <details className="input-choice">
      <summary>{name}を確認・選び直す</summary>
      <Failure code={error} retry={retry} />
      {loading ? (
        <p role="status">{name}を確認しています…</p>
      ) : (
        <label>
          {name}
          <select
            aria-label={name}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          >
            <option value="">
              {values.length ? "選んでください" : "登録なし"}
            </option>
            {values.map((v) => {
              const r = object(v.data.input) ? v.data.input : {};
              const payload = object(r.payload) ? r.payload : {};
              return (
                <option
                  key={String(r[`${kind}_input_id`])}
                  value={String(r[`${kind}_input_id`])}
                >
                  {kind === "capacity"
                    ? productTitle(String(r.product_id))
                    : "損害額の算定データ"}
                  ・第{String(r.version)}版・
                  {displayPeriod(payload.period_start, payload.period_end)}
                </option>
              );
            })}
          </select>
        </label>
      )}
      {p && (
        <dl>
          <dt>評価期間（読み取り専用）</dt>
          <dd>{displayPeriod(p.period_start, p.period_end)}</dd>
          <dt>出典</dt>
          <dd>
            {kind === "capacity" ? (
              String(p.source)
            ) : (
              <ul>
                {lossSourceLines(p.incident_losses, productTitle).map(
                  (text) => (
                    <li key={text}>{text}</li>
                  ),
                )}
              </ul>
            )}
          </dd>
          <dt>選択</dt>
          <dd>
            {values.length === 1
              ? "1件の登録データを自動選択しています。"
              : "選択した登録データを使用しています。"}
          </dd>
        </dl>
      )}
      {object(record) && (
        <details>
          <summary>技術情報</summary>
          <pre>{String(record.input_code)}</pre>
        </details>
      )}
    </details>
  );
}
export function EquipmentInvestigation({
  executionEpoch,
  onRootChange,
  onUseEquipment,
  onRegister,
  onObservations,
}: {
  executionEpoch: number;
  onRootChange: (v: EquipmentCandidate | null) => void;
  onUseEquipment: (v: EquipmentCandidate) => void;
  onRegister: (v: EquipmentCandidate) => void;
  onObservations: (v: Envelope) => void;
}) {
  const [query, setQuery] = useState(""),
    [root, setRoot] = useState<EquipmentCandidate | null>(null);
  const [found, setFound] = useState<EquipmentCandidate[]>([]),
    [searched, setSearched] = useState(false),
    [searchBusy, setSearchBusy] = useState(false),
    [searchErrors, setSearchErrors] = useState<string[]>([]),
    [more, setMore] = useState(false);
  const [direction, setDirection] = useState<"down" | "up" | "extra">("down");
  const searchAbort = useRef<AbortController | null>(null);
  useEffect(() => () => searchAbort.current?.abort(), []);
  const model = useEquipmentInvestigation(root, executionEpoch);
  const { states } = model;
  function choose(item: EquipmentCandidate) {
    setRoot(item);
    setDirection("down");
    onRootChange(item);
  }
  async function search(event?: FormEvent) {
    event?.preventDefault();
    searchAbort.current?.abort();
    const controller = new AbortController();
    searchAbort.current = controller;
    setSearchBusy(true);
    setSearchErrors([]);
    setSearched(false);
    try {
      const response = await searchEquipment(query, controller.signal);
      if (!controller.signal.aborted) {
        setFound(response.items);
        setMore(response.more);
        setSearchErrors(response.errors);
        setSearched(true);
      }
    } catch (e) {
      if (!controller.signal.aborted) setSearchErrors([errorCode(e)]);
    } finally {
      if (!controller.signal.aborted) setSearchBusy(false);
    }
  }
  const base = states[direction]?.value;
  const shown = useMemo(
    () =>
      base
        ? displayGraph(
            base,
            direction === "down" ? states.alternatives?.value : undefined,
            model.metadata,
          )
        : null,
    [base, direction, states.alternatives?.value, model.metadata],
  );
  const view = shown ? graphView(shown) : null;
  const down = toolData(states.down?.value);
  const candidateRefs = candidates(states.alternatives?.value);
  const candidateFacts = rows(
    toolData(states.alternatives?.value).alternatives,
  ).flatMap((row) => rows(row.candidates));
  const factOf = (id: unknown) =>
    candidateFacts.find(
      (row) => object(row.candidate) && row.candidate.entity_id === id,
    );
  const alternativesUsable =
    toolData(states.alternatives?.value).complete === true &&
    toolData(states.alternatives?.value).graph_sync_state === "CURRENT" &&
    sameGenerationForAlternatives();
  function sameGenerationForAlternatives() {
    return (
      generation(states.alternatives?.value) === generation(states.down?.value)
    );
  }

  const observedStates = [
    ...rows(rows(states.down?.value?.evidence.tool_results)[0]?.current_states),
    ...rows(
      rows(states.alternatives?.value?.evidence.tool_results)[0]
        ?.current_states,
    ),
  ];
  const stateOf = (id: string) =>
    observedStates.find((x) => x.equipment_id === id)?.state_code;
  const titleOf = (ref: { entity_type: string; entity_id: string }) =>
    shown
      ? label(shown, ref, model.labelStates[nodeKey(ref)])
      : typeLabel(ref.entity_type);
  const selected = model.selected;
  const selectedData = shown && selected ? detail(shown, selected) : null;
  const selectedEquipment =
    selected?.entity_type === "Equipment" &&
    selectedData &&
    typeof selectedData.equipment_code === "string" &&
    typeof selectedData.equipment_name === "string"
      ? {
          equipment_id: selected.entity_id,
          equipment_code: selectedData.equipment_code,
          equipment_name: selectedData.equipment_name,
        }
      : null;
  const paths = rows(view?.data.representative_paths).filter(
    (path) =>
      selected &&
      Array.isArray(path.nodes) &&
      path.nodes.filter(node).some((n) => nodeKey(n) === nodeKey(selected)),
  );
  const graphGeneration = generation(states.down?.value);
  const sameGeneration = (s: ReadState | undefined) =>
    !s?.value || !graphGeneration || generation(s.value) === graphGeneration;
  const lossResponse = states.loss?.value;
  const loss =
    lossResponse && object(lossResponse.data.loss)
      ? lossResponse.data.loss
      : null;
  const econ = model.economic.find(
    (x) =>
      object(x.data.input) &&
      x.data.input.economic_input_id === model.economicId,
  );
  const econPayload =
    econ && object(econ.data.input) && object(econ.data.input.payload)
      ? econ.data.input.payload
      : null;
  const included = rows(loss?.items).filter(
    (v) => v.included_in_subtotal === true,
  );
  const comp = states.comparison?.value;
  const pkg =
    comp && object(comp.data.decision_package)
      ? comp.data.decision_package
      : null;
  const profile = pkg && object(pkg.comparison) ? pkg.comparison : null;
  const options = rows(profile?.options).filter(
    (o) => o.option === "SUBSTITUTE",
  );
  const selectedProducts = new Set(
    rows(object(pkg?.selected_inputs) ? pkg.selected_inputs.capacity : []).map(
      (row) => (object(row.input) ? row.input.product_id : undefined),
    ),
  );
  const notSelected = products(states.down?.value).filter(
    (n) => n.entity_type === "Product" && !selectedProducts.has(n.entity_id),
  );
  const reported = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (shown && reported.current !== shown.request_id) {
      reported.current = shown.request_id;
      onObservations(shown);
    }
  }, [shown, onObservations]);
  const info = (text: string) => <p className="muted">{text}</p>;
  return (
    <section className="equipment-investigation" aria-label="設備調査">
      <aside className="equipment-search-panel">
        <h2>設備を探す</h2>
        <form onSubmit={search}>
          <label htmlFor="equipment-search">設備名・コード</label>
          <input
            id="equipment-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="設備名の一部、またはコード"
          />
          <button className="primary" disabled={searchBusy}>
            検索
          </button>
        </form>
        {searchBusy && <p role="status">設備を探しています…</p>}
        {searchErrors.map((code, i) => (
          <Failure key={i} code={code} retry={() => void search()} />
        ))}
        {searched &&
          !found.length &&
          !searchErrors.length &&
          info(
            "該当する設備がありません。設備名の一部、またはコードの全体を入力してください。コードは大文字・小文字を区別します。",
          )}
        {found.map((item) => (
          <button
            className="equipment-result"
            key={item.equipment_id}
            aria-pressed={root?.equipment_id === item.equipment_id}
            onClick={() => choose(item)}
          >
            <strong>{item.equipment_name}</strong>
            <span>{item.equipment_code}</span>
            <span
              className={`registered-state state-${String(stateOf(item.equipment_id))}`}
            >
              登録上の状態：{registeredState(stateOf(item.equipment_id))}
            </span>
          </button>
        ))}
        {model.candidateEquipment.length > 0 && (
          <section className="discovered-candidates">
            <h3>調査で見つかった代替候補</h3>
            {model.candidateEquipment.map((item) => (
              <button
                className="equipment-result"
                key={item.equipment_id}
                onClick={() => choose(item)}
              >
                <strong>{item.equipment_name}</strong>
                <span>{item.equipment_code}</span>
                <span className="registered-state">
                  登録上の状態：{registeredState(stateOf(item.equipment_id))}
                </span>
              </button>
            ))}
          </section>
        )}
        {more &&
          info("ほかにも設備があります。名前やコードで絞り込んでください。")}
        {root && (
          <div className="selected-equipment">
            <strong>選択中：{root.equipment_name}</strong>
            <p>
              {root.equipment_code}・登録上の状態：
              {registeredState(model.currentState)}
            </p>
            <button
              onClick={() => {
                setRoot(null);
                onRootChange(null);
              }}
            >
              選択を解除
            </button>
          </div>
        )}
      </aside>
      <div className="investigation-center">
        <section
          className="relationship-panel"
          aria-label="つながりと影響の範囲"
        >
          <div className="section-heading">
            <h1>つながりと影響の範囲</h1>
            {root && <button onClick={model.retry}>再調査</button>}
          </div>
          <div className="direction-tabs">
            {(["down", "up"] as const).map((d) => (
              <button
                key={d}
                aria-pressed={direction === d}
                onClick={() => setDirection(d)}
              >
                {d === "down"
                  ? "止まると影響を受ける先"
                  : "この設備が依存する先"}
              </button>
            ))}
          </div>
          {(states.extra?.value ||
            states.extra?.loading ||
            states.extra?.error) && (
            <button
              onClick={() => setDirection("extra")}
              aria-pressed={direction === "extra"}
            >
              詳しい分析の結果
            </button>
          )}
          {model.stale && (
            <p className="notice">更新前の結果です。再調査してください。</p>
          )}
          {!root &&
            info("設備名またはコードで検索し、調べる設備を選んでください。")}
          {states[direction]?.loading && (
            <p role="status">つながりを調べています…</p>
          )}
          <Failure code={states[direction]?.error} retry={model.retry} />
          <Failure
            code={
              Object.values(model.labelStates).find((s) => s.status === "error")
                ?.code
            }
            retry={model.retryLabels}
          />
          {Object.values(model.labelStates).some(
            (s) => s.status === "error",
          ) && (
            <p className="notice">
              一部の名称を取得できませんでした。表示済みの関係と金額は保持しています。
            </p>
          )}
          {Object.values(model.labelStates).some(
            (s) => s.status === "limited",
          ) && (
            <p className="notice">
              名称の取得は100件までです。調査範囲を絞って再調査してください。
            </p>
          )}
          {view && shown ? (
            <>
              <p className="relationship-summary">
                {direction === "down"
                  ? `直接 ${rows(down.direct_nodes).length}件・間接 ${rows(down.indirect_nodes).length}件`
                  : direction === "up"
                    ? `依存先 ${rows(view.data.reached_nodes).length}件`
                    : `表示する項目 ${view.nodes.length}件`}{" "}
                ／ 調べた範囲：
                {view.data.complete === true
                  ? "最後まで調べた"
                  : "途中まで（制限あり）"}
              </p>
              <div className="entity-legend">
                {[
                  "Equipment",
                  "Process",
                  "ProductionOperation",
                  "Product",
                  "InfrastructureResource",
                ].map((t) => (
                  <span key={t} className={`legend-${t}`}>
                    {typeLabel(t)}
                  </span>
                ))}
                <span>破線枠：代替候補</span>
              </div>
              <GraphCanvas
                key={`${root?.equipment_id}:${direction}:${model.stale}:${view.nodes.length}`}
                view={view}
                result={shown}
                selected={selected ? nodeKey(selected) : null}
                onSelect={model.select}
                classification={
                  direction === "down"
                    ? "影響を受ける先"
                    : direction === "up"
                      ? "依存先"
                      : "関係先"
                }
                candidates={candidateRefs.map(nodeKey)}
                labelStates={model.labelStates}
                registeredStates={Object.fromEntries(
                  observedStates.map((s) => [
                    String(s.equipment_id),
                    registeredState(s.state_code),
                  ]),
                )}
              />
              {direction === "extra" && (
                <GraphFindings
                  data={view.data}
                  result={shown}
                  onSelect={model.select}
                />
              )}
              <GraphInvestigation
                key={root?.equipment_id}
                result={shown}
                selected={selected}
                busy={states.extra?.loading === true}
                initiallyOpen={false}
                onAnalyze={(tool, args) => {
                  model.analyze(tool, args);
                  setDirection("extra");
                }}
              />
              <p className="muted">
                つながりをたどった結果です。実際に止まるとは限りません
              </p>
            </>
          ) : root &&
            !states[direction]?.loading &&
            !states[direction]?.error ? (
            info("表示できる関係を取得していません。")
          ) : null}
        </section>
        <div className="investigation-summaries">
          <section className="loss-estimate" aria-label="推定損害額">
            <h2>
              推定損害額<span className="muted">（円／時間）</span>
            </h2>
            {!root ? (
              info("設備を選ぶと表示されます。")
            ) : model.stale ? (
              info("更新前の結果です。再調査してください。")
            ) : model.currentState === "RUNNING" ? (
              info("登録状態が稼働中のため、停止損害の算定対象外です。")
            ) : model.currentState && model.currentState !== "STOPPED" ? (
              info(
                `登録状態が${registeredState(model.currentState)}のため、停止損害に当てはまるか確認できません。`,
              )
            ) : (
              <>
                {(model.inputLoading.economic || states.loss?.loading) && (
                  <p role="status">損害額を確認しています…</p>
                )}
                <Failure
                  code={model.inputErrors.economic}
                  retry={model.retry}
                />
                <Failure
                  code={states.loss?.error}
                  retry={model.retryCalculation}
                />
                {!model.inputLoading.economic &&
                  !model.inputErrors.economic &&
                  !model.economic.length &&
                  info("この設備には損害額の算定データが登録されていません。")}
                {model.economic.length > 1 &&
                  !model.economicId &&
                  info("損害額の算定データを選んでください。")}
                {econPayload && !rows(econPayload.incident_losses).length ? (
                  info(
                    "選んだ算定データに、損害額（円／時間）が登録されていません。",
                  )
                ) : loss && sameGeneration(states.loss) ? (
                  <>
                    <p className="loss-amount">
                      {loss.complete === true
                        ? money(loss.loss_per_hour)
                        : included.length
                          ? `判明分のみ ${money(loss.known_subtotal_per_hour)}（不明あり）`
                          : "金額を確認できません"}
                    </p>
                    <p>
                      {loss.complete === true
                        ? "登録条件に基づく見積もり"
                        : "算定に必要な情報が不足しています。"}
                    </p>
                    <ul>
                      {rows(loss.items).map((item, i) => (
                        <li key={i}>
                          {titleOf({
                            entity_type: "Product",
                            entity_id: String(item.product_id),
                          })}
                          ：
                          {item.included_in_subtotal === true
                            ? money(item.loss_per_hour)
                            : "条件未確認"}
                        </li>
                      ))}
                    </ul>
                    {rows(loss.missing_information).map((item, i) => (
                      <p className="notice" key={i}>
                        {lossReasons[String(item.reason)] ??
                          "算定条件を確認できません。"}
                      </p>
                    ))}
                  </>
                ) : loss && !sameGeneration(states.loss) ? (
                  <Failure code="GRAPH_NOT_CURRENT" retry={model.retry} />
                ) : null}
                <button onClick={() => root && onRegister(root)}>
                  算定データを登録・訂正する
                </button>
              </>
            )}
            {root && (
              <InputChoice
                productTitle={(id) =>
                  titleOf({ entity_type: "Product", entity_id: id })
                }
                kind="economic"
                values={model.economic}
                value={model.economicId}
                onChange={model.setEconomicId}
                loading={model.inputLoading.economic}
                retry={model.retry}
              />
            )}
            <p className="estimate-note">
              登録された条件での見積もりです。実際の損害額ではありません。
            </p>
          </section>
          <section className="alternative-proposal" aria-label="代替の提案">
            <h2>代替の提案</h2>
            {!root ? info("設備を選ぶと候補を探します。") : null}
            {states.alternatives?.loading && (
              <p role="status">代替候補を探しています…</p>
            )}
            <Failure code={states.alternatives?.error} retry={model.retry} />
            {root &&
              states.down?.value &&
              !rows(down.reached_nodes)
                .filter(node)
                .some((n) => n.entity_type === "Product") &&
              info("代替を調べる対象製品がないため、候補を探索できません。")}
            {states.alternatives?.value &&
              !candidateRefs.length &&
              info(
                toolData(states.alternatives.value).complete === true
                  ? "登録された代替候補はありません。"
                  : "途中までしか調べられず、代替候補を確認できません。",
              )}
            {model.stale
              ? info("更新前の結果です。再調査してください。")
              : candidateRefs.map((candidate) => {
                  const fact = factOf(candidate.entity_id);
                  const available =
                    alternativesUsable && fact?.availability === "AVAILABLE";
                  const equipment = model.candidateEquipment.find(
                    (x) => x.equipment_id === candidate.entity_id,
                  );
                  return (
                    <article key={nodeKey(candidate)}>
                      <h3>
                        {available
                          ? "代替候補："
                          : fact?.availability === "UNAVAILABLE"
                            ? "利用できない候補："
                            : "確認が必要な候補："}
                        {equipment
                          ? `${equipment.equipment_name} · ${equipment.equipment_code}`
                          : titleOf(candidate)}
                      </h3>
                      <p>
                        登録上の状態：
                        {registeredState(stateOf(candidate.entity_id))}
                      </p>
                      {!options.some(
                        (option) => option.equipment_id === candidate.entity_id,
                      ) && (
                        <p>
                          利用可能性：
                          {availabilityLabel(
                            alternativesUsable ? fact?.availability : "UNKNOWN",
                          )}
                        </p>
                      )}
                      {!available && <p>{availabilityReason(fact)}</p>}
                      {equipment && (
                        <button onClick={() => choose(equipment)}>
                          この設備を調べる
                        </button>
                      )}
                    </article>
                  );
                })}
            <Failure code={model.inputErrors.capacity} retry={model.retry} />
            {model.inputLoading.capacity && (
              <p role="status">能力データを確認しています…</p>
            )}
            {candidateRefs.length > 0 &&
              !model.inputLoading.capacity &&
              !model.inputErrors.capacity &&
              !model.capacity.length &&
              info("能力データが未登録のため、能力は評価できません。")}
            {model.capacity.length > 1 &&
              !model.capacityId &&
              info("能力データを選んでください。")}
            {states.comparison?.loading && (
              <p role="status">能力を評価しています…</p>
            )}
            <Failure
              code={states.comparison?.error}
              retry={model.retryCalculation}
            />
            {!model.stale && sameGeneration(states.comparison) ? (
              options.map((option, i) => (
                <AlternativeAssessment
                  key={i}
                  option={option}
                  candidate={
                    alternativesUsable ? factOf(option.equipment_id) : undefined
                  }
                  product={titleOf({
                    entity_type: "Product",
                    entity_id: String(option.product_id),
                  })}
                  unevaluated={notSelected.map(titleOf)}
                />
              ))
            ) : !model.stale && states.comparison?.value ? (
              <Failure code="GRAPH_NOT_CURRENT" retry={model.retry} />
            ) : null}
            {candidateRefs.length > 0 && (
              <InputChoice
                productTitle={(id) =>
                  titleOf({ entity_type: "Product", entity_id: id })
                }
                kind="capacity"
                values={model.capacity}
                value={model.capacityId}
                onChange={model.setCapacityId}
                loading={model.inputLoading.capacity}
                retry={model.retry}
              />
            )}
          </section>
        </div>
      </div>
      <aside className="selected-node-panel" aria-label="選択した項目">
        <h2>選択した項目</h2>
        {selected && shown ? (
          <>
            <h3>{titleOf(selected)}</h3>
            <p>{typeLabel(selected.entity_type)}</p>
            {selected.entity_type === "Equipment" && (
              <p>
                登録上の状態：{registeredState(stateOf(selected.entity_id))}
              </p>
            )}
            <Failure
              code={model.attributeError}
              retry={() => model.select(selected)}
            />
            <dl>
              {selectedData &&
                Object.entries(selectedData)
                  .filter(([k]) =>
                    [
                      "equipment_name",
                      "equipment_code",
                      "equipment_type",
                      "process_name",
                      "process_code",
                      "operation_code",
                      "product_name",
                      "product_code",
                      "resource_name",
                      "resource_code",
                    ].includes(k),
                  )
                  .map(([k, v]) => (
                    <div key={k}>
                      <dt>
                        {
                          (
                            {
                              equipment_name: "設備名",
                              equipment_code: "設備コード",
                              equipment_type: "種別",
                              process_name: "工程名",
                              process_code: "工程コード",
                              operation_code: "作業コード",
                              product_name: "製品名",
                              product_code: "製品コード",
                              resource_name: "資源名",
                              resource_code: "資源コード",
                            } as Record<string, string>
                          )[k]
                        }
                      </dt>
                      <dd>{String(v)}</dd>
                    </div>
                  ))}
            </dl>
            {selectedEquipment && (
              <>
                <button onClick={() => choose(selectedEquipment)}>
                  この設備を調べる
                </button>
                <button onClick={() => onUseEquipment(selectedEquipment)}>
                  この設備で対応案を比べる
                </button>
              </>
            )}
            <h3>この項目を含む経路</h3>
            <ol>
              {paths.map((p, i) => (
                <li key={i}>
                  {Array.isArray(p.nodes)
                    ? p.nodes.filter(node).map(titleOf).join(" → ")
                    : null}
                </li>
              ))}
            </ol>
            <details>
              <summary>技術情報</summary>
              <pre>{JSON.stringify(selectedData, null, 2)}</pre>
            </details>
          </>
        ) : (
          <>
            {root ? (
              <>
                <h3>{root.equipment_name}</h3>
                <p>{root.equipment_code}</p>
                <p>登録上の状態：{registeredState(model.currentState)}</p>
                <button onClick={() => onUseEquipment(root)}>
                  この設備で対応案を比べる
                </button>
              </>
            ) : (
              info("関係図の項目を選ぶと、属性と経路を表示します。")
            )}
          </>
        )}
      </aside>
    </section>
  );
}
