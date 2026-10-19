import { expect, it } from "vitest";
import { comparisonPeriod } from "./workspaceModel";
const start = "2026-10-18T00:00:00.123456Z",
  end = "2026-10-19T00:00:00.123456Z";
const input = (a = start, b = end, kind = "REPAIR_PLAN") => ({
  payload: { period_start: a, period_end: b, kind },
});
it("preserves exact registered instants and keeps past records out of period derivation", () => {
  expect(
    comparisonPeriod({
      economic: [input()],
      capacity: [input()],
      safety: [input("2026-10-17T00:00:00Z", "2026-10-20T00:00:00Z")],
      maintenance: [
        input("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z", "FAILURE_RECORD"),
      ],
    }),
  ).toEqual({ period: { start, end }, error: "" });
  expect(
    comparisonPeriod({ maintenance: [input(start, end, "REPAIR_RECORD")] })
      .period,
  ).toBeNull();
});
it("does not silently intersect unequal inputs or accept uncovered safety periods", () => {
  expect(
    comparisonPeriod({
      economic: [input()],
      capacity: [input(start, "2026-10-20T00:00:00Z")],
    }).error,
  ).toContain("一致しません");
  expect(
    comparisonPeriod({
      capacity: [input()],
      safety: [input("2026-10-18T01:00:00Z", end)],
    }).error,
  ).toContain("覆っていません");
});
