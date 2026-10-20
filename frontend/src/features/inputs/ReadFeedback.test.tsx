import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ReadFeedback } from "./ReadFeedback";
afterEach(cleanup);
it("keeps diagnostic values inside closed technical details and retries only on explicit action", () => {
  const retry = vi.fn();
  render(
    <ReadFeedback
      problem={{ code: "CONNECTION_FAILED", requestId: "diagnostic-key" }}
      operation="登録内容の取得"
      onRetry={retry}
    />,
  );
  expect(screen.getByRole("alert").textContent).toContain(
    "接続できませんでした",
  );
  const technical = screen.getByText("CONNECTION_FAILED").closest("details");
  expect(technical?.hasAttribute("open")).toBe(false);
  expect(screen.getByText(/diagnostic-key/).closest("details")).toBe(technical);
  expect(retry).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "登録内容の取得を再試行" }),
  );
  expect(retry).toHaveBeenCalledTimes(1);
});
