import { expect, it } from "vitest";
import { money } from "./model";

it("formats decimal server amounts without losing digits to binary float", () => {
  expect(money("999999999999999.123456")).toBe(
    "999,999,999,999,999.123456 円／時間",
  );
});
it("keeps an unknown estimate distinct from a registered zero", () => {
  expect(money(null)).toBe("未算出");
  expect(money("0")).toBe("0 円／時間");
});
