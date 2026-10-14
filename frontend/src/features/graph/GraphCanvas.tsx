import { object, type Envelope } from "../../api/client";
import { label, nodeKey, node, type GraphView, type NodeRef } from "./model";
export function GraphCanvas({
  view,
  result,
  selected,
  onSelect,
}: {
  view: GraphView;
  result: Envelope;
  selected: string | null;
  onSelect: (node: NodeRef) => void;
}) {
  const distances = object(view.data.distances) ? view.data.distances : {};
  const groups = new Map<number, NodeRef[]>();
  view.nodes.forEach((item, index) => {
    const raw = distances[nodeKey(item)];
    const depth =
      typeof raw === "number" && Number.isInteger(raw) && raw >= 0 && raw <= 16
        ? raw
        : index;
    groups.set(depth, [...(groups.get(depth) ?? []), item]);
  });
  const rows = Math.max(
    1,
    ...[...groups.values()].map((items) => items.length),
  );
  const positions = new Map<string, { x: number; y: number }>();
  for (const [depth, items] of groups)
    items.forEach((item, index) =>
      positions.set(nodeKey(item), {
        x: 30 + depth * 245,
        y: 35 + ((rows - items.length) / 2 + index) * 115,
      }),
    );
  const width = Math.max(760, (Math.max(0, ...groups.keys()) + 1) * 245 + 30);
  const height = Math.max(300, rows * 115 + 70);
  const direct = new Set(
    Array.isArray(view.data.direct_nodes)
      ? view.data.direct_nodes.filter(node).map(nodeKey)
      : [],
  );
  const indirect = new Set(
    Array.isArray(view.data.indirect_nodes)
      ? view.data.indirect_nodes.filter(node).map(nodeKey)
      : [],
  );
  return (
    <>
      <div className="graph-scroll">
        <svg
          className="graph"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="サーバ代表経路のGraph。ノード操作は下の一覧から行えます。"
        >
          <defs>
            <marker
              id="arrow"
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="4"
              orient="auto"
            >
              <path d="M0 0L8 4L0 8" fill="#78c9c5" />
            </marker>
          </defs>
          {view.edges.map((edge, index) => {
            const a = positions.get(edge.source);
            const b = positions.get(edge.target);
            if (!a || !b) return null;
            const dx = b.x - a.x,
              dy = b.y - a.y;
            const fraction =
              1 / Math.max(Math.abs(dx) / 105, Math.abs(dy) / 31);
            if (!Number.isFinite(fraction)) return null;
            return (
              <g key={index}>
                <path
                  className="edge"
                  d={`M${a.x + 105 + dx * fraction},${a.y + 31 + dy * fraction} L${b.x + 105 - dx * fraction},${b.y + 31 - dy * fraction}`}
                  markerEnd="url(#arrow)"
                />
                <text
                  className="edge-label"
                  x={(a.x + b.x) / 2 + 105}
                  y={(a.y + b.y) / 2 + 22}
                >
                  {edge.label}
                </text>
              </g>
            );
          })}
          {view.nodes.map((item) => {
            const key = nodeKey(item);
            const p = positions.get(key)!;
            return (
              <g
                key={key}
                className={selected === key ? "selected-node" : "node"}
                onClick={() => onSelect(item)}
              >
                <rect x={p.x} y={p.y} width="210" height="62" rx="7" />
                <text x={p.x + 12} y={p.y + 25}>
                  {label(result, item)}
                </text>
                <text className="node-type" x={p.x + 12} y={p.y + 46}>
                  {direct.has(key)
                    ? "直接影響候補"
                    : indirect.has(key)
                      ? "間接影響候補"
                      : item.entity_type}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <p className="muted">
        矢印は返された経路の探索方向です。全Graphの一覧ではありません。
        {view.limited ? " 描画範囲は制限されています。" : ""}
      </p>
      <div className="node-list" aria-label="Graphノードの一覧">
        {view.nodes.map((item) => (
          <button
            key={nodeKey(item)}
            onClick={() => onSelect(item)}
            aria-pressed={selected === nodeKey(item)}
          >
            {label(result, item)}
          </button>
        ))}
      </div>
    </>
  );
}
