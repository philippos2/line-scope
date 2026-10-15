import { object, type JsonObject } from "../../api/client";
const shown = (value: unknown) => (typeof value === "string" ? value : "不明");
const statuses: Record<string, string> = {
  SUFFICIENT: "能力面で充足",
  INSUFFICIENT: "能力不足",
  INCOMPATIBLE: "製品非互換",
  UNKNOWN: "能力判定不明",
};
export function CapacityResult({
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
  const c = data.calculation;
  const labels = object(data.labels) ? data.labels : {};
  return (
    <section aria-label="登録済み能力入力の計算結果">
      <h2>正式能力入力：{shown(data.input.input_code)}</h2>
      {stale && (
        <p className="notice">
          取得時の結果です。確定操作後は登録値を再取得してください。
        </p>
      )}
      <p>
        設備：{shown(labels.equipment_name)}（{shown(labels.equipment_code)}） /
        製品：{shown(labels.product_name)}（{shown(labels.product_code)}）
      </p>
      <p>
        version {String(data.input.version)} / 観測日時：
        {shown(data.observed_at)}
      </p>
      <p>
        評価期間：{shown(c.period_start)} ～ {shown(c.period_end)}
      </p>
      <h3>{statuses[shown(c.capacity_status)] ?? "能力判定不明"}</h3>
      <dl>
        <dt>必要能力</dt>
        <dd>
          {shown(c.required_rate)} {shown(c.quantity_unit)}/hour
        </dd>
        <dt>利用可能能力</dt>
        <dd>
          {shown(c.available_rate)} {shown(c.quantity_unit)}/hour
        </dd>
        <dt>不足量</dt>
        <dd>
          {shown(c.shortage_rate)} {shown(c.quantity_unit)}/hour
        </dd>
        <dt>製品互換性</dt>
        <dd>
          {c.compatibility === true
            ? "確認済み"
            : c.compatibility === false
              ? "非互換"
              : "不明"}
        </dd>
      </dl>
      <p>条件付き許容停止時間：{shown(c.permissible_downtime_hours)} 時間</p>
      <p>条件付き復旧期限：{shown(c.recovery_deadline)}</p>
      <p>
        出典：{shown(c.source)} /{" "}
        {c.certainty === "CONFIRMED" ? "確定" : "推定"}
      </p>
      {Array.isArray(c.missing_information) &&
        c.missing_information.length > 0 && (
          <p>
            不足・未確認事項：{c.missing_information.map(String).join("、")}
          </p>
        )}
      <p className="notice">
        能力面の評価です。安全・品質・実稼働・完全代替は未評価です。復旧期限は表示した入力前提の範囲に限ります。
      </p>
      <details>
        <summary>計算入力・製品・出典・復旧期限の前提</summary>
        <pre>{JSON.stringify(data.input, null, 2)}</pre>
      </details>
    </section>
  );
}
