import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DocumentSearchStatus } from "./DocumentSearchStatus";
afterEach(cleanup);
it("marks an earlier search after execution without asserting the document itself changed", () => {
  const observation = {
    equipmentId: "equipment-a",
    equipmentLabel: "設備A",
    completedAt: "2026-10-18T00:00:00Z",
    epoch: 0,
  };
  const view = render(
    <DocumentSearchStatus observation={observation} executionEpoch={0} />,
  );
  expect(screen.getByText(/検索完了時刻/).textContent).toContain("9:00:00");
  expect(screen.queryByText(/更新前の検索結果/)).toBeNull();
  view.rerender(
    <DocumentSearchStatus observation={observation} executionEpoch={1} />,
  );
  expect(screen.getByText(/更新前の検索結果/)).toBeDefined();
  expect(screen.getByText(/文書自体の改訂の有無/)).toBeDefined();
  view.rerender(
    <DocumentSearchStatus
      observation={{ ...observation, epoch: 1 }}
      executionEpoch={1}
    />,
  );
  expect(screen.queryByText(/更新前の検索結果/)).toBeNull();
});
