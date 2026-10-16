import { object, type JsonObject } from "../../api/client";
import { CostRecoveryResult } from "./CostRecoveryResult";
import { kindNames, optionNames } from "./model";

const shown = (value: unknown) =>
  typeof value === "string" ? value : "未取得";
export function EconomicResult({
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
  const input = data.input,
    calculation = data.calculation;
  const options = Array.isArray(calculation.options)
    ? calculation.options.filter(object)
    : [];
  return (
    <section aria-label="登録済み経済入力の計算結果">
      <h2>正式経済入力：{shown(input.input_code)}</h2>
      {stale && (
        <p className="notice">
          取得時の結果です。確定操作後は登録値を再取得してください。
        </p>
      )}
      <p>
        登録値の見積計算 / version {String(input.version)} / 観測日時：
        {shown(data.observed_at)}
      </p>
      <p>
        比較期間：{shown(calculation.period_start)} ～{" "}
        {shown(calculation.period_end)} / 明示稼働時間：
        {shown(calculation.operating_hours)}時間
      </p>
      <p className="notice">
        登録値に基づく条件付き見積です。能力・安全性・最適案は未評価です。
      </p>
      <div className="option-grid">
        {options.map((option, index) => (
          <article key={index} className="evidence-card">
            <h3>{optionNames[shown(option.option)] ?? shown(option.option)}</h3>
            <p>
              見積総額：
              <strong>
                {typeof option.total_jpy === "string"
                  ? `${option.total_jpy} JPY`
                  : "不明"}
              </strong>
            </p>
            <p>既知小計：{shown(option.known_subtotal_jpy)} JPY</p>
            <p>
              {option.complete === true
                ? "費用項目の網羅申告あり"
                : "費用項目の網羅未確認"}
            </p>
            {Array.isArray(option.unknown_or_nonindependent_keys) &&
              option.unknown_or_nonindependent_keys.length > 0 && (
                <p>
                  未知・非独立：
                  {option.unknown_or_nonindependent_keys.map(String).join("、")}
                </p>
              )}
            {Array.isArray(option.items) &&
              option.items.filter(object).map((item, i) => (
                <div key={i} className="calculation">
                  <h4>
                    {shown(item.key)} /{" "}
                    {kindNames[shown(item.kind)] ?? shown(item.kind)}
                  </h4>
                  <p>
                    項目額：
                    {typeof item.amount_jpy === "string"
                      ? `${item.amount_jpy} JPY`
                      : "不明"}{" "}
                    /{" "}
                    {item.included_in_subtotal === true
                      ? "小計へ加算"
                      : "小計へ未加算"}
                  </p>
                  <p>
                    出典：{shown(item.source)} /{" "}
                    {item.certainty === "CONFIRMED"
                      ? "確定"
                      : item.certainty === "ESTIMATED"
                        ? "推定"
                        : "未確認"}
                  </p>
                </div>
              ))}
          </article>
        ))}
      </div>
      <CostRecoveryResult value={calculation.simple_cost_recovery} />
      <details>
        <summary>計算入力・適用期間・出典の全文</summary>
        <pre>{JSON.stringify(input, null, 2)}</pre>
      </details>
    </section>
  );
}
