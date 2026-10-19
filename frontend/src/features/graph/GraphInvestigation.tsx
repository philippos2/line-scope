import { useState } from "react";
import { type Envelope } from "../../api/client";
import { label, nodeKey, type NodeRef } from "./model";

export function GraphInvestigation({
  result,
  selected,
  busy,
  onAnalyze,
  initiallyOpen = true,
}: {
  initiallyOpen?: boolean;
  result: Envelope;
  selected: NodeRef | null;
  busy: boolean;
  onAnalyze: (tool: string, args: Record<string, unknown>) => void;
}) {
  const [targets, setTargets] = useState<NodeRef[]>([]);
  const [excluded, setExcluded] = useState<NodeRef[]>([]);
  const [candidates, setCandidates] = useState<NodeRef[]>([]);
  const [automatic, setAutomatic] = useState(true);
  function group(
    title: string,
    items: NodeRef[],
    set: (items: NodeRef[]) => void,
  ) {
    return (
      <section className="graph-selection-group" aria-label={title}>
        <h3>
          {title}（{items.length}件）
        </h3>
        <button
          disabled={
            busy ||
            !selected ||
            items.some(
              (item) => selected && nodeKey(item) === nodeKey(selected),
            )
          }
          onClick={() => selected && set([...items, selected])}
        >
          選択ノードを追加：{title}
        </button>
        {items.length ? (
          <ul>
            {items.map((item) => (
              <li key={nodeKey(item)}>
                <span>{label(result, item)}</span>{" "}
                <button
                  disabled={busy}
                  aria-label={`${title}から${label(result, item)}を外す`}
                  onClick={() =>
                    set(
                      items.filter((value) => nodeKey(value) !== nodeKey(item)),
                    )
                  }
                >
                  外す
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">関係図で項目を選んで追加してください。</p>
        )}
      </section>
    );
  }
  return (
    <details className="graph-investigation" open={initiallyOpen}>
      <summary>詳しい分析</summary>
      <p>
        製品や生産作業を重要対象に追加し、依存先の共通点や、設備・インフラを失った場合の構造を調べます。
      </p>
      <div className="graph-selection-grid">
        {group("重要対象", targets, setTargets)}
        {group("除外対象", excluded, setExcluded)}
        <div>
          <label>
            <input
              type="checkbox"
              checked={automatic}
              disabled={busy}
              onChange={(event) => setAutomatic(event.target.checked)}
            />
            単一障害点の候補を必須上流から自動探索
          </label>
          {!automatic && group("単一障害点の候補", candidates, setCandidates)}
        </div>
      </div>
      <div className="graph-analysis-actions">
        <button
          disabled={busy || targets.length < 2}
          onClick={() => onAnalyze("find_common_dependencies", { targets })}
        >
          共通依存を調べる
        </button>
        <button
          disabled={busy || !targets.length || !excluded.length}
          onClick={() =>
            onAnalyze("find_alternative_paths", {
              important_targets: targets,
              excluded_nodes: excluded,
            })
          }
        >
          除外後の代替経路を調べる
        </button>
        <button
          disabled={
            busy || !targets.length || (!automatic && !candidates.length)
          }
          onClick={() =>
            onAnalyze("find_single_point_failure_candidates", {
              important_targets: targets,
              ...(!automatic ? { candidate_nodes: candidates } : {}),
            })
          }
        >
          単一障害点候補を調べる
        </button>
      </div>
      <p className="muted">
        共通依存には重要対象が2件以上必要です。代替は除外対象をまとめて除外し、単一障害点は候補を1件ずつ除外して評価します。構造成立は実運転・能力・安全の保証ではありません。
      </p>
    </details>
  );
}
