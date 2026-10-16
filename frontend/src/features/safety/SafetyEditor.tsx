import { useRef, useState, type FormEvent } from "react";
import { ApiError, request } from "../../api/client";
import { decisions, textFields, type SafetyInput } from "./model";
export function SafetyEditor({
  initial,
  onPrepared,
  signal,
}: {
  initial: SafetyInput;
  onPrepared: (id: string) => void;
  signal: AbortSignal;
}) {
  const [value, setValue] = useState(initial),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [saved, setSaved] = useState("");
  const retry = useRef<{ serialized: string; key: string } | null>(null),
    pending = useRef(false);
  function patch(key: string, text: string) {
    setValue((previous) => ({ ...previous, [key]: text }));
    setSaved("");
  }
  function payload(key: string, text: unknown) {
    setValue((previous) => ({
      ...previous,
      payload: { ...previous.payload, [key]: text },
    }));
    setSaved("");
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setSaved("");
    const body = {
      safety_input_id: value.safety_input_id || null,
      input: {
        input_code: value.input_code,
        equipment_id: value.equipment_id,
        payload: value.payload,
      },
      supersedes_update_request_id: null,
    };
    const serialized = JSON.stringify(body);
    if (retry.current?.serialized !== serialized)
      retry.current = { serialized, key: crypto.randomUUID() };
    try {
      const result = await request(
        "",
        "/safety-inputs/prepare",
        { ...body, retry_key: retry.current.key },
        signal,
      );
      if (signal.aborted) return;
      const id = result.data.update_request_id;
      if (typeof id !== "string") throw new ApiError("INVALID_RESPONSE");
      setSaved(id);
      onPrepared(id);
    } catch (caught) {
      if (!signal.aborted)
        setError(
          `${caught instanceof ApiError ? caught.code : "REQUEST_FAILED"}。この画面では確定しません。応答不明時は内容を変えず再送できます。`,
        );
    } finally {
      pending.current = false;
      if (!signal.aborted) setBusy(false);
    }
  }
  const p = value.payload;
  return (
    <section aria-label="安全入力の登録・訂正">
      <h2>
        {value.safety_input_id ? "安全入力を訂正する" : "安全入力を登録する"}
      </h2>
      <p>
        出典のある観測・基準・判断を登録します。空欄は不明です。数値基準や故障確率をこの画面で生成しません。
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <legend>安全判断の記録</legend>
          <label>
            安全入力の入力コード
            <input
              required
              maxLength={100}
              disabled={Boolean(value.safety_input_id)}
              value={value.input_code}
              onChange={(event) => patch("input_code", event.target.value)}
            />
          </label>
          <label>
            安全情報の適用開始
            <input
              required
              value={String(p.period_start)}
              onChange={(event) => payload("period_start", event.target.value)}
            />
          </label>
          <label>
            安全情報の適用終了
            <input
              required
              value={String(p.period_end)}
              onChange={(event) => payload("period_end", event.target.value)}
            />
          </label>
          <p>
            日時にはtimezoneを付けてください。適用期間外は安全判定不明として表示します。
          </p>
          {Object.entries(textFields).map(([key, label]) => (
            <label key={key}>
              {label}
              <textarea
                maxLength={1000}
                value={typeof p[key] === "string" ? p[key] : ""}
                onChange={(event) => payload(key, event.target.value || null)}
              />
            </label>
          ))}
          <label>
            安全判断の出典
            <textarea
              required
              maxLength={1000}
              value={String(p.source)}
              onChange={(event) => payload("source", event.target.value)}
            />
          </label>
          <label>
            安全判定
            <select
              value={String(p.decision)}
              onChange={(event) => payload("decision", event.target.value)}
            >
              {Object.entries(decisions).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            安全判断の確度
            <select
              value={String(p.certainty)}
              onChange={(event) => payload("certainty", event.target.value)}
            >
              <option value="ESTIMATED">推定</option>
              <option value="CONFIRMED">確定</option>
            </select>
          </label>
        </fieldset>
        <button disabled={busy}>安全入力の変更準備を作成</button>
      </form>
      {busy && <p role="status">処理中…</p>}
      {error && <p role="alert">{error}</p>}
      {saved && (
        <p role="status">
          変更準備を保存しました。承認付きActionで保存Snapshotを確認してください。
        </p>
      )}
    </section>
  );
}
