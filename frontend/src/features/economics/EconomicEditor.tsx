import { useRef, useState, type FormEvent } from "react";
import { ApiError, request } from "../../api/client";
import {
  blankItem,
  kindNames,
  optionNames,
  prepareInput,
  type EconomicInput,
} from "./model";

export function EconomicEditor({
  initial,
  onPrepared,
  signal,
}: {
  initial: EconomicInput;
  onPrepared: (id: string) => void;
  signal: AbortSignal;
}) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedId, setSavedId] = useState("");
  const retry = useRef<{ serialized: string; key: string } | null>(null);
  const pending = useRef(false);
  const heading = useRef<HTMLParagraphElement>(null);
  function patch(field: string, text: string) {
    setValue((previous) => ({ ...previous, [field]: text }));
    setSavedId("");
  }
  function payload(field: string, text: string) {
    setValue((previous) => ({
      ...previous,
      payload: { ...previous.payload, [field]: text },
    }));
    setSavedId("");
  }
  function option(
    index: number,
    change: Partial<EconomicInput["payload"]["options"][number]>,
  ) {
    setValue((previous) => ({
      ...previous,
      payload: {
        ...previous.payload,
        options: previous.payload.options.map((item, i) =>
          i === index ? { ...item, ...change } : item,
        ),
      },
    }));
    setSavedId("");
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setSavedId("");
    const body = {
      economic_input_id: value.economic_input_id || null,
      input: prepareInput(value),
      supersedes_update_request_id: null,
    };
    const serialized = JSON.stringify(body);
    if (retry.current?.serialized !== serialized)
      retry.current = { serialized, key: crypto.randomUUID() };
    try {
      const result = await request(
        "",
        "/economic-inputs/prepare",
        { ...body, retry_key: retry.current.key },
        signal,
      );
      if (signal.aborted) return;
      const id = result.data.update_request_id;
      if (typeof id !== "string") throw new ApiError("INVALID_RESPONSE");
      setSavedId(id);
      onPrepared(id);
    } catch (caught) {
      if (!signal.aborted)
        setError(
          `${caught instanceof ApiError ? caught.code : "REQUEST_FAILED"}。業務値はこの画面では確定しません。応答不明時は内容を変えず再送できます。書き込みは自動再送しません。`,
        );
    } finally {
      pending.current = false;
      if (!signal.aborted) setBusy(false);
    }
  }
  return (
    <section aria-label="経済入力の登録・訂正">
      <h2>
        {value.economic_input_id ? "経済入力を訂正する" : "経済入力を登録する"}
      </h2>
      <p>
        設備：{value.equipment_id || "未選択。設備候補から選択してください。"}
      </p>
      <p>
        共通期間はtimezone付き日時、時間と金額は十進文字列です。空欄の金額・損失時間は不明で、0とは区別します。項目の適用期間が空欄なら、入力した共通期間を使用します。
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <legend>共通比較条件</legend>
          <label>
            入力コード
            <input
              required
              value={value.input_code}
              maxLength={100}
              disabled={Boolean(value.economic_input_id)}
              onChange={(event) => patch("input_code", event.target.value)}
            />
          </label>
          <label>
            比較開始
            <input
              required
              placeholder="2026-10-01T00:00:00+09:00"
              value={value.payload.period_start}
              onChange={(event) => payload("period_start", event.target.value)}
            />
          </label>
          <label>
            比較終了
            <input
              required
              placeholder="2026-10-02T00:00:00+09:00"
              value={value.payload.period_end}
              onChange={(event) => payload("period_end", event.target.value)}
            />
          </label>
          <label>
            稼働時間
            <input
              required
              inputMode="decimal"
              value={value.payload.operating_hours}
              onChange={(event) =>
                payload("operating_hours", event.target.value)
              }
            />
          </label>
          <p>通貨：JPY</p>
        </fieldset>
        <fieldset disabled={busy}>
          <legend>単純費用回収期間の登録条件</legend>
          <label>
            <input
              type="checkbox"
              checked={Boolean(value.payload.cost_recovery)}
              onChange={(event) => {
                setValue((previous) => ({
                  ...previous,
                  payload: {
                    ...previous.payload,
                    cost_recovery: event.target.checked
                      ? {
                          daily_operating_hours: null,
                          constant_daily_operation: null,
                          replacement_removes_degradation: null,
                          source: "",
                          certainty: "ESTIMATED",
                        }
                      : null,
                  },
                }));
                setSavedId("");
              }}
            />
            単純費用回収の条件を登録する
          </label>
          <p>
            一定の日次稼働と、交換で劣化損失が解消する仮定を明示します。未登録・不明から日数を推測しません。
          </p>
          {value.payload.cost_recovery && (
            <>
              <label>
                1日稼働時間
                <input
                  inputMode="decimal"
                  value={
                    value.payload.cost_recovery.daily_operating_hours ?? ""
                  }
                  onChange={(event) => {
                    const daily = event.target.value;
                    setValue((previous) => ({
                      ...previous,
                      payload: {
                        ...previous.payload,
                        cost_recovery: {
                          ...previous.payload.cost_recovery!,
                          daily_operating_hours: daily || null,
                        },
                      },
                    }));
                    setSavedId("");
                  }}
                />
              </label>
              {(
                [
                  ["constant_daily_operation", "一定の日次稼働を仮定する"],
                  [
                    "replacement_removes_degradation",
                    "交換で劣化損失が解消すると仮定する",
                  ],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <select
                    aria-label={label}
                    value={
                      value.payload.cost_recovery?.[key] === null
                        ? "UNKNOWN"
                        : String(value.payload.cost_recovery?.[key])
                    }
                    onChange={(event) => {
                      const next = event.target.value;
                      setValue((previous) => ({
                        ...previous,
                        payload: {
                          ...previous.payload,
                          cost_recovery: {
                            ...previous.payload.cost_recovery!,
                            [key]: next === "UNKNOWN" ? null : next === "true",
                          },
                        },
                      }));
                      setSavedId("");
                    }}
                  >
                    <option value="UNKNOWN">不明</option>
                    <option value="true">はい</option>
                    <option value="false">いいえ</option>
                  </select>
                </label>
              ))}
              <label>
                費用回収条件の出典
                <input
                  required
                  maxLength={1000}
                  value={value.payload.cost_recovery.source}
                  onChange={(event) => {
                    const next = event.target.value;
                    setValue((previous) => ({
                      ...previous,
                      payload: {
                        ...previous.payload,
                        cost_recovery: {
                          ...previous.payload.cost_recovery!,
                          source: next,
                        },
                      },
                    }));
                    setSavedId("");
                  }}
                />
              </label>
              <label>
                費用回収条件の確度
                <select
                  aria-label="費用回収条件の確度"
                  value={value.payload.cost_recovery.certainty}
                  onChange={(event) => {
                    const next = event.target.value;
                    setValue((previous) => ({
                      ...previous,
                      payload: {
                        ...previous.payload,
                        cost_recovery: {
                          ...previous.payload.cost_recovery!,
                          certainty: next,
                        },
                      },
                    }));
                    setSavedId("");
                  }}
                >
                  <option value="ESTIMATED">推定</option>
                  <option value="CONFIRMED">確認済み</option>
                </select>
              </label>
            </>
          )}
        </fieldset>
        {value.payload.options.map((choice, index) => (
          <fieldset key={choice.option} disabled={busy}>
            <legend>{optionNames[choice.option] ?? choice.option}</legend>
            {choice.items.map((item, itemIndex) => {
              function change(change: Partial<typeof item>) {
                option(index, {
                  items: choice.items.map((entry, i) =>
                    i === itemIndex ? { ...entry, ...change } : entry,
                  ),
                });
              }
              return (
                <fieldset key={itemIndex}>
                  <legend>費用項目 {itemIndex + 1}</legend>
                  <label>
                    項目キー
                    <input
                      required
                      maxLength={100}
                      value={item.key}
                      onChange={(event) => change({ key: event.target.value })}
                    />
                  </label>
                  <label>
                    費用種別
                    <select
                      value={item.kind}
                      onChange={(event) =>
                        change({ kind: event.target.value, hours: null })
                      }
                    >
                      {Object.entries(kindNames).map(([key, label]) => (
                        <option key={key} value={key}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {item.kind === "DIRECT"
                      ? "直接費（JPY）"
                      : "損失率（JPY/hour）"}
                    <input
                      inputMode="decimal"
                      value={item.amount ?? ""}
                      placeholder="空欄は不明"
                      onChange={(event) =>
                        change({ amount: event.target.value || null })
                      }
                    />
                  </label>
                  {item.kind !== "DIRECT" && (
                    <label>
                      損失時間
                      <input
                        inputMode="decimal"
                        value={item.hours ?? ""}
                        placeholder="空欄は不明"
                        onChange={(event) =>
                          change({ hours: event.target.value || null })
                        }
                      />
                    </label>
                  )}
                  <label>
                    出典
                    <input
                      required
                      maxLength={1000}
                      value={item.source}
                      onChange={(event) =>
                        change({ source: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    値の確度
                    <select
                      value={item.certainty}
                      onChange={(event) =>
                        change({ certainty: event.target.value })
                      }
                    >
                      <option value="ESTIMATED">推定</option>
                      <option value="CONFIRMED">確定</option>
                    </select>
                  </label>
                  <label>
                    適用開始
                    <input
                      value={item.valid_from}
                      placeholder="空欄は共通比較開始"
                      onChange={(event) =>
                        change({ valid_from: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    適用終了
                    <input
                      value={item.valid_to}
                      placeholder="空欄は共通比較終了"
                      onChange={(event) =>
                        change({ valid_to: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={item.independent}
                      onChange={(event) =>
                        change({ independent: event.target.checked })
                      }
                    />
                    他の項目と重複しないことを確認した
                  </label>
                  <button
                    type="button"
                    disabled={choice.items.length <= 1}
                    onClick={() =>
                      option(index, {
                        items: choice.items.filter((_, i) => i !== itemIndex),
                      })
                    }
                  >
                    この項目を削除
                  </button>
                </fieldset>
              );
            })}
            <button
              type="button"
              disabled={choice.items.length >= 30}
              onClick={() =>
                option(index, { items: [...choice.items, blankItem()] })
              }
            >
              費用項目を追加
            </button>
            <label>
              <input
                type="checkbox"
                checked={choice.complete}
                onChange={(event) =>
                  option(index, { complete: event.target.checked })
                }
              />
              この期間に必要な費用項目を網羅した
            </label>
          </fieldset>
        ))}
        <button className="primary" disabled={busy || !value.equipment_id}>
          {busy ? "変更準備中…" : "経済入力の変更準備を作成"}
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      {savedId && (
        <p ref={heading} role="status">
          変更要求ID：{savedId}
          。別の工場管理者が保存Snapshotを確認して承認し、元の要求者が実行してください。
          <button onClick={() => onPrepared(savedId)}>
            承認・実行画面へ渡す
          </button>
        </p>
      )}
    </section>
  );
}
