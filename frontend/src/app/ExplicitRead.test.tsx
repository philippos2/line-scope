import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  ApiError,
  object,
  request,
  type Envelope,
  type JsonObject,
} from "../api/client";
import { ExplicitRead } from "./ExplicitRead";
vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  request: vi.fn(),
}));
const first = {
  equipment_id: "00000000-0000-0000-0000-000000000021",
  equipment_name: "検証装置",
  equipment_code: "V-21",
};
const other = {
  equipment_id: "00000000-0000-0000-0000-000000000022",
  equipment_name: "対照装置",
  equipment_code: "V-22",
};
const envelope = (
  data: JsonObject = {},
  answer: string | null = null,
): Envelope => ({
  request_id: "r",
  context_id: null,
  status: "ok",
  answer,
  data,
  evidence: {},
  errors: [],
  warnings: [],
});
const catalog = envelope({
  read_catalog: {
    version: "h7-1",
    entries: [
      {
        key: "registered_state",
        label: "登録状態",
        description: "登録上の運用状態です",
        min_targets: 1,
        max_targets: 4,
        action: "EXECUTE",
      },
    ],
  },
});
function result(body: JsonObject) {
  const selected = body.read_selection as JsonObject;
  return envelope({
    read_selection: {
      ...selected,
      label: "登録状態",
      original_question: body.message,
      target_labels: ["照会した装置"],
      observed_at: "2026-10-24T00:00:00Z",
    },
    answer_sections: {
      version: 1,
      facts: [{ id: "f1", text: "登録上は停止中", references: ["o1"] }],
      unavailable: [],
      scope: [],
    },
    tool_results: [
      {
        tool_call_id: "o1",
        tool: "get_equipment_state",
        data: { state_code: "STOPPED" },
      },
    ],
  });
}
function stub(
  execute: (body: JsonObject) => Promise<Envelope> = async (body) =>
    result(body),
) {
  vi.mocked(request).mockImplementation(async (_token, _path, body) => {
    if (
      object(body?.read_selection) &&
      body.read_selection.operation === "CATALOG"
    )
      return catalog;
    if (
      typeof body?.message === "string" &&
      body.message.startsWith("関係分析 ")
    )
      return envelope({
        tool_results: [
          {
            tool: "search_equipment",
            data: { items: [other], next_cursor: null },
          },
        ],
      });
    return execute(body!);
  });
}
const props = {
  question: "補助の原文",
  equipment: first,
  connected: true,
  onNavigate: vi.fn(),
};
async function ready() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "照会項目を取得" }));
  await user.selectOptions(
    screen.getByLabelText("調べる項目"),
    "registered_state",
  );
  await user.click(screen.getByRole("button", { name: /画面の設備/ }));
  return user;
}
function executes() {
  return vi
    .mocked(request)
    .mock.calls.filter(
      (call) =>
        object(call[2]?.read_selection) &&
        call[2].read_selection.operation === "EXECUTE",
    );
}
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("only executes the confirmed target and field after explicit action", async () => {
  stub();
  render(<ExplicitRead {...props} />);
  const user = await ready();
  expect(executes()).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "この項目を調べる" }));
  await screen.findByText("登録上は停止中");
  expect(executes()[0][2]).toEqual({
    message: props.question,
    read_selection: {
      operation: "EXECUTE",
      catalog_version: "h7-1",
      key: "registered_state",
      targets: [{ entity_type: "Equipment", entity_id: first.equipment_id }],
    },
  });
});
it("explains why an unselected viewpoint or target cannot execute", async () => {
  stub();
  render(<ExplicitRead {...props} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "照会項目を取得" }));
  expect(
    (
      screen.getByRole("button", {
        name: "この項目を調べる",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  await user.selectOptions(
    screen.getByLabelText("調べる項目"),
    "registered_state",
  );
  expect(screen.getByText(/対象を1〜4件/)).toBeDefined();
  expect(executes()).toHaveLength(0);
});
it("always offers no matching viewpoint without redirecting to another read", async () => {
  stub();
  render(<ExplicitRead {...props} />);
  const user = userEvent.setup();
  await user.selectOptions(screen.getByLabelText("調べる項目"), "__none__");
  expect(screen.getByText(/参照は行いません/)).toBeDefined();
  expect(screen.getByText(`元の質問：${props.question}`)).toBeDefined();
  expect(vi.mocked(request)).not.toHaveBeenCalled();
});
it("keeps the original supplement and explicitly chosen other equipment separate", async () => {
  stub();
  render(<ExplicitRead {...props} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "照会項目を取得" }));
  await user.selectOptions(
    screen.getByLabelText("調べる項目"),
    "registered_state",
  );
  await user.click(
    screen.getByRole("button", { name: "照会対象の候補を検索" }),
  );
  await user.click(
    await screen.findByRole("button", { name: /対照装置 · V-22を追加/ }),
  );
  await user.click(screen.getByRole("button", { name: "この項目を調べる" }));
  await screen.findByText("登録上は停止中");
  expect(executes()[0][2]?.read_selection).toMatchObject({
    targets: [{ entity_type: "Equipment", entity_id: other.equipment_id }],
  });
  expect(screen.getAllByText(`元の質問：${props.question}`)).toHaveLength(2);
});
it("does not restore a late result after editing the supplement", async () => {
  let finish: (value: Envelope) => void = () => {};
  let sent: JsonObject = {};
  stub((body) => {
    sent = body;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  const view = render(<ExplicitRead {...props} />);
  const user = await ready();
  await user.click(screen.getByRole("button", { name: "この項目を調べる" }));
  view.rerender(<ExplicitRead {...props} question="別の補助入力" />);
  await act(async () => finish(result(sent)));
  expect(screen.queryByText("登録上は停止中")).toBeNull();
});
it("discards pending results on connection change", async () => {
  let finish: (value: Envelope) => void = () => {};
  let sent: JsonObject = {};
  stub((body) => {
    sent = body;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  const view = render(<ExplicitRead {...props} />);
  const user = await ready();
  await user.click(screen.getByRole("button", { name: "この項目を調べる" }));
  view.rerender(<ExplicitRead {...props} connected={false} />);
  await act(async () => finish(result(sent)));
  expect(screen.queryByText("登録上は停止中")).toBeNull();
  expect(screen.getByText("接続が必要です。")).toBeDefined();
});
it("retains the previous result on failure and refreshes stale state explicitly", async () => {
  let fail = false;
  stub(async (body) => {
    if (fail) throw new ApiError("CONNECTION_FAILED");
    return result(body);
  });
  const view = render(<ExplicitRead {...props} />);
  const user = await ready();
  await user.click(screen.getByRole("button", { name: "この項目を調べる" }));
  await screen.findByText("登録上は停止中");
  view.rerender(<ExplicitRead {...props} executionEpoch={1} />);
  expect(screen.getByText(/更新前の結果/)).toBeDefined();
  fail = true;
  await user.click(screen.getByRole("button", { name: "この項目を調べる" }));
  await screen.findByRole("alert");
  expect(screen.getByText("登録上は停止中")).toBeDefined();
  fail = false;
  await user.click(
    screen.getByRole("button", { name: "選択した登録情報を取得を再試行" }),
  );
  await waitFor(() => expect(screen.queryByText(/更新前の結果/)).toBeNull());
});
it("never accepts or publishes a legacy interpretation response", async () => {
  stub(async () =>
    envelope(
      { read_clarification: { kind: "READ_SCOPE", status: "PENDING" } },
      "UNRELATED_VALUE",
    ),
  );
  render(<ExplicitRead {...props} />);
  const user = await ready();
  await user.click(screen.getByRole("button", { name: "この項目を調べる" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("UNRELATED_VALUE")).toBeNull();
  expect(screen.queryByRole("button", { name: "この範囲を調べる" })).toBeNull();
});

function proposal(
  status = "PROPOSED",
  question = props.question,
  version = "h7-1",
) {
  return envelope({
    read_suggestions: {
      status,
      question,
      catalog_version: version,
      candidates: status === "PROPOSED" ? [{ key: "registered_state" }] : [],
      subject_references: [
        { entity_type: "Equipment", reference: "AIの対象表現" },
      ],
    },
  });
}
it("keeps the manual catalog and none option when suggestions are unavailable", async () => {
  stub();
  render(
    <ExplicitRead
      {...props}
      availableCatalog={catalog}
      suggestions={proposal("UNAVAILABLE")}
    />,
  );
  await screen.findByText(
    "AIの候補を利用できません。全項目から手動で選べます。",
  );
  expect(
    screen.getByRole("option", { name: "該当する観点がない" }),
  ).toBeTruthy();
  const user = await ready();
  await user.click(screen.getByRole("button", { name: "この項目を調べる" }));
  expect(executes()).toHaveLength(1);
});
it("a suggestion selects a field without reading or accepting a model target", async () => {
  stub();
  render(
    <ExplicitRead
      {...props}
      availableCatalog={catalog}
      suggestions={proposal()}
    />,
  );
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", { name: "候補「登録状態」を選ぶ" }),
  );
  expect(executes()).toHaveLength(0);
  expect((screen.getByLabelText("調べる項目") as HTMLSelectElement).value).toBe(
    "registered_state",
  );
  expect(
    (
      screen.getByRole("button", {
        name: "この項目を調べる",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  await user.click(screen.getByRole("button", { name: /画面の設備/ }));
  await user.click(screen.getByRole("button", { name: "この項目を調べる" }));
  expect(executes()[0][2]?.read_selection).toEqual({
    operation: "EXECUTE",
    catalog_version: "h7-1",
    key: "registered_state",
    targets: [{ entity_type: "Equipment", entity_id: first.equipment_id }],
  });
});
it("does not expose proposals for another question or catalog version", async () => {
  stub();
  const view = render(
    <ExplicitRead
      {...props}
      availableCatalog={catalog}
      suggestions={proposal("PROPOSED", "別の原文")}
    />,
  );
  await screen.findByRole("option", { name: "登録状態" });
  expect(screen.queryByRole("region", { name: "未確定のAI提案" })).toBeNull();
  view.rerender(
    <ExplicitRead
      {...props}
      availableCatalog={catalog}
      suggestions={proposal("PROPOSED", props.question, "retired")}
    />,
  );
  expect(screen.queryByRole("region", { name: "未確定のAI提案" })).toBeNull();
});
