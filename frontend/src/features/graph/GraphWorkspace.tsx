import { useMemo, useState, type ReactNode } from "react";
import { object, type Envelope } from "../../api/client";
import { GraphCanvas } from "./GraphCanvas";
import {
  detail,
  graphAnalyses,
  graphView,
  label,
  node,
  nodeKey,
  typeLabel,
  type NodeRef,
} from "./model";

export function GraphWorkspace({
  result,
  selected,
  busy,
  stale,
  onSelect,
  onInvestigate,
  onEvidence,
  onStart,
  onRefresh,
  emptyContent,
}: {
  result: Envelope | null;
  selected: NodeRef | null;
  busy: boolean;
  stale: boolean;
  onSelect: (item: NodeRef) => void;
  onInvestigate: (text: string) => void;
  onEvidence: () => void;
  onStart: () => void;
  onRefresh: () => void;
  emptyContent?: ReactNode;
}) {
  const [choice, setChoice] = useState("");
  const entries = useMemo(
    () => (result ? graphAnalyses(result) : []),
    [result],
  );
  const active = entries.find((entry) => entry.key === choice) ?? entries[0];
  const view = useMemo(
    () => (result ? graphView(result, active?.key) : null),
    [result, active?.key],
  );
  const selection =
    selected && view?.nodes.find((item) => nodeKey(item) === nodeKey(selected));
  const properties = result && selection ? detail(result, selection) : null;
  const paths =
    view && Array.isArray(view.data.representative_paths)
      ? view.data.representative_paths.filter(
          (path) =>
            object(path) &&
            Array.isArray(path.nodes) &&
            path.nodes.every(node) &&
            (!selection ||
              path.nodes.some((item) => nodeKey(item) === nodeKey(selection))),
        )
      : [];
  const downstream =
    active?.key === "impact" ||
    active?.key.startsWith("trace_downstream_impact:");
  function analyze(tool: string, args: Record<string, unknown>) {
    onInvestigate(
      `公開Read Tool ${tool} を次の明示引数で呼び出して結果と未評価事項を説明してください。変更要求は作成しないでください。${JSON.stringify(args)}`,
    );
  }
  return (
    <section className="graph-workspace" aria-label="関係と影響の調査">
      <div className="graph-workspace-heading">
        <div>
          <p className="eyebrow">RELATIONSHIPS & IMPACT</p>
          <h1>何とつながり、どこまで影響するか</h1>
        </div>
        <span className="badge">
          {view
            ? `取得時のGraph：${String(view.data.graph_sync_state)}`
            : "Graph未取得"}
        </span>
      </div>
      {stale && (
        <p className="notice">
          前回取得した関係です。変更後の状態は再調査してください。
        </p>
      )}
      {entries.length > 0 && (
        <div className="graph-question-bar">
          <label>
            表示する調査
            <select
              aria-label="表示するGraph分析"
              value={active?.key ?? ""}
              onChange={(event) => setChoice(event.target.value)}
            >
              {entries.map((entry) => (
                <option key={entry.key} value={entry.key}>
                  {entry.title}
                </option>
              ))}
            </select>
          </label>
          <button disabled={busy} onClick={onRefresh}>
            起点の関係を再取得
          </button>
        </div>
      )}
      {!view || !result ? (
        <div className="graph-empty">
          <span className="empty-network" aria-hidden="true">
            ◎ — ◇ — ◎
          </span>
          <h2>設備の停止が、どこまで影響するか調べる</h2>
          <p>
            設備・工程・生産作業・製品・インフラの関係を表示します。
            <br />
            起点から届く範囲と経路を、Graphと根拠で確認できます。
          </p>
          {emptyContent ?? (
            <button
              className="start-investigation"
              disabled={busy}
              onClick={onStart}
            >
              {busy
                ? "設備候補を取得しています…"
                : "登録設備を表示して調査を始める"}
            </button>
          )}
          {entries.length > 0 && (
            <p className="notice">
              この応答のGraphは表示できません。非CURRENTや未取得の結果を正常なGraphとして表示しません。
            </p>
          )}
        </div>
      ) : (
        <>
          <div className="impact-summary" aria-label="探索範囲の概要">
            <div>
              <span>{downstream ? "直接の影響候補" : "取得した関係先"}</span>
              <strong>
                {downstream && Array.isArray(view.data.direct_nodes)
                  ? view.data.direct_nodes.length
                  : Array.isArray(view.data.reached_nodes)
                    ? view.data.reached_nodes.length
                    : view.nodes.length}
                件
              </strong>
            </div>
            <div>
              <span>{downstream ? "間接の影響候補" : "代表経路"}</span>
              <strong>
                {downstream && Array.isArray(view.data.indirect_nodes)
                  ? view.data.indirect_nodes.length
                  : Array.isArray(view.data.representative_paths)
                    ? view.data.representative_paths.length
                    : 0}
                件
              </strong>
            </div>
            <div>
              <span>探索の完全性</span>
              <strong>
                {view.data.complete === true
                  ? "指定範囲は完了"
                  : "不完全・判定不能"}
              </strong>
            </div>
          </div>
          <div className="graph-inspection-layout">
            <div className="graph-stage">
              <div className="entity-legend">
                {[
                  "Equipment",
                  "Process",
                  "ProductionOperation",
                  "Product",
                  "InfrastructureResource",
                ].map((type) => (
                  <span key={type} className={`legend-${type}`}>
                    {typeLabel(type)}
                  </span>
                ))}
              </div>
              <GraphCanvas
                view={view}
                result={result}
                selected={selection ? nodeKey(selection) : null}
                onSelect={onSelect}
                classification={
                  downstream
                    ? "影響候補"
                    : active?.key === "upstream_dependencies" ||
                        active?.key.startsWith("trace_upstream_dependencies:")
                      ? "依存先"
                      : "関係先"
                }
              />
            </div>
            <section
              className="node-inspector"
              aria-label="選択ノードと根拠経路"
            >
              <h2>
                {selection
                  ? label(result, selection)
                  : "ノードを選んで経路を確認"}
              </h2>
              {selection ? (
                <>
                  <p className="muted">{typeLabel(selection.entity_type)}</p>
                  <dl className="node-properties">
                    {properties &&
                      Object.entries(properties)
                        .filter(
                          ([, value]) =>
                            typeof value === "string" ||
                            typeof value === "number" ||
                            typeof value === "boolean",
                        )
                        .map(([key, value]) => (
                          <div key={key}>
                            <dt>{key}</dt>
                            <dd>{String(value)}</dd>
                          </div>
                        ))}
                  </dl>
                  <button
                    disabled={busy}
                    onClick={() => {
                      const field = (
                        {
                          Equipment: "equipment",
                          Process: "process",
                          ProductionOperation: "production_operation",
                          Product: "product",
                          InfrastructureResource: "infrastructure_resource",
                        } as Record<string, string>
                      )[selection.entity_type];
                      if (field)
                        analyze(`get_${field}`, {
                          [`${field}_id`]: selection.entity_id,
                        });
                    }}
                  >
                    名称・属性を取得
                  </button>
                  <button onClick={onEvidence}>この調査の根拠を開く</button>
                </>
              ) : (
                <p className="muted">
                  Graph上のノードを選ぶと、取得済みの属性と、そのノードを含む経路を表示します。
                </p>
              )}
              <h3>根拠となる代表経路</h3>
              {selection && paths.length === 0 && (
                <p>表示できる代表経路はありません。</p>
              )}
              {selection && (
                <ol className="path-list">
                  {paths.map((path, index) =>
                    object(path) && Array.isArray(path.nodes) ? (
                      <li key={index}>
                        {path.nodes.filter(node).map((item, n) => (
                          <span key={`${nodeKey(item)}:${n}`}>
                            {n > 0 && <span aria-hidden="true"> → </span>}
                            <button
                              className="path-node"
                              onClick={() => onSelect(item)}
                            >
                              {label(result, item)}
                            </button>
                          </span>
                        ))}
                      </li>
                    ) : null,
                  )}
                </ol>
              )}
            </section>
          </div>
          <p className="notice">
            取得した関係と探索範囲の結果です。工場全体の一覧ではありません。依存到達や構造成立だけで、実停止・能力・安全・経済影響を断定しません。
            {view.data.complete !== true
              ? ` 探索制限：${String(view.data.limit_reason ?? "未確認")}`
              : ""}
          </p>
        </>
      )}
    </section>
  );
}
