import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import * as client from "../../api/client";
import { DateTimeInput } from "./DateTimeInput";
import {
  InputAssistance,
  SuggestedInput,
  SuggestionScope,
} from "./InputAssistance";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("retains the original sub-millisecond timestamp until the displayed instant is actually edited", () => {
  const change = vi.fn();
  render(
    <label>
      日時
      <DateTimeInput value="2026-10-18T00:00:00.123456Z" onChange={change} />
    </label>,
  );
  const input = screen.getByLabelText(/日時/);
  expect((input as HTMLInputElement).value).toBe("2026-10-18T09:00:00.123");
  fireEvent.change(input, { target: { value: "2026-10-18T09:00:00.123" } });
  expect(change).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "2026-10-18T10:30" } });
  expect(change).toHaveBeenCalledWith("2026-10-18T10:30+09:00");
});
it("offers scoped registered values without replacing a typed value or borrowing a different product", async () => {
  const period = {
    period_start: "2026-10-18T00:00:00Z",
    period_end: "2026-10-19T00:00:00Z",
    quantity_unit: "個",
  };
  const response = (data: client.JsonObject): client.Envelope => ({
    request_id: "read",
    context_id: null,
    status: "ok",
    answer: null,
    data,
    evidence: {},
    warnings: [],
    errors: [],
  });
  vi.spyOn(client, "request").mockImplementation(async (_token, path) =>
    path.endsWith("/search")
      ? response({
          items: [{ capacity_input_id: "a" }, { capacity_input_id: "b" }],
          next_cursor: null,
        })
      : response({
          input: {
            capacity_input_id: path.endsWith("/a") ? "a" : "b",
            equipment_id: "equipment",
            equipment_name: "加工機",
            input_code: "registered",
            version: 1,
            product_id: path.endsWith("/a") ? "product-a" : "product-b",
            payload: {
              ...period,
              required_rate: path.endsWith("/a") ? "0" : "90",
              source: "登録資料",
            },
          },
        }),
  );
  const changed = vi.fn();
  render(
    <InputAssistance
      kind="capacity"
      equipment={{
        equipment_id: "equipment",
        equipment_code: "machine",
        equipment_name: "加工機",
      }}
    >
      <SuggestionScope
        value={{
          equipment_id: "equipment",
          product_id: "product-a",
          payload: period,
        }}
      >
        <label>
          能力
          <SuggestedInput
            field="payload.required_rate"
            inputMode="decimal"
            value="77"
            onChange={changed}
          />
        </label>
      </SuggestionScope>
    </InputAssistance>,
  );
  fireEvent.click(screen.getByRole("button", { name: "入力候補を取得・更新" }));
  await waitFor(() =>
    expect(document.querySelectorAll("datalist option")).toHaveLength(1),
  );
  expect(document.querySelector("datalist option")?.getAttribute("value")).toBe(
    "0",
  );
  expect(
    document.querySelector("datalist option")?.getAttribute("label"),
  ).toContain("登録資料");
  expect((screen.getByLabelText("能力") as HTMLInputElement).value).toBe("77");
  expect(changed).not.toHaveBeenCalled();
});
