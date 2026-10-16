import { DecisionAssessments } from "./DecisionAssessments";
import { object, type JsonObject } from "../../api/client";

const names: Record<string, string> = {
  REPAIR: "修理",
  REPLACE: "交換",
  CONTINUE: "継続使用",
  SUBSTITUTE: "代替設備",
  INTERIM: "暫定対応",
};
const fields: [string, string, string][] = [
  ["lead_time_hours", "調達待ち", "時間"],
  ["downtime_hours", "停止時間", "時間"],
  ["known_subtotal_jpy", "経済入力の既知小計", "JPY"],
  ["plan_cost_subtotal_jpy", "計画直接費の小計（合算しない）", "JPY"],
  ["required_rate", "必要能力", "毎時"],
  ["available_rate", "利用可能能力", "毎時"],
  ["shortage_rate", "能力不足", "毎時"],
  ["quantity_unit", "能力の数量単位", ""],
  ["recovery_deadline", "条件付き復旧期限", ""],
  ["interim_until", "暫定終了", ""],
  ["direct_cost", "直接費用", "JPY"],
  ["duration_hours", "作業時間", "時間"],
  ["lead_time_days", "調達期間", "日"],
  ["production_loss", "停止中の生産損失", "JPY"],
  ["total_cost", "総経済影響", "JPY"],
  ["required_units_per_hour", "必要能力", "units/hour"],
  ["available_units_per_hour", "利用可能能力", "units/hour"],
  ["shortage_units_per_hour", "能力不足", "units/hour"],
  ["days_until_update", "次回更新まで", "日"],
  ["cumulative_degradation_loss", "期間中の劣化損失", "JPY"],
];
function display(value: unknown, unit = "", currency: unknown = "JPY") {
  if (value === null || value === undefined || value === "UNKNOWN")
    return "未確認";
  if (typeof value === "number" && Number.isFinite(value)) {
    const text = value.toLocaleString("ja-JP", { maximumFractionDigits: 20 });
    return unit === "JPY" && currency === "JPY"
      ? `¥${text}`
      : `${text}${unit ? ` ${unit}` : ""}`;
  }
  return typeof value === "string"
    ? `${value}${unit ? ` ${unit}` : ""}`
    : JSON.stringify(value);
}
function list(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}
const reasons: Record<string, string> = {
  STRUCTURAL_SUBSTITUTION_UNAVAILABLE: "登録済みの一段代替構造を満たしません",
  CURRENT_EQUIPMENT_UNAVAILABLE: "現在の設備状態では使用できません",
  PRODUCT_INCOMPATIBLE: "登録された製品互換性を満たしません",
  HARD_SAFETY_STOP: "登録された安全停止条件に該当します",
  INSUFFICIENT_CAPACITY_FOR_FULL_ABSORPTION:
    "必要能力を完全には吸収できません。部分的な緩和の可否は別途判断が必要です",
};
const calculationNames: Record<string, string> = {
  economic_REPAIR: "修理の経済入力",
  economic_REPLACE: "交換の経済入力",
  economic_CONTINUE: "継続の経済入力",
  loss_rate: "停止損失率",
  repair_downtime: "修理中の生産損失",
  repair_total: "修理の総経済影響",
  capacity_shortage: "代替能力不足",
  degradation_loss: "期間中の劣化損失",
  simple_cost_recovery: "単純費用回収期間",
};

export function DecisionComparison({ comparison }: { comparison: JsonObject }) {
  const economics = object(comparison.economics) ? comparison.economics : {};
  const options = Array.isArray(comparison.options)
    ? comparison.options.filter(object)
    : [];
  const calculations = Array.isArray(comparison.calculations)
    ? comparison.calculations.filter(object)
    : [];
  const risks = object(comparison.risk) ? comparison.risk : {};
  return (
    <section className="decision">
      <h2>対応案を比較する</h2>
      <p className="muted">
        選択した入力と共通期間の比較です。費用の大小だけで案の優劣や実行可否を確定しません。
      </p>
      <div className="metrics">
        <div>
          仮想停止の損失率
          <strong>
            {display(economics.loss_per_hour, "JPY", economics.currency)} / hour
          </strong>
        </div>
        <div>
          判明分の小計
          <strong>
            {display(
              economics.known_subtotal_per_hour,
              "JPY",
              economics.currency,
            )}{" "}
            / hour
          </strong>
        </div>
        <div>
          経済データ
          <strong>
            {economics.complete === true
              ? "登録入力内で算出可能"
              : "不完全 / 未確認"}
          </strong>
        </div>
      </div>
      <div className="option-grid">
        {options.map((option, index) => (
          <article
            className="option-card"
            key={`${String(option.option)}-${index}`}
          >
            <div className="title">
              <h3>
                {names[String(option.option)] ??
                  String(option.option ?? "名称未確認")}
              </h3>
              <span className="badge warning">
                {option.feasibility === "INFEASIBLE"
                  ? "候補から除外"
                  : option.feasibility === "FEASIBLE"
                    ? "条件内で実行可能"
                    : "実行可否は未確認"}
              </span>
            </div>
            {typeof option.equipment_code === "string" && (
              <p>{option.equipment_code}</p>
            )}
            <dl>
              {fields
                .filter(([key]) => key in option)
                .map(([key, caption, unit]) => (
                  <div key={key}>
                    <dt>{caption}</dt>
                    <dd>{display(option[key], unit, economics.currency)}</dd>
                  </div>
                ))}
            </dl>
            {object(option.safety_basis) && (
              <details>
                <summary>
                  登録上の安全判断：{String(option.safety_basis.status)}
                  （選択入力の範囲）
                </summary>
                <pre>{JSON.stringify(option.safety_basis, null, 2)}</pre>
              </details>
            )}
            {object(option.condition_assessment) && (
              <details open>
                <summary>代替の条件別確認</summary>
                <dl>
                  <div>
                    <dt>構造候補</dt>
                    <dd>{String(option.condition_assessment.structure)}</dd>
                  </div>
                  <div>
                    <dt>能力</dt>
                    <dd>{String(option.condition_assessment.capacity)}</dd>
                  </div>
                  <div>
                    <dt>登録上の安全判断</dt>
                    <dd>{String(option.condition_assessment.safety)}</dd>
                  </div>
                  <div>
                    <dt>品質</dt>
                    <dd>{String(option.condition_assessment.quality)}</dd>
                  </div>
                </dl>
                <p>実運転許可は認定していません。</p>
                <details>
                  <summary>構造候補の根拠</summary>
                  <pre>{JSON.stringify(option.structural_basis, null, 2)}</pre>
                </details>
              </details>
            )}
            <p className="muted">残存リスク：{display(option.residual_risk)}</p>
            {Array.isArray(option.blocking_constraints) &&
              option.blocking_constraints
                .filter(object)
                .map((constraint, i) => (
                  <div className="notice" key={i}>
                    <strong>
                      {reasons[String(constraint.code)] ??
                        String(constraint.code ?? "制約の詳細は未確認")}
                    </strong>
                    <details>
                      <summary>制約の根拠</summary>
                      <pre>{JSON.stringify(constraint, null, 2)}</pre>
                    </details>
                  </div>
                ))}
            {list(option.missing_information).length > 0 && (
              <details>
                <summary>
                  不足情報（{list(option.missing_information).length}件）
                </summary>
                <ul>
                  {list(option.missing_information).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </details>
            )}
          </article>
        ))}
      </div>
      {options.length === 0 && <p>比較案は取得できませんでした。</p>}
      <h2>リスクの評価状態</h2>
      <dl className="risk-grid">
        {Object.entries(risks).map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>
              {display(value)}
              {object(comparison.risk_details) &&
                object(comparison.risk_details[key]) && (
                  <details>
                    <summary>確認した事実と不足情報</summary>
                    <pre>
                      {JSON.stringify(comparison.risk_details[key], null, 2)}
                    </pre>
                  </details>
                )}
            </dd>
          </div>
        ))}
      </dl>
      {object(comparison.cost_comparison) && (
        <DecisionAssessments comparison={comparison} />
      )}
      <h2>計算の根拠</h2>
      <p className="muted">
        サーバが返した入力・計算式・結果です。調達期間は停止時間と同じではありません。
      </p>
      {calculations.map((calculation, i) => (
        <details className="calculation" key={i}>
          <summary>
            {calculationNames[String(calculation.id)] ?? String(calculation.id)}
            ：
            {display(
              calculation.result,
              typeof calculation.unit === "string" ? calculation.unit : "",
              economics.currency,
            )}
            {calculation.complete !== true ? " / 未完了" : ""}
          </summary>
          <p>
            入力元：{display(calculation.input_source)} /{" "}
            {display(calculation.input_version)}
          </p>
          <p>計算式：{display(calculation.formula)}</p>
          <pre>{JSON.stringify(calculation.inputs, null, 2)}</pre>
        </details>
      ))}
      <details>
        <summary>前提・未確定事項</summary>
        <ul>
          {list(comparison.unknowns).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
      <details>
        <summary>比較データの原文</summary>
        <pre>{JSON.stringify(comparison, null, 2)}</pre>
      </details>
      <p className="notice">
        分析結果の表示です。変更準備・承認・実行は行いません。
      </p>
    </section>
  );
}
