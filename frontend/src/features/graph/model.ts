import { object, type Envelope, type JsonObject } from "../../api/client";
export interface NodeRef {
  entity_type: string;
  entity_id: string;
}
export interface GraphView {
  data: JsonObject;
  nodes: NodeRef[];
  edges: { source: string; target: string; label: string }[];
  limited: boolean;
}
export const nodeKey = (node: NodeRef) =>
  node.entity_type + ":" + node.entity_id;
export function node(value: unknown): value is NodeRef {
  return (
    object(value) &&
    typeof value.entity_type === "string" &&
    typeof value.entity_id === "string"
  );
}
export function graphView(result: Envelope): GraphView | null {
  const pkg = result.data.decision_package;
  let data: unknown = object(pkg) ? pkg.impact : undefined;
  if (!object(data) && Array.isArray(result.data.tool_results)) {
    const row = result.data.tool_results.find(
      (item) => object(item) && item.tool === "trace_downstream_impact",
    );
    data = object(row) ? row.data : undefined;
  }
  if (
    !object(data) ||
    data.graph_sync_state !== "CURRENT" ||
    !Array.isArray(data.representative_paths)
  )
    return null;
  const nodes = new Map<string, NodeRef>();
  const edges = new Map<
    string,
    { source: string; target: string; label: string }
  >();
  let limited = false;
  for (const path of data.representative_paths) {
    if (
      !object(path) ||
      !Array.isArray(path.nodes) ||
      !Array.isArray(path.edges) ||
      !path.nodes.every(node) ||
      path.edges.length !== path.nodes.length - 1
    ) {
      limited = true;
      continue;
    }
    if (
      nodes.size +
        path.nodes.filter((item) => !nodes.has(nodeKey(item))).length >
      100
    ) {
      limited = true;
      continue;
    }
    for (const item of path.nodes) nodes.set(nodeKey(item), item);
    const pathNodes = path.nodes;
    path.edges.forEach((edge, index) => {
      if (!object(edge) || typeof edge.relation_type !== "string") {
        limited = true;
        return;
      }
      const source = nodeKey(pathNodes[index]);
      const target = nodeKey(pathNodes[index + 1]);
      const label = edge.relation_type;
      edges.set(source + ">" + target + ":" + label, { source, target, label });
    });
  }
  return {
    data,
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    limited,
  };
}
export function detail(result: Envelope, nodeRef: NodeRef): JsonObject {
  const pkg = result.data.decision_package;
  if (
    object(pkg) &&
    object(pkg.equipment) &&
    nodeRef.entity_type === "Equipment" &&
    pkg.equipment.equipment_id === nodeRef.entity_id
  )
    return pkg.equipment;
  if (Array.isArray(result.data.tool_results))
    for (const row of result.data.tool_results) {
      if (!object(row) || !object(row.data)) continue;
      const data = row.data;
      if (
        nodeRef.entity_type === "Equipment" &&
        data.equipment_id === nodeRef.entity_id
      )
        return data;
      if (Array.isArray(data.items)) {
        const match = data.items.find(
          (item) =>
            object(item) &&
            nodeRef.entity_type === "Equipment" &&
            item.equipment_id === nodeRef.entity_id,
        );
        if (object(match)) return match;
      }
    }
  return { entity_type: nodeRef.entity_type, entity_id: nodeRef.entity_id };
}
export function label(result: Envelope, item: NodeRef): string {
  const data = detail(result, item);
  return typeof data.equipment_code === "string"
    ? data.equipment_code
    : typeLabel(item.entity_type) + " · " + item.entity_id.slice(0, 8);
}

export function typeLabel(kind: string): string {
  return (
    (
      {
        Equipment: "設備",
        Process: "工程",
        ProductionOperation: "生産作業",
        Product: "製品",
        InfrastructureResource: "インフラ",
      } as Record<string, string>
    )[kind] ?? kind
  );
}
