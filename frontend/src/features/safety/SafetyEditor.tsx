import {
  PrepareInputButton,
  PreparedInputNotice,
  usePreparedInput,
} from "../inputs/PreparedInputFeedback";
import { DateTimeInput } from "../inputs/DateTimeInput";
import {
  SuggestionScope,
  SuggestedInput,
  SuggestedText,
} from "../inputs/InputAssistance";
import { useRef, useState, type FormEvent } from "react";
import { ApiError, request } from "../../api/client";
import { decisions, textFields, type SafetyInput } from "./model";
export function SafetyEditor({
  initial,
  onPrepared,
  onOpenPrepared,
  signal,
}: {
  initial: SafetyInput;
  onPrepared: (id: string) => void;
  onOpenPrepared?: (id: string) => void;
  signal: AbortSignal;
}) {
  const [value, setValue] = useState(initial),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const retry = useRef<{ serialized: string; key: string } | null>(null),
    pending = useRef(false);
  const body = {
    safety_input_id: value.safety_input_id || null,
    input: {
      input_code: value.input_code,
      equipment_id: value.equipment_id,
      payload: value.payload,
    },
    supersedes_update_request_id: null,
  };
  const preparation = usePreparedInput(body);
  const { serialized, alreadyPrepared } = preparation;
  function patch(key: string, text: string) {
    setValue((previous) => ({ ...previous, [key]: text }));
  }
  function payload(key: string, text: unknown) {
    setValue((previous) => ({
      ...previous,
      payload: {
        ...previous.payload,
        ...(key !== "source" && key !== "certainty"
          ? { source: "", certainty: "ESTIMATED" }
          : {}),
        [key]: text,
      },
    }));
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending.current || alreadyPrepared) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      if (retry.current?.serialized !== serialized)
        retry.current = { serialized, key: crypto.randomUUID() };
      const result = await request(
        "",
        "/safety-inputs/prepare",
        { ...body, retry_key: retry.current.key },
        signal,
      );
      if (signal.aborted) return;
      const id = result.data.update_request_id;
      if (typeof id !== "string") throw new ApiError("INVALID_RESPONSE");
      preparation.remember(id, result);
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
    <SuggestionScope
      label="安全入力の登録・訂正"
      value={{ equipment_id: value.equipment_id, payload: value.payload }}
    >
      <h2>
        {value.safety_input_id ? "安全入力を訂正する" : "安全入力を登録する"}
      </h2>
      <p>
        出典のある観測・基準・判断を登録します。空欄は不明です。数値基準や故障確率をこの画面で生成しません。
      </p>
      <p className="muted">
        値を編集した場合は、出典と確認済みの扱いを引き継ぎません。変更内容に合う出典・確度を確認してください。
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <legend>安全判断の記録</legend>
          <label>
            安全入力の入力コード
            <SuggestedInput
              field="input_code"
              required
              maxLength={100}
              disabled={Boolean(value.safety_input_id)}
              value={value.input_code}
              onChange={(event) => patch("input_code", event.target.value)}
            />
          </label>
          <label>
            安全情報の適用開始
            <DateTimeInput
              required
              value={String(p.period_start)}
              onChange={(text) => payload("period_start", text)}
            />
          </label>
          <label>
            安全情報の適用終了
            <DateTimeInput
              required
              value={String(p.period_end)}
              onChange={(text) => payload("period_end", text)}
            />
          </label>
          <p>
            日時は日本時間で選択します。適用期間外は安全判定不明として表示します。
          </p>
          {Object.entries(textFields).map(([key, label]) => (
            <SuggestedText
              key={key}
              label={label}
              field={`payload.${key}`}
              maxLength={1000}
              value={typeof p[key] === "string" ? p[key] : ""}
              onValue={(text) => payload(key, text || null)}
            />
          ))}
          <SuggestedText
            label="安全判断の出典"
            field="payload.source"
            required
            maxLength={1000}
            value={String(p.source)}
            onValue={(text) => payload("source", text)}
          />
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
        <PrepareInputButton
          preparation={preparation}
          busy={busy}
          label="安全入力の変更準備を作成"
          disabledReason={
            !value.equipment_id ? "変更準備には対象設備の選択が必要です。" : ""
          }
        />
      </form>
      {error && <p role="alert">{error}</p>}
      <PreparedInputNotice
        preparation={preparation}
        label="安全入力"
        onOpen={onOpenPrepared ?? onPrepared}
      />
    </SuggestionScope>
  );
}
