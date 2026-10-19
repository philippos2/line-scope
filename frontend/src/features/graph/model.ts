import type { NodeLabelState } from "./labelLoader";
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
export const graphTools: Record<string, string> = {
  trace_downstream_impact: "停止すると、どこまで影響するか",
  trace_upstream_dependencies: "何に依存しているか",
  find_common_dependencies: "共通して依存するものは何か",
  find_alternative_paths: "除外しても代替経路は成立するか",
  find_single_point_failure_candidates: "どこが単一障害点の候補か",
};
export function graphAnalyses(
  result: Envelope,
): { key: string; title: string; data: JsonObject }[] {
  const entries: { key: string; title: string; data: JsonObject }[] = [];
  const pkg = result.data.decision_package;
  if (object(pkg)) {
    for (const [key, tool] of [
      ["impact", "trace_downstream_impact"],
      ["upstream_dependencies", "trace_upstream_dependencies"],
    ]) {
      if (object(pkg[key]))
        entries.push({ key, title: graphTools[tool], data: pkg[key] });
    }
  }
  if (Array.isArray(result.data.tool_results))
    result.data.tool_results.forEach((row, index) => {
      if (
        object(row) &&
        typeof row.tool === "string" &&
        graphTools[row.tool] &&
        object(row.data)
      )
        entries.push({
          key: `${row.tool}:${index}`,
          title:
            typeof row.title === "string" ? row.title : graphTools[row.tool],
          data: row.data,
        });
    });
  return entries;
}
export function graphView(result: Envelope, key?: string): GraphView | null {
  const entries = graphAnalyses(result);
  const data = (key ? entries.find((entry) => entry.key === key) : entries[0])
    ?.data;
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
  function addSubject(item: unknown) {
    if (!node(item) || nodes.has(nodeKey(item))) return;
    if (nodes.size >= 100) limited = true;
    else nodes.set(nodeKey(item), item);
  }
  addSubject(data.target);
  // Keep explicitly returned subjects visible even when there is no path.
  for (const field of [
    "targets",
    "important_targets",
    "excluded_nodes",
    "common_candidates",
  ]) {
    if (Array.isArray(data[field]))
      for (const item of data[field]) addSubject(item);
  }
  if (Array.isArray(data.findings))
    for (const finding of data.findings)
      if (object(finding)) {
        addSubject(finding.important_target);
        addSubject(finding.candidate);
      }
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
const fields: Record<string, string> = {
  Equipment: "equipment",
  Process: "process",
  ProductionOperation: "production_operation",
  Product: "product",
  InfrastructureResource: "infrastructure_resource",
};
export function detail(result: Envelope, nodeRef: NodeRef): JsonObject {
  const prefix = fields[nodeRef.entity_type];
  const id = `${prefix}_id`;
  const pkg = result.data.decision_package;
  if (
    object(pkg) &&
    object(pkg.equipment) &&
    nodeRef.entity_type === "Equipment" &&
    pkg.equipment.equipment_id === nodeRef.entity_id
  )
    return pkg.equipment;
  if (Array.isArray(result.data.tool_results))
    for (const row of [...result.data.tool_results].reverse()) {
      if (!object(row) || !object(row.data)) continue;
      if (row.tool === `get_${prefix}` && row.data[id] === nodeRef.entity_id)
        return row.data;
      if (row.tool === `search_${prefix}` && Array.isArray(row.data.items)) {
        const match = row.data.items.find(
          (item) => object(item) && item[id] === nodeRef.entity_id,
        );
        if (object(match)) return match;
      }
    }
  return { entity_type: nodeRef.entity_type, entity_id: nodeRef.entity_id };
}
export function label(
  result: Envelope,
  item: NodeRef,
  state?: NodeLabelState,
): string {
  const data = detail(result, item);
  if (
    item.entity_type === "ProductionOperation" &&
    typeof data.operation_code === "string"
  )
    return data.operation_code;
  const prefix =
    item.entity_type === "InfrastructureResource"
      ? "resource"
      : fields[item.entity_type];
  const name = data[`${prefix}_name`],
    code = data[`${prefix}_code`];
  if (typeof name === "string" && typeof code === "string") {
    if (name === code) return code;
    const displayName = name.endsWith(` ${code}`)
      ? name.slice(0, -code.length).trimEnd()
      : name;
    return `${displayName} · ${code}`;
  }
  if (typeof code === "string") return code;
  if (typeof name === "string") return name;
  return `${typeLabel(item.entity_type)} · ${state?.status === "error" ? "名称取得に失敗" : state?.status === "limited" ? "名称取得の上限" : "読み込み中"}`;
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

// Highlight only edges in returned representative paths containing the selection.
// This is a display projection, not a new dependency traversal.
export function pathHighlights(
  view: GraphView,
  selected: string | null,
): Set<string> {
  const keys = new Set<string>();
  if (!selected || !Array.isArray(view.data.representative_paths)) return keys;
  for (const path of view.data.representative_paths) {
    if (
      !object(path) ||
      !Array.isArray(path.nodes) ||
      !path.nodes.every(node) ||
      !Array.isArray(path.edges) ||
      path.edges.length !== path.nodes.length - 1 ||
      !path.nodes.some((item) => nodeKey(item) === selected)
    )
      continue;
    const nodes = path.nodes;
    path.edges.forEach((edge, index) => {
      if (object(edge) && typeof edge.relation_type === "string")
        keys.add(
          `${nodeKey(nodes[index])}>${nodeKey(nodes[index + 1])}:${edge.relation_type}`,
        );
    });
  }
  return keys;
}
