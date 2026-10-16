import { object, type JsonObject } from "../../api/client";
import { fields, kinds } from "./model";
const shown = (value: unknown): string =>
  value === null || value === undefined ? "不明" : String(value);
export function MaintenanceResult({
  data,
  stale = false,
}: {
  data: JsonObject;
  stale?: boolean;
}) {
  if (
    data.source !== "REGISTERED_INPUT" ||
    !object(data.input) ||
    !object(data.calculation)
  )
    return null;
  const c = data.calculation,
    next = object(data.next_maintenance) ? data.next_maintenance : null;
  return (
    <section aria-label="登録済み対応計画・故障履歴の参照結果">
      <h2>正式対応計画・故障履歴：{shown(data.input.input_code)}</h2>
      {stale && (
        <p className="notice">
          取得時の結果です。確定操作後は登録値を再取得してください。
        </p>
      )}
      <p>
        version {shown(data.input.version)} / 観測日時：
        {shown(data.observed_at)}
      </p>
      <h3>{kinds[shown(c.kind)] ?? "不明"}</h3>
      <p>
        分類：
        {c.record_scope === "HISTORICAL"
          ? "過去の事象記録"
          : "計画の評価期間"}{" "}
        / 期間：{shown(c.period_start)} ～ {shown(c.period_end)}
      </p>
      <dl>
        {Object.entries(fields).map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>{shown(c[key])}</dd>
          </div>
        ))}
        <dt>出典</dt>
        <dd>{shown(c.source)}</dd>
        <dt>交換費の算入</dt>
        <dd>
          {c.include_replacement_cost === true
            ? "含める"
            : c.include_replacement_cost === false
              ? "含めない"
              : "未決定"}
        </dd>
        <dt>既知の計画直接費小計（JPY）</dt>
        <dd>{shown(c.known_plan_direct_cost_subtotal_jpy)}</dd>
        <dt>総経済影響（JPY）</dt>
        <dd>不明</dd>
      </dl>
      <p className="notice">
        調達待ち・作業・停止時間は別の値です。過去損失を将来費用へ加算せず、将来故障率や実行可能性を認定しません。次回保全の停止は予定であり、自動で状態変更しません。
      </p>
      {next && (
        <details>
          <summary>次回保全の候補・関連付ける予定ID</summary>
          <p>
            {next.selection_status === "SELECT_REQUIRED"
              ? "開始時刻が同じ候補が複数あります。利用者が選択してください。"
              : next.selection_status === "INCOMPLETE"
                ? "候補取得が不完全なため次回を判定できません。"
                : next.selection_status === "NONE"
                  ? "将来のPLANNED保全予定はありません。"
                  : "最も早く開始する将来のPLANNED保全予定です。"}
          </p>
          <pre>{JSON.stringify(next.next_candidates, null, 2)}</pre>
        </details>
      )}
      <details>
        <summary>計画・履歴の登録入力・出典</summary>
        <pre>{JSON.stringify(data.input, null, 2)}</pre>
      </details>
    </section>
  );
}
