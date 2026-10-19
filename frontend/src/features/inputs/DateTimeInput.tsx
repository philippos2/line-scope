import type { InputHTMLAttributes } from "react";

// Conversion is display-only until the user actually edits the field.
export function localDateTime(value: string) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : new Date(date.getTime() + 9 * 3600000).toISOString().slice(0, 23);
}
export function DateTimeInput({
  value,
  onChange,
  ...props
}: Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "value" | "onChange" | "type"
> & { value: string; onChange: (value: string) => void }) {
  const local = localDateTime(value);
  return (
    <>
      <input
        {...props}
        type="datetime-local"
        step="any"
        value={local}
        onChange={(event) => {
          const next = event.target.value;
          if (
            next !== local &&
            !(
              next &&
              value &&
              Date.parse(`${next}+09:00`) === Date.parse(value)
            )
          )
            onChange(next ? `${next}+09:00` : "");
        }}
      />
      <small className="muted">日本時間</small>
      {value && !local && (
        <small role="alert">日時の形式を確認し、選び直してください。</small>
      )}
    </>
  );
}
