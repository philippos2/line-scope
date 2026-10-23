import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { Envelope } from "../api/client";
import { RegisteredAnswer } from "./RegisteredAnswer";

afterEach(cleanup);

function response(facts: unknown[], tools: unknown[] = []): Envelope {
  return {
    request_id: "test-request",
    context_id: null,
    status: "partial",
    answer: null,
    evidence: {},
    errors: [],
    warnings: [],
    data: {
      answer_sections: {
        version: 1,
        facts,
        definitions: [],
        scope: ["質問の読み取りを確定できませんでした。"],
        unavailable: [{ text: "尋ねられた情報は確認できません。" }],
      },
      tool_results: tools,
    },
  };
}

it("does not present an unsuccessful interpretation as acquired registered information", () => {
  render(<RegisteredAnswer response={response([])} />);
  expect(screen.getByText("尋ねられた情報は確認できません。")).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "確認できたこと" })).toBeNull();
  expect(
    screen.queryByText(/登録情報から確認できた内容を表示しています/),
  ).toBeNull();
  // Diagnostic interpretation remains accessible, without pretending to be evidence.
  expect(screen.getByText(/質問の読み取りを確定できませんでした/)).toBeTruthy();
});

it("keeps verified equipment identity beside the unanswered question without replacing it", () => {
  render(
    <RegisteredAnswer
      response={response(
        [
          {
            id: "f1",
            predicate: "equipment.identity",
            text: "試験設備（E-7）のことですね。",
            references: ["lookup"],
          },
        ],
        [{ tool_call_id: "lookup", tool: "search_equipment", data: {} }],
      )}
    />,
  );
  expect(screen.getByText("試験設備（E-7）のことですね。")).toBeTruthy();
  expect(screen.getByText("尋ねられた情報は確認できません。")).toBeTruthy();
  expect(screen.queryByText(/未登録です|在庫はありません/)).toBeNull();
});
