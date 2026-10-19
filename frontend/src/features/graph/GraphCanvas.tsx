import type { NodeLabelStates } from "./labelLoader";
import { useEffect, useMemo, useRef } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  MarkerType,
  Position,
  useNodesState,
  type Node,
  type ReactFlowInstance,
  type Viewport,
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

const EMPTY_CANDIDATES: string[] = [];
const EMPTY_LABELS: NodeLabelStates = {};
const EMPTY_STATES: Record<string, string> = {};

export type GraphMemory = {
  positions: Record<string, { x: number; y: number }>;
  viewport?: Viewport;
};

export function GraphCanvas({
  memory,
  onMemory,
  view,
  result,
  selected,
  onSelect,
  classification = "影響候補",
  candidates = EMPTY_CANDIDATES,
  registeredStates = EMPTY_STATES,
  labelStates = EMPTY_LABELS,
}: {
  memory?: GraphMemory;
  onMemory?: (value: GraphMemory) => void;
  view: GraphView;
  result: Envelope;
  selected: string | null;
  onSelect: (node: NodeRef) => void;
  classification?: string;
  candidates?: string[];
  registeredStates?: Record<string, string>;
  labelStates?: NodeLabelStates;
}) {
  const flow = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  useEffect(() => {
    if (!memory?.viewport || !flow.current) return;
    const current = flow.current.getViewport();
    const next = memory.viewport;
    if (
      current.x !== next.x ||
      current.y !== next.y ||
      current.zoom !== next.zoom
    )
      void flow.current.setViewport(next);
  }, [memory?.viewport]);
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
          name = label(result, item, labelStates[nodeKey(item)]);
        nodes.push({
          id: key,
          position: memory?.positions[key] ?? {
            x: depth * 285,
            y: index * 140,
          },
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          className: `entity-${item.entity_type}${candidates.includes(key) ? " alternative-node" : ""}`,
          ariaLabel: `${typeLabel(item.entity_type)}：${name}`,
          data: {
            label: (
              <>
                <span className="entity-kind">
                  {typeLabel(item.entity_type)}
                </span>
                <strong>{name}</strong>
                <span className="node-classification">
                  {candidates.includes(key)
                    ? "代替候補"
                    : direct.has(key)
                      ? `直接${classification}`
                      : indirect.has(key)
                        ? `間接${classification}`
                        : depth === 0
                          ? "探索の起点・対象"
                          : "関係先"}
                </span>
                {registeredStates[item.entity_id] && (
                  <span>{registeredStates[item.entity_id]}</span>
                )}
              </>
            ),
          },
        });
      });
    return nodes;
  }, [
    memory,
    view,
    result,
    direct,
    indirect,
    classification,
    candidates,
    registeredStates,
    labelStates,
  ]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  useEffect(() => {
    setNodes((old) =>
      initialNodes.map((item) => ({
        ...old.find((previous) => previous.id === item.id),
        ...item,
        position: item.position,
      })),
    );
  }, [initialNodes, setNodes]);
  const edges: Edge[] = view.edges.map((edge, index) => ({
    id: `${edge.source}>${edge.target}:${edge.label}:${index}`,
    source: edge.source,
    target: edge.target,
    label:
      (
        {
          SUPPLIES: "供給",
          PRODUCES: "生産",
          PRECEDES: "先行",
          USES: "使用",
          DEPENDS_ON: "依存",
          CAN_SUBSTITUTE: "代替関係",
          CONTROLS: "制御",
        } as Record<string, string>
      )[edge.label] ?? "つながり",
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
      <div className="relation-canvas" aria-label="つながりと影響範囲の関係図">
        <ReactFlow<Node, Edge>
          onInit={(instance) => {
            flow.current = instance;
          }}
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
          fitView={!memory?.viewport}
          defaultViewport={memory?.viewport}
          onMoveEnd={(_, viewport) => {
            const previous = memory?.viewport;
            if (
              !previous ||
              previous.x !== viewport.x ||
              previous.y !== viewport.y ||
              previous.zoom !== viewport.zoom
            )
              onMemory?.({ positions: memory?.positions ?? {}, viewport });
          }}
          onNodeDragStop={(_, dragged) =>
            onMemory?.({
              positions: {
                ...memory?.positions,
                [dragged.id]: dragged.position,
              },
              viewport: memory?.viewport,
            })
          }
          minZoom={0.2}
          maxZoom={2.5}
          ariaLabelConfig={{
            "controls.zoomIn.ariaLabel": "関係図を拡大",
            "controls.zoomOut.ariaLabel": "関係図を縮小",
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
        項目を選ぶと、その項目を含む経路を強調します。
        {view.limited ? " 描画範囲に制限があります。" : ""}
      </p>
      <details className="graph-node-access">
        <summary>項目を一覧から選ぶ（{view.nodes.length}件）</summary>
        <div className="node-list" aria-label="関係図の項目一覧">
          {view.nodes.map((item) => (
            <button
              key={nodeKey(item)}
              aria-pressed={selected === nodeKey(item)}
              onClick={() => onSelect(item)}
            >
              {label(result, item, labelStates[nodeKey(item)])}
            </button>
          ))}
        </div>
      </details>
    </>
  );
}
