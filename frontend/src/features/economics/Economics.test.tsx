import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, request, type Envelope } from "../../api/client";
import { EconomicEditor } from "./EconomicEditor";
import { EconomicPanel } from "./EconomicPanel";
import { EconomicResult } from "./EconomicResult";
import { blankInput, readInput, type EconomicInput } from "./model";
vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/client")>()),
  request: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  Reflect.deleteProperty(navigator, "clipboard");
});
function response(data: Record<string, unknown>): Envelope {
  return {
    request_id: "req",
    context_id: null,
    status: "ok",
    answer: null,
    data,
    evidence: {},
    warnings: [],
    errors: [],
  };
}
function initial(): EconomicInput {
  const value = blankInput("20400000-0000-4000-8000-000000000001");
  value.input_code = "COST";
  value.payload = {
    ...value.payload,
    period_start: "2026-10-01T00:00:00Z",
    period_end: "2026-10-02T00:00:00Z",
    operating_hours: "16",
    options: value.payload.options.map((option) => ({
      ...option,
      items: option.items.map((item) => ({
        ...item,
        key: "cost",
        source: "source",
      })),
    })),
  };
  return value;
}
test("unknown totals and exact zero remain distinct and sources stay text", () => {
  render(
    <EconomicResult
      data={{
        source: "REGISTERED_INPUT",
        input: { input_code: "COST", version: 1 },
        calculation: {
          options: [
            {
              option: "REPAIR",
              total_jpy: null,
              known_subtotal_jpy: "0",
              complete: false,
              items: [
                {
                  key: "fee",
                  kind: "DIRECT",
                  amount_jpy: "0",
                  included_in_subtotal: true,
                  source: "<img onerror=alert(1)>",
                  certainty: "ESTIMATED",
                },
              ],
            },
          ],
        },
      }}
    />,
  );
  expect(screen.getByText("不明")).toBeTruthy();
  expect(screen.getByText("既知小計：0 JPY")).toBeTruthy();
  expect(document.querySelector("img")).toBeNull();
});
test("prepare is explicit and retry identity is retained until input changes", async () => {
  const onPrepared = vi.fn();
  vi.mocked(request)
    .mockRejectedValueOnce(new ApiError("CONNECTION_FAILED"))
    .mockResolvedValue(response({ update_request_id: "saved" }));
  render(
    <EconomicEditor
      initial={initial()}
      onPrepared={onPrepared}
      signal={new AbortController().signal}
    />,
  );
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "経済入力の変更準備を作成" }),
  );
  await screen.findByRole("alert");
  fireEvent.click(
    screen.getByRole("button", { name: "経済入力の変更準備を作成" }),
  );
  await waitFor(() => expect(onPrepared).toHaveBeenCalledWith("saved"));
  const calls = vi.mocked(request).mock.calls;
  expect(calls[0][2]?.retry_key).toBe(calls[1][2]?.retry_key);
  fireEvent.change(screen.getByLabelText("稼働時間"), {
    target: { value: "18" },
  });
  // Editing a fact invalidates the copied provenance; the user must state it again.
  for (const source of screen.getAllByLabelText("出典", { exact: true })) {
    expect((source as HTMLInputElement).value).toBe("");
    fireEvent.change(source, { target: { value: "変更内容の出典" } });
  }
  fireEvent.click(
    screen.getByRole("button", { name: "経済入力の変更準備を作成" }),
  );
  await waitFor(() => expect(request).toHaveBeenCalledTimes(3));
  expect(calls[0][2]?.retry_key).not.toBe(
    vi.mocked(request).mock.calls[2][2]?.retry_key,
  );
  expect(
    vi
      .mocked(request)
      .mock.calls.every((call) => call[1] === "/economic-inputs/prepare"),
  ).toBe(true);
});
test("an aborted prepare cannot repopulate the disconnected session", async () => {
  let finish!: (value: Envelope) => void;
  vi.mocked(request).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const controller = new AbortController(),
    onPrepared = vi.fn();
  const view = render(
    <EconomicEditor
      initial={initial()}
      onPrepared={onPrepared}
      signal={controller.signal}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "経済入力の変更準備を作成" }),
  );
  controller.abort();
  view.unmount();
  await act(async () => finish(response({ update_request_id: "late" })));
  expect(onPrepared).not.toHaveBeenCalled();
});
test("opening a fresh editor discards unsaved values without submitting", () => {
  const equipment = {
    equipment_id: "eq",
    equipment_code: "E1",
    equipment_name: "Machine",
  };
  render(
    <EconomicPanel
      equipment={equipment}
      onPrepared={vi.fn()}
      onInvestigate={vi.fn()}
      executionEpoch={0}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "選択設備の経済入力を登録" }),
  );
  fireEvent.change(screen.getByLabelText("入力コード"), {
    target: { value: "unsaved" },
  });
  fireEvent.click(screen.getByRole("button", { name: "編集を閉じる" }));
  fireEvent.click(
    screen.getByRole("button", { name: "選択設備の経済入力を登録" }),
  );
  expect((screen.getByLabelText("入力コード") as HTMLInputElement).value).toBe(
    "",
  );
  expect(request).not.toHaveBeenCalled();
});

test("a malformed registered payload is rejected before opening an editor", () => {
  expect(() =>
    readInput({
      economic_input_id: "id",
      input_code: "A",
      equipment_id: "eq",
      version: 1,
      payload: { options: [null] },
    }),
  ).toThrow("INVALID_RESPONSE");
});

test("a prepared input remains visible, exposes its saved contents and copyable ID, and blocks a duplicate prepare", async () => {
  const input = initial();
  const copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: copy },
  });
  const opened = vi.fn();
  vi.mocked(request).mockResolvedValue(
    response({
      update_request_id: "saved-request",
      canonical_snapshot: {
        targets: [
          { target_type: "EconomicInput", after: { ...input, version: 1 } },
        ],
      },
    }),
  );
  render(
    <EconomicEditor
      initial={input}
      onPrepared={vi.fn()}
      onOpenPrepared={opened}
      signal={new AbortController().signal}
    />,
  );
  const button = screen.getByRole("button", {
    name: "経済入力の変更準備を作成",
  });
  fireEvent.click(button);
  await screen.findByRole("heading", { name: "変更準備が完了しました" });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(true),
  );
  expect(button.textContent).toBe("変更準備を作成済み");
  expect(button.getAttribute("aria-busy")).toBe("false");
  fireEvent.submit(button.closest("form")!);
  expect(request).toHaveBeenCalledTimes(1);
  expect(opened).not.toHaveBeenCalled();
  expect(screen.getByText(/次は別の工場管理者による承認/)).toBeTruthy();
  expect(screen.getByText("saved-request")).toBeTruthy();
  expect(screen.getByRole("region", { name: "選択入力の内容" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "変更要求IDをコピー" }));
  await waitFor(() => expect(copy).toHaveBeenCalledWith("saved-request"));
  fireEvent.click(
    screen.getByRole("button", { name: "保存した変更要求を開く" }),
  );
  expect(opened).toHaveBeenCalledWith("saved-request");
  fireEvent.change(screen.getByLabelText("稼働時間"), {
    target: { value: "18" },
  });
  expect((button as HTMLButtonElement).disabled).toBe(false);
  expect(screen.getByText("作成後に編集した内容は未保存です。")).toBeTruthy();
});
