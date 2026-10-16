import { useEffect, useMemo } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  MarkerType,
  Position,
  useNodesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { object, type Envelope } from "../../api/client";
import {
  label,
  nodeKey,
  node,
  pathHighlights,
  typeLabel,
  type GraphView,
  type NodeRef,
} from "./model";

export function GraphCanvas({
  view,
  result,
  selected,
  onSelect,
  classification = "影響候補",
}: {
  view: GraphView;
  result: Envelope;
  selected: string | null;
  onSelect: (node: NodeRef) => void;
  classification?: string;
}) {
  const direct = useMemo(
    () =>
      new Set(
        Array.isArray(view.data.direct_nodes)
          ? view.data.direct_nodes.filter(node).map(nodeKey)
          : [],
      ),
    [view],
  );
  const indirect = useMemo(
    () =>
      new Set(
        Array.isArray(view.data.indirect_nodes)
          ? view.data.indirect_nodes.filter(node).map(nodeKey)
          : [],
      ),
    [view],
  );
  const highlighted = useMemo(
    () => pathHighlights(view, selected),
    [view, selected],
  );
  const initialNodes = useMemo<Node[]>(() => {
    const distances = object(view.data.distances) ? view.data.distances : {};
    const groups = new Map<number, NodeRef[]>();
    const depths = new Map<string, number>();
    if (Array.isArray(view.data.representative_paths))
      for (const path of view.data.representative_paths)
        if (object(path) && Array.isArray(path.nodes))
          path.nodes.filter(node).forEach((item, depth) => {
            const key = nodeKey(item);
            depths.set(key, Math.min(depths.get(key) ?? depth, depth));
          });
    view.nodes.forEach((item) => {
      const raw = distances[nodeKey(item)];
      const depth =
        typeof raw === "number" &&
        Number.isInteger(raw) &&
        raw >= 0 &&
        raw <= 16
          ? raw
          : (depths.get(nodeKey(item)) ?? 0);
      groups.set(depth, [...(groups.get(depth) ?? []), item]);
    });
    const nodes: Node[] = [];
    for (const [depth, items] of groups)
      items.forEach((item, index) => {
        const key = nodeKey(item),
          name = label(result, item);
        nodes.push({
          id: key,
          position: { x: depth * 285, y: index * 140 },
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          className: `entity-${item.entity_type}`,
          ariaLabel: `${typeLabel(item.entity_type)}：${name}`,
          data: {
            label: (
              <>
                <span className="entity-kind">
                  {typeLabel(item.entity_type)}
                </span>
                <strong>{name}</strong>
                <span className="node-classification">
                  {direct.has(key)
                    ? `直接${classification}`
                    : indirect.has(key)
                      ? `間接${classification}`
                      : depth === 0
                        ? "探索の起点・対象"
                        : "関係先"}
                </span>
              </>
            ),
          },
        });
      });
    return nodes;
  }, [view, result, direct, indirect, classification]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  useEffect(() => {
    setNodes(initialNodes);
  }, [initialNodes, setNodes]);
  const edges: Edge[] = view.edges.map((edge, index) => ({
    id: `${edge.source}>${edge.target}:${edge.label}:${index}`,
    source: edge.source,
    target: edge.target,
    label: edge.label,
    type: "smoothstep",
    className:
      selected && highlighted.has(`${edge.source}>${edge.target}:${edge.label}`)
        ? "path-highlight"
        : "",
    style: {
      stroke:
        selected &&
        highlighted.has(`${edge.source}>${edge.target}:${edge.label}`)
          ? "#f0bd66"
          : "#7395ad",
      strokeWidth:
        selected &&
        highlighted.has(`${edge.source}>${edge.target}:${edge.label}`)
          ? 3
          : 1.5,
    },
    markerEnd: { type: MarkerType.ArrowClosed, color: "#7395ad" },
  }));
  return (
    <>
      <div className="relation-canvas" aria-label="関係と影響範囲のGraph">
        <ReactFlow
          nodes={nodes.map((item) => ({
            ...item,
            selected: item.id === selected,
          }))}
          edges={edges}
          onNodesChange={onNodesChange}
          onNodeClick={(_, item) => {
            const found = view.nodes.find((row) => nodeKey(row) === item.id);
            if (found) onSelect(found);
          }}
          nodesConnectable={false}
          edgesReconnectable={false}
          deleteKeyCode={null}
          fitView
          minZoom={0.2}
          maxZoom={2.5}
          ariaLabelConfig={{
            "controls.zoomIn.ariaLabel": "Graphを拡大",
            "controls.zoomOut.ariaLabel": "Graphを縮小",
            "controls.fitView.ariaLabel": "全ノードを表示",
          }}
          colorMode="dark"
        >
          <Background gap={24} color="#2a3c4b" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>
      <p className="graph-caption">
        矢印はサーバが返した探索方向です。ノードを選ぶと、そのノードを含む代表経路を強調します。
        {view.limited ? " 描画範囲に制限があります。" : ""}
      </p>
      <details className="graph-node-access">
        <summary>Graphノードを一覧から選ぶ（{view.nodes.length}件）</summary>
        <div className="node-list" aria-label="Graphノードの一覧">
          {view.nodes.map((item) => (
            <button
              key={nodeKey(item)}
              aria-pressed={selected === nodeKey(item)}
              onClick={() => onSelect(item)}
            >
              {label(result, item)}
            </button>
          ))}
        </div>
      </details>
    </>
  );
}
