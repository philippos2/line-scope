import { object, type JsonObject } from "../../api/client";
import { decisions } from "./model";
const shown = (value: unknown) => (typeof value === "string" ? value : "不明");
export function SafetyResult({
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
  return (
    <section aria-label="登録済み安全入力の判定結果">
      <h2>正式安全入力：{shown(data.input.input_code)}</h2>
      {stale && (
        <p className="notice">
          取得時の結果です。確定操作後は登録値を再取得してください。
        </p>
      )}
      <p>
        version {String(data.input.version)} / 観測日時：
        {shown(data.observed_at)}
      </p>
      <h3>{decisions[shown(c.status)] ?? "不明"}</h3>
      <p>
        {c.continue_candidate === "EXCLUDED"
          ? "継続案を候補から除外します。経済利益で停止基準を上書きしません。"
          : c.continue_candidate === "CONDITIONAL"
            ? "登録された条件の範囲での判断です。"
            : "継続可能とは認定しません。"}
      </p>
      <p>
        適用期間：{shown(c.period_start)} ～ {shown(c.period_end)}
      </p>
      <p>評価時刻：{shown(c.evaluated_at)}</p>
      <dl>
        <dt>観測内容</dt>
        <dd>{shown(c.observation)}</dd>
        <dt>安全基準</dt>
        <dd>{shown(c.criterion)}</dd>
        <dt>継続条件</dt>
        <dd>{shown(c.conditions)}</dd>
        <dt>出典</dt>
        <dd>{shown(c.source)}</dd>
        <dt>残存リスクの資料・不足情報</dt>
        <dd>{shown(c.risk_notes)}</dd>
      </dl>
      {Array.isArray(c.missing_information) &&
        c.missing_information.length > 0 && (
          <p>不足・未確認：{c.missing_information.map(String).join("、")}</p>
        )}
      <p className="notice">
        単一記録の評価です。設備全体の安全や実運転許可を認定しません。残存リスクは不明です。
      </p>
      <details>
        <summary>安全判断の入力・出典・適用期間</summary>
        <pre>{JSON.stringify(data.input, null, 2)}</pre>
      </details>
    </section>
  );
}
