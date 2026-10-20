import {
  OperationFeedback,
  useOperationFeedback,
} from "../inputs/OperationFeedback";
import {
  PrepareInputButton,
  PreparedInputNotice,
  usePreparedInput,
} from "../inputs/PreparedInputFeedback";
import { displayPeriod } from "../investigation/EquipmentInvestigation";
import { DateTimeInput } from "../inputs/DateTimeInput";
import {
  SuggestionScope,
  SuggestedInput,
  SuggestedText,
} from "../inputs/InputAssistance";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, request, object, type JsonObject } from "../../api/client";
import { kinds, fields, type MaintenanceInput } from "./model";
export function MaintenanceEditor({
  initial,
  onPrepared,
  onOpenPrepared,
  signal,
}: {
  initial: MaintenanceInput;
  onPrepared: (id: string) => void;
  onOpenPrepared?: (id: string) => void;
  signal: AbortSignal;
}) {
  const [value, setValue] = useState(initial);
  const [plans, setPlans] = useState<JsonObject | null>(null);
  const [plansError, setPlansError] = useState("");
  useEffect(() => {
    void request(
      "",
      `/maintenance-inputs/next-plans/${encodeURIComponent(initial.equipment_id)}`,
      undefined,
      signal,
    )
      .then((result) => {
        if (!signal.aborted) setPlans(result.data);
      })
      .catch(() => {
        if (!signal.aborted)
          setPlansError(
            "保全予定の候補を取得できません。関連付けは未確認です。",
          );
      });
  }, [initial.equipment_id, signal]);
  const retry = useRef<{ serialized: string; key: string } | null>(null);
  const body = {
    maintenance_input_id: value.maintenance_input_id || null,
    input: {
      input_code: value.input_code,
      equipment_id: value.equipment_id,
      payload: value.payload,
    },
    supersedes_update_request_id: null,
  };
  const operation = useOperationFeedback();
  const busy = operation.busy;
  const uncertain = operation.problem?.kind === "unknown";
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
        ...(key !== "source" ? { source: "" } : {}),
        [key]: text,
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
          "/maintenance-inputs/prepare",
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
  const p = value.payload;
  return (
    <SuggestionScope
      label="対応計画・故障履歴の登録・訂正"
      value={{
        equipment_id: value.equipment_id,
        payload: value.payload,
        kind: value.payload.kind,
      }}
    >
      <h2>
        {value.maintenance_input_id
          ? "対応計画・故障履歴を訂正する"
          : "対応計画・故障履歴を登録する"}
      </h2>
      <p>
        出典のある計画・実績を登録します。空欄は不明です。調達待ち・作業・停止時間を分けます。過去損失から将来故障率を生成しません。
      </p>
      <p className="muted">
        値を編集した場合は、出典と確認済みの扱いを引き継ぎません。変更内容に合う出典・確度を確認してください。
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <legend>計画・実績の記録</legend>
          <label>
            対応計画・故障履歴の入力コード
            <SuggestedInput
              field="input_code"
              required
              maxLength={100}
              disabled={Boolean(value.maintenance_input_id)}
              value={value.input_code}
              onChange={(event) => patch("input_code", event.target.value)}
            />
          </label>
          <label>
            評価・記録の期間開始
            <DateTimeInput
              required
              value={String(p.period_start)}
              onChange={(text) => payload("period_start", text)}
            />
          </label>
          <label>
            評価・記録の期間終了
            <DateTimeInput
              required
              value={String(p.period_end)}
              onChange={(text) => payload("period_end", text)}
            />
          </label>
          <p>
            日時は日本時間で選択します。計画の期間は共通の費用評価期間、履歴では過去の事象期間です。期間外費用を自動で加除しません。
          </p>
          <section aria-label="次回保全の選択">
            <h3>次回保全の候補</h3>
            <p>
              {p.maintenance_plan_id
                ? "登録済みの保全予定を関連付けています。"
                : "保全予定は未選択です。"}
            </p>
            {p.maintenance_plan_id != null && (
              <button
                type="button"
                onClick={() => payload("maintenance_plan_id", null)}
              >
                保全予定の関連付けを外す
              </button>
            )}
            {plansError && <p role="alert">{plansError}</p>}
            {plans && (
              <>
                <p>
                  {plans.complete === false
                    ? "取得が不完全なため次回を選定できません。"
                    : plans.selection_required
                      ? "同時刻の候補があります。対象を選択してください。"
                      : "将来のPLANNED保全予定です。関連付けても自動で停止しません。"}
                </p>
                {Array.isArray(plans.next_candidates) &&
                  plans.next_candidates.filter(object).map((row) => (
                    <button
                      type="button"
                      key={String(row.maintenance_plan_id)}
                      onClick={() =>
                        payload("maintenance_plan_id", row.maintenance_plan_id)
                      }
                    >
                      {String(row.plan_code)} /{" "}
                      {displayPeriod(row.planned_start, row.planned_start)}{" "}
                      を関連付ける
                    </button>
                  ))}
              </>
            )}
          </section>
          <label>
            記録分類
            <select
              value={String(p.kind)}
              onChange={(event) => payload("kind", event.target.value)}
            >
              {Object.entries(kinds).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {Object.entries(fields)
            .filter(([key]) => key !== "maintenance_plan_id")
            .map(([key, label]) => (
              <label key={key}>
                {label}
                {key === "interim_until" ? (
                  <DateTimeInput
                    value={typeof p[key] === "string" ? p[key] : ""}
                    onChange={(text) => payload(key, text || null)}
                  />
                ) : (
                  <SuggestedInput
                    field={`payload.${key}`}
                    inputMode={
                      key.endsWith("_hours") || key.endsWith("_jpy")
                        ? "decimal"
                        : undefined
                    }
                    maxLength={1000}
                    required={key === "details"}
                    value={typeof p[key] === "string" ? p[key] : ""}
                    onChange={(event) =>
                      payload(key, event.target.value || null)
                    }
                  />
                )}
              </label>
            ))}
          <label>
            交換費を評価期間の費用へ含める
            <select
              value={
                p.include_replacement_cost === null
                  ? "UNKNOWN"
                  : String(p.include_replacement_cost)
              }
              onChange={(event) =>
                payload(
                  "include_replacement_cost",
                  event.target.value === "UNKNOWN"
                    ? null
                    : event.target.value === "true",
                )
              }
            >
              <option value="UNKNOWN">未決定（履歴では選択しない）</option>
              <option value="true">含める</option>
              <option value="false">含めない</option>
            </select>
          </label>
          <p>
            履歴の期間は過去の事象期間です。履歴には調達待ち・暫定終了・交換費の算入を入力しません。過去損失は履歴だけに入力します。次回保全で停止する場合は保全予定を別途登録・承認し、そのIDを関連付けてください。設備状態の自動変更は行いません。
          </p>
          <SuggestedText
            label="計画・実績の出典"
            field="payload.source"
            required
            maxLength={1000}
            value={String(p.source)}
            onValue={(text) => payload("source", text)}
          />
        </fieldset>
        <PrepareInputButton
          preparation={preparation}
          busy={busy}
          label={
            uncertain
              ? "同じ内容を再送して結果を確認"
              : "対応計画・故障履歴の変更準備を作成"
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
        label="対応計画・故障履歴"
        onOpen={onOpenPrepared ?? onPrepared}
      />
    </SuggestionScope>
  );
}
