import { useEffect, useRef, useState } from "react";
import {
  object,
  request,
  type Envelope,
  type JsonObject,
} from "../../api/client";
import type { EquipmentCandidate } from "../equipment/EquipmentCandidates";
import { type NodeRef } from "../graph/model";
import {
  candidates,
  direct,
  errorCode,
  generation,
  inputs,
  products,
  rows,
  toolData,
  type ReadState,
} from "./readModel";

type Channel = "down" | "up" | "alternatives" | "loss" | "comparison" | "extra";
export function useEquipmentInvestigation(
  root: EquipmentCandidate | null,
  executionEpoch: number,
) {
  const [refresh, setRefresh] = useState(0);
  const [states, setStates] = useState<Partial<Record<Channel, ReadState>>>({});
  const [metadata, setMetadata] = useState<unknown[]>([]);
  const [economic, setEconomic] = useState<Envelope[]>([]),
    [capacity, setCapacity] = useState<Envelope[]>([]);
  const [economicId, setEconomicId] = useState(""),
    [capacityId, setCapacityId] = useState("");
  const [inputErrors, setInputErrors] = useState<Record<string, string>>({});
  const [inputLoading, setInputLoading] = useState<Record<string, boolean>>({});
  const [candidateEquipment, setCandidateEquipment] = useState<
    EquipmentCandidate[]
  >([]);
  const [observedEpoch, setObservedEpoch] = useState(executionEpoch);
  const [selected, setSelected] = useState<NodeRef | null>(null),
    [attributeError, setAttributeError] = useState("");
  const active = useRef<AbortController | null>(null),
    attribute = useRef<AbortController | null>(null);
  const epoch = useRef(executionEpoch);
  epoch.current = executionEpoch;
  const [choiceGeneration, setChoiceGeneration] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    active.current = controller;
    attribute.current?.abort();
    const signal = controller.signal;
    setStates({});
    setMetadata(root ? [{ tool: "get_equipment", data: root }] : []);
    setEconomic([]);
    setCapacity([]);
    setEconomicId("");
    setCapacityId("");
    setCandidateEquipment([]);
    setInputErrors({});
    setInputLoading({});
    setSelected(null);
    setAttributeError("");
    setObservedEpoch(epoch.current);
    if (!root) return () => controller.abort();
    function update(channel: Channel, state: ReadState) {
      if (!signal.aborted) setStates((old) => ({ ...old, [channel]: state }));
    }
    async function labels(subjects: NodeRef[]) {
      // Only names required by the monetary/proposal cards; full node inspection is lazy.
      for (const item of subjects) {
        try {
          const response = await direct(
            item.entity_type === "Product" ? "get_product" : "get_equipment",
            {
              [item.entity_type === "Product" ? "product_id" : "equipment_id"]:
                item.entity_id,
            },
            signal,
          );
          if (!signal.aborted)
            setMetadata((old) => [...old, ...rows(response.data.tool_results)]);
          if (item.entity_type === "Equipment") {
            const d = toolData(response);
            if (
              typeof d.equipment_id === "string" &&
              typeof d.equipment_code === "string" &&
              typeof d.equipment_name === "string" &&
              !signal.aborted
            )
              setCandidateEquipment((old) => [
                ...old.filter((x) => x.equipment_id !== item.entity_id),
                d as unknown as EquipmentCandidate,
              ]);
          }
        } catch {
          /* Names are optional; the independently retrieved analysis remains visible. */
        }
      }
    }
    async function loadInputs(kind: "economic" | "capacity", ids: string[]) {
      setInputLoading((old) => ({ ...old, [kind]: true }));
      try {
        const replies = (
          await Promise.all(ids.map((id) => inputs(kind, id, signal)))
        ).flat();
        if (signal.aborted) return;
        if (kind === "economic") {
          setEconomic(replies);
          setEconomicId(
            replies.length === 1
              ? String((replies[0].data.input as JsonObject).economic_input_id)
              : "",
          );
        } else {
          setCapacity(replies);
          setCapacityId(
            replies.length === 1
              ? String((replies[0].data.input as JsonObject).capacity_input_id)
              : "",
          );
        }
      } catch (e) {
        if (!signal.aborted)
          setInputErrors((old) => ({ ...old, [kind]: errorCode(e) }));
      } finally {
        if (!signal.aborted)
          setInputLoading((old) => ({ ...old, [kind]: false }));
      }
    }
    const target = { entity_type: "Equipment", entity_id: root.equipment_id };
    update("down", { loading: true });
    update("up", { loading: true });
    void direct("trace_upstream_dependencies", { target }, signal)
      .then((value) => update("up", { value }))
      .catch((e) => update("up", { error: errorCode(e) }));
    void loadInputs("economic", [root.equipment_id]);
    void direct("trace_downstream_impact", { target }, signal)
      .then(async (value) => {
        if (signal.aborted) return;
        update("down", { value });
        const targets = products(value);
        void labels(targets);
        if (!targets.length) return;
        update("alternatives", { loading: true });
        try {
          const result = await direct(
            "find_alternative_paths",
            { important_targets: targets, excluded_nodes: [target] },
            signal,
          );
          if (generation(value) !== generation(result))
            throw new Error("Graph generation mismatch");
          update("alternatives", { value: result });
          const found = candidates(result).filter(
            (x) => x.entity_type === "Equipment",
          );
          void labels(found);
          if (found.length)
            void loadInputs(
              "capacity",
              found.map((x) => x.entity_id),
            );
        } catch (e) {
          update("alternatives", {
            error:
              e instanceof Error && e.message === "Graph generation mismatch"
                ? "GRAPH_NOT_CURRENT"
                : errorCode(e),
          });
        }
      })
      .catch((e) => update("down", { error: errorCode(e) }));
    return () => {
      controller.abort();
      attribute.current?.abort();
    };
  }, [root, refresh]);
  useEffect(() => {
    const controller = new AbortController(),
      signal = controller.signal;
    function update(channel: Channel, state: ReadState) {
      if (!signal.aborted) setStates((old) => ({ ...old, [channel]: state }));
    }
    const econ = economic.find(
      (x) =>
        object(x.data.input) && x.data.input.economic_input_id === economicId,
    );
    const cap = capacity.find(
      (x) =>
        object(x.data.input) && x.data.input.capacity_input_id === capacityId,
    );
    const econRecord = econ?.data.input,
      capRecord = cap?.data.input;
    const payload =
      object(econRecord) && object(econRecord.payload)
        ? econRecord.payload
        : null;
    if (!root) {
      setStates((old) => ({ ...old, loss: {}, comparison: {} }));
      return () => controller.abort();
    }
    const ownPayload =
      object(econRecord) && econRecord.equipment_id === root.equipment_id
        ? payload
        : null;
    const capPayload =
      object(capRecord) && object(capRecord.payload) ? capRecord.payload : null;
    const period = ownPayload ?? capPayload;
    if (ownPayload) {
      update("loss", { loading: true });
      void request(
        "",
        "/incidents/investigate",
        {
          equipment_ids: [root.equipment_id],
          economic_input_ids: [economicId],
          period_start: ownPayload.period_start,
          period_end: ownPayload.period_end,
        },
        signal,
      )
        .then((value) => update("loss", { value }))
        .catch((e) => update("loss", { error: errorCode(e) }));
    } else update("loss", {});
    if (period && capPayload) {
      if (
        capPayload.period_start !== period.period_start ||
        capPayload.period_end !== period.period_end
      )
        update("comparison", { error: "PERIOD_MISMATCH" });
      else {
        update("comparison", { loading: true });
        void request(
          "",
          "/decisions/compare",
          {
            equipment_id: root.equipment_id,
            economic_input_id: ownPayload ? economicId : null,
            capacity_input_ids: [capacityId],
            safety_input_ids: [],
            maintenance_input_ids: [],
            period_start: period.period_start,
            period_end: period.period_end,
          },
          signal,
        )
          .then((value) => update("comparison", { value }))
          .catch((e) => update("comparison", { error: errorCode(e) }));
      }
    } else update("comparison", {});
    return () => controller.abort();
  }, [root, economic, capacity, economicId, capacityId, choiceGeneration]);
  function select(item: NodeRef) {
    setSelected(item);
    setAttributeError("");
    attribute.current?.abort();
    const controller = new AbortController();
    attribute.current = controller;
    const field = (
      {
        Equipment: "equipment",
        Process: "process",
        ProductionOperation: "production_operation",
        Product: "product",
        InfrastructureResource: "infrastructure_resource",
      } as Record<string, string>
    )[item.entity_type];
    if (!field) return;
    void direct(
      `get_${field}`,
      { [`${field}_id`]: item.entity_id },
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted)
          setMetadata((old) => [...old, ...rows(value.data.tool_results)]);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setAttributeError(errorCode(e));
      });
  }
  function analyze(tool: string, args: JsonObject) {
    const controller = active.current;
    if (!controller || controller.signal.aborted) return;
    setStates((old) => ({ ...old, extra: { loading: true } }));
    void direct(tool, args, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted)
          setStates((old) => ({
            ...old,
            extra:
              generation(value) === generation(old.down?.value)
                ? { value }
                : { error: "GRAPH_NOT_CURRENT" },
          }));
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setStates((old) => ({ ...old, extra: { error: errorCode(e) } }));
      });
  }
  const currentState =
    rows(
      rows(states.down?.value?.evidence.tool_results)[0]?.current_states,
    ).find((x) => x.equipment_id === root?.equipment_id)?.state_code ??
    rows(states.loss?.value?.data.impacts).find(
      (x) => x.equipment_id === root?.equipment_id,
    )?.state_code;
  return {
    states,
    analyze,
    metadata,
    economic,
    capacity,
    economicId,
    capacityId,
    setEconomicId,
    setCapacityId,
    candidateEquipment,
    inputErrors,
    inputLoading,
    currentState,
    selected,
    select,
    attributeError,
    stale: observedEpoch !== executionEpoch,
    retry: () => setRefresh((x) => x + 1),
    retryCalculation: () => setChoiceGeneration((x) => x + 1),
  };
}
