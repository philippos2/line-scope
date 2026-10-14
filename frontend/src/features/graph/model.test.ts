import { expect, it } from "vitest";
import { envelope } from "../../api/client";
import { graphView } from "./model";
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
