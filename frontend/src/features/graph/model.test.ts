import { expect, it } from "vitest";
import { envelope } from "../../api/client";
import { graphView, pathHighlights } from "./model";
const a = { entity_type: "Equipment", entity_id: "a" },
  b = { entity_type: "Product", entity_id: "b" };
function response(paths: unknown[]) {
  return envelope({
    request_id: "r",
    context_id: null,
    status: "ok",
    answer: "",
    data: {
      tool_results: [
        {
          tool: "trace_downstream_impact",
          data: {
            representative_paths: paths,
            complete: false,
            graph_sync_state: "CURRENT",
          },
        },
      ],
    },
    evidence: {},
    warnings: [],
    errors: [],
  });
}
it("keeps typed nodes and server path direction without inventing labels", () => {
  const view = graphView(
    response([{ nodes: [a, b], edges: [{ relation_type: "SUPPLIES" }] }]),
  )!;
  expect(view.nodes).toEqual([a, b]);
  expect(view.edges).toEqual([
    { source: "Equipment:a", target: "Product:b", label: "SUPPLIES" },
  ]);
  expect(view.data.complete).toBe(false);
});
it("marks an invalid path as limited instead of inventing an edge", () => {
  const view = graphView(response([{ nodes: [a, b], edges: [] }]))!;
  expect(view.limited).toBe(true);
  expect(view.edges).toEqual([]);
});
it("does not infer a graph from an unrelated result", () => {
  const r = response([]);
  r.data = { items: [a] };
  expect(graphView(r)).toBeNull();
});

it("never renders a non-CURRENT graph as a current analysis", () => {
  const r = response([
    { nodes: [a, b], edges: [{ relation_type: "SUPPLIES" }] },
  ]);
  const rows = r.data.tool_results as { data: Record<string, unknown> }[];
  rows[0].data.graph_sync_state = "LAGGING";
  expect(graphView(r)).toBeNull();
});

it("selects upstream paths without converting them into downstream impact", () => {
  const r = response([]);
  const upstream = {
    target: b,
    representative_paths: [
      { nodes: [b, a], edges: [{ relation_type: "PRODUCES" }] },
    ],
    graph_sync_state: "CURRENT",
    complete: true,
    analysis_mode: "UPSTREAM",
  };
  r.data.decision_package = { upstream_dependencies: upstream };
  const view = graphView(r, "upstream_dependencies")!;
  expect(view.edges).toEqual([
    { source: "Product:b", target: "Equipment:a", label: "PRODUCES" },
  ]);
  expect(view.data.analysis_mode).toBe("UPSTREAM");
});
it("keeps a confirmed isolated root without inventing neighbours", () => {
  const r = response([]);
  const rows = r.data.tool_results as { data: Record<string, unknown> }[];
  rows[0].data.target = a;
  const view = graphView(r)!;
  expect(view.nodes).toEqual([a]);
  expect(view.edges).toEqual([]);
});
it("does not fall back to another current analysis when the chosen one is stale", () => {
  const r = response([]);
  r.data.decision_package = {
    upstream_dependencies: {
      representative_paths: [],
      graph_sync_state: "LAGGING",
    },
  };
  expect(graphView(r, "upstream_dependencies")).toBeNull();
});
it("highlights the actual path edges without cross-highlighting another relationship", () => {
  const r = response([
    { nodes: [a, b], edges: [{ relation_type: "PRODUCES" }] },
    {
      nodes: [a, { entity_type: "Process", entity_id: "c" }],
      edges: [{ relation_type: "SUPPLIES" }],
    },
  ]);
  const highlighted = pathHighlights(graphView(r)!, "Product:b");
  expect([...highlighted]).toEqual(["Equipment:a>Product:b:PRODUCES"]);
  expect(highlighted.has("Equipment:a>Product:b:SUPPLIES")).toBe(false);
});

it("keeps explicit structural subjects visible when no representative path exists", () => {
  const r = response([]);
  const rows = r.data.tool_results as {
    tool: string;
    data: Record<string, unknown>;
  }[];
  rows[0].tool = "find_alternative_paths";
  rows[0].data.important_targets = [b];
  rows[0].data.excluded_nodes = [a];
  expect(graphView(r)?.nodes).toEqual([b, a]);
  expect(graphView(r)?.edges).toEqual([]);
});
