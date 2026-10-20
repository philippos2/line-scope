import { useState, type ComponentProps, type FormEvent } from "react";

type Field = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
function invalidFields(form: HTMLFormElement) {
  return Array.from(form.querySelectorAll<Field>("input, select, textarea"))
    .filter((field) => field.willValidate && !field.validity.valid)
    .map((field) => ({
      field,
      label:
        field.getAttribute("aria-label") ??
        field.labels?.[0]?.textContent?.replace(/\s+/g, " ").trim() ??
        "入力項目",
    }));
}

// Browser constraint validation remains authoritative for the form UI.
// Do not duplicate domain validation or trigger a request from invalid input.
export function PreparedInputForm({
  children,
  onSubmit,
}: Pick<ComponentProps<"form">, "children" | "onSubmit">) {
  const [invalid, setInvalid] = useState<ReturnType<typeof invalidFields>>([]);
  const refresh = (event: FormEvent<HTMLFormElement>) => {
    if (invalid.length) setInvalid(invalidFields(event.currentTarget));
  };
  return (
    <form
      onInvalidCapture={(event) =>
        setInvalid(invalidFields(event.currentTarget))
      }
      onInputCapture={refresh}
      onChangeCapture={refresh}
      onSubmit={(event) => {
        setInvalid([]);
        onSubmit?.(event);
      }}
    >
      {children}
      {invalid.length > 0 && (
        <section role="alert" aria-label="入力内容の確認">
          <p>
            入力内容に不備があるため、今回の送信操作は行っていません。次の入力欄を確認してください。
          </p>
          <ul>
            {invalid.map(({ field, label }, index) => (
              <li key={index}>
                <button type="button" onClick={() => field.focus()}>
                  {label}
                </button>
                ：
                {field.validity.valueMissing
                  ? "入力が必要です。"
                  : "入力形式を確認してください。"}
              </li>
            ))}
          </ul>
        </section>
      )}
    </form>
  );
}
