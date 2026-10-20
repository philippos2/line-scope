import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PreparedInputForm } from "./PreparedInputForm";
afterEach(cleanup);
it("blocks invalid submission and clears its summary when required fields are completed", async () => {
  const submit = vi.fn((event) => event.preventDefault());
  render(
    <PreparedInputForm onSubmit={submit}>
      <label>
        出典
        <input required />
      </label>
      <button>変更準備</button>
    </PreparedInputForm>,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "変更準備" }));
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByRole("alert").textContent).toContain(
    "今回の送信操作は行っていません",
  );
  await user.type(screen.getByLabelText("出典"), "検証用の出典");
  expect(screen.queryByRole("alert")).toBeNull();
  await user.click(screen.getByRole("button", { name: "変更準備" }));
  expect(submit).toHaveBeenCalledTimes(1);
});
