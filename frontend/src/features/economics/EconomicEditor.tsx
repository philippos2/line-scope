import {
  OperationFeedback,
  useOperationFeedback,
} from "../inputs/OperationFeedback";
import {
  PrepareInputButton,
  PreparedInputNotice,
  usePreparedInput,
} from "../inputs/PreparedInputFeedback";
import { DateTimeInput } from "../inputs/DateTimeInput";
import { SuggestionScope, SuggestedInput } from "../inputs/InputAssistance";
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
  onOpenPrepared,
  signal,
  equipmentLabel = "登録データの対象設備",
}: {
  equipmentLabel?: string;
  initial: EconomicInput;
  onPrepared: (id: string) => void;
  onOpenPrepared?: (id: string) => void;
  signal: AbortSignal;
}) {
  const [value, setValue] = useState(initial);
  const retry = useRef<{ serialized: string; key: string } | null>(null);
  const body = {
    economic_input_id: value.economic_input_id || null,
    input: prepareInput(value),
    supersedes_update_request_id: null,
  };
  const operation = useOperationFeedback();
  const busy = operation.busy;
  const uncertain = operation.problem?.kind === "unknown";
  const preparation = usePreparedInput(body);
  const { serialized, alreadyPrepared } = preparation;
  function patch(field: string, text: string) {
    setValue((previous) => ({ ...previous, [field]: text }));
  }
  function payload(field: string, text: string) {
    setValue((previous) => ({
      ...previous,
      payload: {
        ...previous.payload,
        cost_recovery: previous.payload.cost_recovery
          ? {
              ...previous.payload.cost_recovery,
              source: "",
              certainty: "ESTIMATED",
              constant_daily_operation: null,
              replacement_removes_degradation: null,
            }
          : previous.payload.cost_recovery,
        options: previous.payload.options.map((option) => ({
          ...option,
          complete: false,
          items: option.items.map((item) => ({
            ...item,
            source: "",
            certainty: "ESTIMATED",
            independent: false,
          })),
        })),
        incident_losses: previous.payload.incident_losses?.map((item) => ({
          ...item,
          source: "",
          certainty: "ESTIMATED",
          independent: false,
        })),
        [field]: text,
      },
    }));
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
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (
      busy ||
      operation.isPending() ||
      alreadyPrepared ||
      signal.aborted ||
      (uncertain && retry.current?.serialized !== serialized)
    )
      return;
    if (retry.current?.serialized !== serialized)
      retry.current = { serialized, key: crypto.randomUUID() };
    void operation.run(
      async (active) => {
        const result = await request(
          "",
          "/economic-inputs/prepare",
          { ...body, retry_key: retry.current!.key },
          active,
        );
        if (active.aborted) return;
        const id = result.data.update_request_id;
        if (typeof id !== "string") throw new ApiError("INVALID_RESPONSE");
        preparation.remember(id, result);
        onPrepared(id);
      },
      { operation: "prepare", signal },
    );
  }
  return (
    <SuggestionScope
      label="経済入力の登録・訂正"
      value={{ equipment_id: value.equipment_id, payload: value.payload }}
    >
      <h2>
        {value.economic_input_id ? "経済入力を訂正する" : "経済入力を登録する"}
      </h2>
      <p>設備：{equipmentLabel}</p>
      <p>
        共通期間は日本時間で選択し、時間と金額は十進文字列です。空欄の金額・損失時間は不明で、0とは区別します。項目の適用期間が空欄なら、入力した共通期間を使用します。
      </p>
      <p className="muted">
        値を編集した場合は、出典と確認済みの扱いを引き継ぎません。変更内容に合う出典・確度を確認してください。
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <legend>共通比較条件</legend>
          <label>
            入力コード
            <SuggestedInput
              field="input_code"
              required
              value={value.input_code}
              maxLength={100}
              disabled={Boolean(value.economic_input_id)}
              onChange={(event) => patch("input_code", event.target.value)}
            />
          </label>
          <label>
            比較開始
            <DateTimeInput
              required
              placeholder="2026-10-01T00:00:00+09:00"
              value={value.payload.period_start}
              onChange={(text) => payload("period_start", text)}
            />
          </label>
          <label>
            比較終了
            <DateTimeInput
              required
              placeholder="2026-10-02T00:00:00+09:00"
              value={value.payload.period_end}
              onChange={(text) => payload("period_end", text)}
            />
          </label>
          <label>
            稼働時間
            <SuggestedInput
              field="payload.operating_hours"
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
                <SuggestedInput
                  field="payload.cost_recovery.daily_operating_hours"
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
                          source: "",
                          certainty: "ESTIMATED",
                          constant_daily_operation: null,
                          replacement_removes_degradation: null,
                          daily_operating_hours: daily || null,
                        },
                      },
                    }));
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
                            source: "",
                            certainty: "ESTIMATED",
                            [key]: next === "UNKNOWN" ? null : next === "true",
                          },
                        },
                      }));
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
                <SuggestedInput
                  field="payload.cost_recovery.source"
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
                          certainty: "ESTIMATED",
                        },
                      },
                    }));
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
                  }}
                >
                  <option value="ESTIMATED">推定</option>
                  <option value="CONFIRMED">確認済み</option>
                </select>
              </label>
            </>
          )}
        </fieldset>
        {value.payload.incident_losses && (
          <fieldset>
            <legend>調査用の停止損失根拠（円／時間）</legend>
            <p>
              製品・範囲・出典を保持して訂正します。修理案の費用とは別の根拠です。
            </p>
            {value.payload.incident_losses.map((row, index) => (
              <section key={row.scope_key}>
                <p>計上範囲：{row.scope_key}</p>
                <label>
                  時間当たり損失：{row.scope_key}
                  <SuggestedInput
                    field={`loss.${row.product_id}.loss_per_hour`}
                    inputMode="decimal"
                    value={row.loss_per_hour ?? ""}
                    onChange={(e) => {
                      setValue((old) => ({
                        ...old,
                        payload: {
                          ...old.payload,
                          incident_losses: old.payload.incident_losses?.map(
                            (item, i) =>
                              i === index
                                ? {
                                    ...item,
                                    loss_per_hour: e.target.value || null,
                                    source: "",
                                    certainty: "ESTIMATED",
                                    independent: false,
                                  }
                                : item,
                          ),
                        },
                      }));
                    }}
                  />
                </label>
                <label>
                  損害額の出典：{row.scope_key}
                  <SuggestedInput
                    field={`loss.${row.product_id}.source`}
                    required
                    value={row.source}
                    onChange={(event) => {
                      const source = event.target.value;
                      setValue((old) => ({
                        ...old,
                        payload: {
                          ...old.payload,
                          incident_losses: old.payload.incident_losses?.map(
                            (item, i) =>
                              i === index
                                ? { ...item, source, certainty: "ESTIMATED" }
                                : item,
                          ),
                        },
                      }));
                    }}
                  />
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={row.independent}
                    onChange={(event) => {
                      const independent = event.target.checked;
                      setValue((old) => ({
                        ...old,
                        payload: {
                          ...old.payload,
                          incident_losses: old.payload.incident_losses?.map(
                            (item, i) =>
                              i === index ? { ...item, independent } : item,
                          ),
                        },
                      }));
                    }}
                  />
                  この損害を独立して加算できることを確認した
                </label>
              </section>
            ))}
          </fieldset>
        )}
        {value.payload.options.map((choice, index) => (
          <fieldset key={choice.option} disabled={busy}>
            <legend>{optionNames[choice.option] ?? choice.option}</legend>
            {choice.items.map((item, itemIndex) => {
              function change(change: Partial<typeof item>) {
                const changedFact = Object.keys(change).some(
                  (key) =>
                    !["source", "certainty", "independent"].includes(key),
                );
                option(index, {
                  complete: false,
                  items: choice.items.map((entry, i) =>
                    i === itemIndex
                      ? {
                          ...entry,
                          ...(changedFact
                            ? {
                                source: "",
                                certainty: "ESTIMATED",
                                independent: false,
                              }
                            : {}),
                          ...change,
                        }
                      : entry,
                  ),
                });
              }
              return (
                <SuggestionScope
                  key={itemIndex}
                  fieldset
                  value={{
                    payload: value.payload,
                    option: choice.option,
                    cost_kind: item.kind,
                  }}
                >
                  <legend>費用項目 {itemIndex + 1}</legend>
                  <label>
                    項目キー
                    <SuggestedInput
                      field="cost.key"
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
                    <SuggestedInput
                      field="cost.amount"
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
                      <SuggestedInput
                        field="cost.hours"
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
                    <SuggestedInput
                      field="cost.source"
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
                    <DateTimeInput
                      value={item.valid_from}
                      placeholder="空欄は共通比較開始"
                      onChange={(text) => change({ valid_from: text })}
                    />
                  </label>
                  <label>
                    適用終了
                    <DateTimeInput
                      value={item.valid_to}
                      placeholder="空欄は共通比較終了"
                      onChange={(text) => change({ valid_to: text })}
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
                </SuggestionScope>
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
        <PrepareInputButton
          preparation={preparation}
          busy={busy}
          label={
            uncertain
              ? "同じ内容を再送して結果を確認"
              : "経済入力の変更準備を作成"
          }
          disabledReason={
            signal.aborted
              ? "接続または対象が変わったため、この編集画面からは送信できません。保存状態や登録内容を確認してください。"
              : uncertain && retry.current?.serialized !== serialized
                ? "送信時と入力が異なるため再送できません。元の内容へ戻してください。"
                : !value.equipment_id
                  ? "変更準備には対象設備の選択が必要です。"
                  : ""
          }
        />
      </form>
      <OperationFeedback
        problem={operation.problem}
        onRead={onOpenPrepared ?? onPrepared}
      />
      <PreparedInputNotice
        preparation={preparation}
        label="経済入力"
        equipmentLabel={equipmentLabel}
        onOpen={onOpenPrepared ?? onPrepared}
      />
    </SuggestionScope>
  );
}
