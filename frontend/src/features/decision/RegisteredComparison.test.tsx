import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RegisteredComparison } from "./RegisteredComparison";
import type { Envelope } from "../../api/client";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const base: Envelope = {
  request_id: "r",
  context_id: null,
  status: "ok",
  answer: null,
  data: {},
  evidence: {},
  errors: [],
  warnings: [],
};
it("keeps selection while candidate reads and comparison run through distinct pending and failure states", async () => {
  let finish: (r: Response) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  const input: Envelope = {
    ...base,
    data: {
      input: {
        economic_input_id: "e",
        equipment_id: "m",
        version: 1,
        payload: {
          period_start: "2026-10-18T00:00:00Z",
          period_end: "2026-10-19T00:00:00Z",
        },
      },
    },
  };
  const view = render(
    <RegisteredComparison
      equipment={{
        equipment_id: "m",
        equipment_name: "設備",
        equipment_code: "M",
      }}
      names={{}}
      initialEconomic={[input]}
      initialCapacity={[]}
      initialEconomicId="e"
      initialCapacityId=""
      candidateIds={[]}
      productIds={[]}
      executionEpoch={0}
      onInvestigate={() => {}}
    />,
  );
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: "別の算定データを検索" }),
  );
  expect(screen.getByText(/入力候補の取得を実行しています/)).toBeDefined();
  await act(async () =>
    finish(
      new Response(
        JSON.stringify({ ...base, data: { items: [], next_cursor: null } }),
      ),
    ),
  );
  const selected = screen.getAllByRole("checkbox")[0] as HTMLInputElement;
  expect(selected.checked).toBe(true);
  await user.click(
    screen.getByRole("button", { name: "選択した正式入力で比較する" }),
  );
  expect(screen.getByText("対応案の比較を実行しています…")).toBeDefined();
  await act(async () =>
    finish(
      new Response(
        JSON.stringify({
          ...base,
          status: "error",
          errors: [{ code: "DEPENDENCY_UNAVAILABLE" }],
        }),
        { status: 503 },
      ),
    ),
  );
  expect(screen.getByRole("alert").textContent).toContain(
    "対応案の比較を完了できませんでした",
  );
  expect(selected.checked).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "選択した正式入力で比較する",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
  view.rerender(
    <RegisteredComparison
      equipment={{
        equipment_id: "m",
        equipment_name: "設備",
        equipment_code: "M",
      }}
      names={{}}
      initialEconomic={[input]}
      initialCapacity={[]}
      initialEconomicId="e"
      initialCapacityId=""
      candidateIds={[]}
      productIds={[]}
      executionEpoch={1}
      onInvestigate={() => {}}
    />,
  );
  expect(screen.getByText(/選択した入力が更新前/)).toBeDefined();
  expect(
    (
      screen.getByRole("button", {
        name: "選択した正式入力で比較する",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  await user.click(
    screen.getByRole("button", { name: "入力・出典を確認：第1版" }),
  );
  await act(async () =>
    finish(
      new Response(
        JSON.stringify({
          ...input,
          data: { input: { ...(input.data.input as object), version: 2 } },
        }),
      ),
    ),
  );
  expect(screen.queryByText(/選択した入力が更新前/)).toBeNull();
  expect(
    (
      screen.getByRole("button", {
        name: "選択した正式入力で比較する",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
});
