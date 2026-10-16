import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, request, object, type JsonObject } from "../../api/client";
import { kinds, fields, type MaintenanceInput } from "./model";
export function MaintenanceEditor({
  initial,
  onPrepared,
  signal,
}: {
  initial: MaintenanceInput;
  onPrepared: (id: string) => void;
  signal: AbortSignal;
}) {
  const [value, setValue] = useState(initial),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [saved, setSaved] = useState("");
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
      maintenance_input_id: value.maintenance_input_id || null,
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
        "/maintenance-inputs/prepare",
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
    <section aria-label="対応計画・故障履歴の登録・訂正">
      <h2>
        {value.maintenance_input_id
          ? "対応計画・故障履歴を訂正する"
          : "対応計画・故障履歴を登録する"}
      </h2>
      <p>
        出典のある計画・実績を登録します。空欄は不明です。調達待ち・作業・停止時間を分けます。過去損失から将来故障率を生成しません。
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <legend>計画・実績の記録</legend>
          <label>
            対応計画・故障履歴の入力コード
            <input
              required
              maxLength={100}
              disabled={Boolean(value.maintenance_input_id)}
              value={value.input_code}
              onChange={(event) => patch("input_code", event.target.value)}
            />
          </label>
          <label>
            評価・記録の期間開始
            <input
              required
              value={String(p.period_start)}
              onChange={(event) => payload("period_start", event.target.value)}
            />
          </label>
          <label>
            評価・記録の期間終了
            <input
              required
              value={String(p.period_end)}
              onChange={(event) => payload("period_end", event.target.value)}
            />
          </label>
          <p>
            日時にはtimezoneを付けてください。計画の期間は共通の費用評価期間、履歴では過去の事象期間です。期間外費用を自動で加除しません。
          </p>
          <section aria-label="次回保全の選択">
            <h3>次回保全の候補</h3>
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
                      {String(row.plan_code)} / {String(row.planned_start)}{" "}
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
          {Object.entries(fields).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                maxLength={1000}
                required={key === "details"}
                value={typeof p[key] === "string" ? p[key] : ""}
                onChange={(event) => payload(key, event.target.value || null)}
              />
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
          <label>
            計画・実績の出典
            <textarea
              required
              maxLength={1000}
              value={String(p.source)}
              onChange={(event) => payload("source", event.target.value)}
            />
          </label>
        </fieldset>
        <button disabled={busy}>対応計画・故障履歴の変更準備を作成</button>
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
