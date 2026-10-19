import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { object } from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { money } from "../incidents/model";
import {
  displayGraph,
  errorCode,
  explanation,
  registeredState,
  rows,
  searchEquipment,
  toolData,
} from "./readModel";
import { label } from "../graph/model";
import { availabilityLabel } from "./AlternativeAssessment";
import { comparisonOptions } from "./workspaceModel";
import type { useEquipmentInvestigation } from "./useEquipmentInvestigation";

type Model = ReturnType<typeof useEquipmentInvestigation>;
export function WorkspaceHeader({
  root,
  model,
  onChoose,
  onInspect,
  children,
  tabs,
}: {
  children: ReactNode;
  tabs: ReactNode;
  root: EquipmentCandidate | null;
  model: Model;
  onChoose: (item: EquipmentCandidate | null) => boolean;
  onInspect: (section: "loss" | "alternative") => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<EquipmentCandidate[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [searched, setSearched] = useState(false),
    [more, setMore] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function search(e?: FormEvent) {
    e?.preventDefault();
    controller.current?.abort();
    const active = new AbortController();
    controller.current = active;
    setBusy(true);
    setFound([]);
    setError("");
    setSearched(false);
    try {
      const result = await searchEquipment(query, active.signal);
      if (active.signal.aborted) return;
      setFound(result.items);
      setMore(result.more);
      setSearched(true);
      setError(result.errors.map(explanation).join("、"));
    } catch (err) {
      if (!active.signal.aborted) setError(explanation(errorCode(err)));
    } finally {
      if (!active.signal.aborted) setBusy(false);
    }
  }
  const { states } = model;
  const rawLoss = states.loss?.value;
  const loss = object(rawLoss?.data.loss) ? rawLoss.data.loss : null;
  const impact = rows(rawLoss?.data.impacts).some(
    (r) => r.equipment_id === root?.equipment_id,
  );
  const down = states.down?.value;
  const full = down
    ? displayGraph(down, states.alternatives?.value, model.metadata)
    : null;
  const options = comparisonOptions(states.comparison?.value).filter(
    (o) => o.option === "SUBSTITUTE",
  );
  const candidates = rows(
    toolData(states.alternatives?.value).alternatives,
  ).flatMap((r) => rows(r.candidates));
  const updated = states.down?.value?.evidence;
  const observed = String(
    updated?.observed_at ??
      rows(updated?.tool_results)[0]?.graph_observed_at ??
      "",
  );
  const time =
    observed && !Number.isNaN(Date.parse(observed))
      ? new Intl.DateTimeFormat("ja-JP", {
          timeZone: "Asia/Tokyo",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }).format(new Date(observed)) + "（日本時間）"
      : down
        ? "取得済み（時刻情報なし）"
        : "未取得";
  const lossText = !root
    ? "設備未選択"
    : model.currentState === "RUNNING"
      ? "稼働中のため算定対象外"
      : impact && loss
        ? loss.complete === true
          ? money(loss.loss_per_hour)
          : rows(loss.items).some((r) => r.included_in_subtotal === true)
            ? `判明分のみ ${money(loss.known_subtotal_per_hour)}（不明あり）`
            : "算定条件を確認できません"
        : states.loss?.loading
          ? "算定中"
          : "未算定";
  return (
    <div className="investigation-layout">
      <aside className="equipment-search-panel" aria-label="起点設備の検索">
        <h2>設備を探す</h2>
        <form onSubmit={search}>
          <label htmlFor="equipment-search">設備名・コード</label>
          <input
            id="equipment-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="設備名の一部、またはコード"
          />
          <button disabled={busy}>検索</button>
        </form>
        {busy && <p role="status">設備を探しています…</p>}
        {error && (
          <div className="read-failure" role="alert">
            <p>{error}</p>
            <button onClick={() => void search()}>再試行</button>
          </div>
        )}
        {searched && !found.length && (
          <p>
            該当する設備がありません。設備名の一部、またはコードの全体を入力してください。コードは大文字・小文字を区別します。
          </p>
        )}
        {found.map((item) => (
          <button
            className="equipment-result"
            key={item.equipment_id}
            aria-pressed={root?.equipment_id === item.equipment_id}
            onClick={() => {
              onChoose(item);
            }}
          >
            <strong>{item.equipment_name}</strong>
            <span>{item.equipment_code}</span>
          </button>
        ))}
        {more && (
          <p>ほかにも設備があります。名前やコードで絞り込んでください。</p>
        )}
        {root && (
          <button
            onClick={() => {
              onChoose(null);
            }}
          >
            選択を解除
          </button>
        )}
      </aside>
      <div className="investigation-main">
        {tabs}
        <section className="workspace-context" aria-label="調査の要約">
          <button
            className="workspace-summary-toggle"
            aria-expanded={expanded}
            aria-controls="workspace-summary-contents"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "要約を折りたたむ" : "損害額・代替・取得時刻を表示"}
          </button>
          <div
            id="workspace-summary-contents"
            className={`summary-grid ${expanded ? "summary-expanded" : ""}`}
          >
            <div>
              <strong>起点</strong>
              <p>
                {root
                  ? `${root.equipment_name} · ${root.equipment_code} ／登録上：${registeredState(model.currentState)}`
                  : "設備未選択"}
                {model.stale ? "（更新前）" : ""}
              </p>
              <button
                onClick={() =>
                  document.getElementById("equipment-search")?.focus()
                }
              >
                {root ? "起点を変更" : "設備を選ぶ"}
              </button>
            </div>
            <div>
              <strong>推定損害額</strong>
              <button onClick={() => onInspect("loss")}>
                {lossText}
                {model.stale ? "（更新前）" : ""}
              </button>
            </div>
            <div>
              <strong>代替の可否</strong>
              {options.length ? (
                options.map((option, i) => {
                  const fact = candidates.find(
                    (c) =>
                      object(c.candidate) &&
                      c.candidate.entity_id === option.equipment_id,
                  );
                  const basis = object(option.structural_basis)
                    ? option.structural_basis
                    : {};
                  const available =
                    fact?.availability === "AVAILABLE" &&
                    basis.status === "AVAILABLE";
                  const product = full
                    ? label(full, {
                        entity_type: "Product",
                        entity_id: String(option.product_id),
                      })
                    : "対象製品";
                  const equipment = model.candidateEquipment.find(
                    (c) => c.equipment_id === option.equipment_id,
                  );
                  return (
                    <button key={i} onClick={() => onInspect("alternative")}>
                      {equipment?.equipment_code ?? "候補確認中"}：
                      {availabilityLabel(fact?.availability)}・
                      {available && option.capacity_status === "SUFFICIENT"
                        ? `${product}のみ能力充足（運転許可ではありません）`
                        : available
                          ? "能力条件を確認してください"
                          : "提案なし"}
                      {model.stale ? "（更新前）" : ""}
                    </button>
                  );
                })
              ) : (
                <p>
                  {states.alternatives?.loading ? "調査中" : "未評価・提案なし"}
                  {model.stale ? "（更新前）" : ""}
                </p>
              )}
            </div>
            <div>
              <strong>調査の取得時刻</strong>
              <p>
                {time}
                {model.stale ? " ／更新前" : ""}
              </p>
            </div>
          </div>
        </section>
        {children}
      </div>
    </div>
  );
}
