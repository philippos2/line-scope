import { ComparisonInputDetails } from "./ComparisonInputDetails";
import { AlternativeAssessment } from "../investigation/AlternativeAssessment";
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
  ["known_subtotal_jpy", "登録費用の既知小計", "JPY"],
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
    return "算定できません";
  if (typeof value === "number" && Number.isFinite(value)) {
    const text = value.toLocaleString("ja-JP", { maximumFractionDigits: 20 });
    return unit === "JPY" && currency === "JPY"
      ? `¥${text}`
      : `${text}${unit ? ` ${unit}` : ""}`;
  }
  return typeof value === "string"
    ? `${value}${unit ? ` ${unit}` : ""}`
    : "詳細情報あり";
}
const safetyLabels: Record<string, string> = {
  UNKNOWN: "選択した安全条件では判断できません",
  CONDITIONAL: "条件付き",
  STOP_REQUIRED: "停止が必要",
};
const missingLabels: Record<string, string> = {
  operational_feasibility:
    "運用上の実現条件は、この評価では確認できていません。",
  residual_risk: "残るリスクは、この版では評価対象外です。",
  economic_input: "この案の費用を算定する登録入力が選択されていません。",
  maintenance_plan: "対応計画が選択されていません。",
  confirmed_continued_operation_conditions:
    "選択した条件だけでは運転を続けるための条件を確認できません。",
};
const riskLabels: Record<string, string> = {
  SAFETY: "安全",
  PRODUCTION: "生産",
  QUALITY: "品質",
  DELIVERY: "納期",
  CASCADE: "波及",
  ECONOMIC: "経済",
};

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
  economic_REPAIR: "修理の登録費用",
  economic_REPLACE: "交換の登録費用",
  economic_CONTINUE: "継続の登録費用",
  loss_rate: "停止損失率",
  repair_downtime: "修理中の生産損失",
  repair_total: "修理の総経済影響",
  capacity_shortage: "代替能力不足",
  degradation_loss: "期間中の劣化損失",
  simple_cost_recovery: "単純費用回収期間",
};

export function DecisionComparison({
  comparison,
  names: entityNames = {},
  productIds = [],
}: {
  comparison: JsonObject;
  names?: Record<string, string>;
  productIds?: string[];
}) {
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
      <section aria-label="比較で使用する費用の範囲">
        <h3>比較の費用と、調査した損害額の違い</h3>
        <p>
          ここでは選択した修理費用の停止項目を使います。接続及び影響範囲の製品別損害額とは、算定範囲が異なります。
        </p>
        {economics.loss_per_hour != null ? (
          <p>
            選択した停止費用の毎時額：
            {display(economics.loss_per_hour, "JPY", economics.currency)}／時間
          </p>
        ) : (
          <p>選択した修理費用では、毎時額を算定できません。</p>
        )}
        {economics.known_subtotal_per_hour != null && (
          <p>
            登録項目の小計：
            {display(
              economics.known_subtotal_per_hour,
              "JPY",
              economics.currency,
            )}
            ／時間（選択範囲のみ）
          </p>
        )}
      </section>
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
            {option.option === "SUBSTITUTE" ? (
              <>
                <p>
                  候補：{entityNames[String(option.equipment_id)] ?? "代替設備"}
                </p>
                <AlternativeAssessment
                  option={option}
                  candidate={
                    object(option.structural_basis) &&
                    object(option.structural_basis.candidate)
                      ? option.structural_basis.candidate
                      : undefined
                  }
                  product={
                    entityNames[String(option.product_id)] ?? "選択した製品"
                  }
                  unevaluated={productIds
                    .filter(
                      (id) =>
                        !options.some(
                          (row) =>
                            row.option === "SUBSTITUTE" &&
                            row.equipment_id === option.equipment_id &&
                            row.product_id === id,
                        ),
                    )
                    .map((id) => entityNames[id] ?? "他の到達製品")}
                />
              </>
            ) : (
              <>
                {option.total_cost == null && (
                  <p>
                    費用の総額は算定できません。登録費用と対応計画の選択内容を確認してください。
                  </p>
                )}
                <dl>
                  {fields
                    .filter(
                      ([key]) =>
                        option[key] != null && option[key] !== "UNKNOWN",
                    )
                    .map(([key, caption, unit]) => (
                      <div key={key}>
                        <dt>{caption}</dt>
                        <dd>
                          {display(option[key], unit, economics.currency)}
                        </dd>
                      </div>
                    ))}
                </dl>
                {object(option.safety_basis) && (
                  <p>
                    登録上の安全判断：
                    {option.safety_basis.status === "UNKNOWN" &&
                    (!Array.isArray(option.safety_basis.declarations) ||
                      !option.safety_basis.declarations.length)
                      ? "この設備の安全条件を選択していません。"
                      : (safetyLabels[String(option.safety_basis.status)] ??
                        "判定を取得できません")}
                  </p>
                )}
              </>
            )}
            {object(option.safety_basis) &&
              Array.isArray(option.safety_basis.declarations) &&
              option.safety_basis.declarations.filter(object).map((row, i) =>
                object(row.input) ? (
                  <details key={i}>
                    <summary>選択した安全条件と出典</summary>
                    <ComparisonInputDetails
                      record={row.input}
                      names={entityNames}
                    />
                  </details>
                ) : null,
              )}
            {Array.isArray(option.blocking_constraints) &&
              option.blocking_constraints
                .filter(object)
                .map((constraint, i) => (
                  <div className="notice" key={i}>
                    <strong>
                      {reasons[String(constraint.code)] ??
                        "この案に実行を妨げる登録条件があります。"}
                    </strong>
                    <details>
                      <summary>制約の根拠</summary>
                      <pre>{JSON.stringify(constraint, null, 2)}</pre>
                    </details>
                  </div>
                ))}
            {option.option !== "SUBSTITUTE" &&
              list(option.missing_information).length > 0 && (
                <details>
                  <summary>
                    不足情報（{list(option.missing_information).length}件）
                  </summary>
                  <ul>
                    {list(option.missing_information).map((item) => (
                      <li key={item}>
                        {missingLabels[item] ??
                          "この評価に含まれない条件があります。技術情報で原文を確認できます。"}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
          </article>
        ))}
      </div>
      {options.length === 0 && <p>比較案は取得できませんでした。</p>}
      <p>
        品質・残るリスクは、この版では評価対象外です。入力の充足や費用の大小は、運転許可を意味しません。
      </p>
      <details>
        <summary>リスクの評価範囲</summary>
        <dl>
          {Object.entries(risks).map(([key, value]) => (
            <div key={key}>
              <dt>{riskLabels[key] ?? "その他の観点"}</dt>
              <dd>
                {key === "QUALITY" && value === "UNKNOWN"
                  ? "この版では評価対象外です。"
                  : value === "UNKNOWN"
                    ? "選択した入力だけでは、リスクの高低を判定できません。"
                    : ((
                        {
                          LOW: "低い",
                          MEDIUM: "中程度",
                          HIGH: "高い",
                        } as Record<string, string>
                      )[String(value)] ?? "判定は技術情報を参照してください。")}
              </dd>
            </div>
          ))}
        </dl>
      </details>
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
            {calculationNames[String(calculation.id)] ?? "追加の計算"}：
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
        <summary>前提と評価の限界</summary>
        <p>
          選択した登録入力の範囲だけを評価しています。未選択の条件を補わず、保全費用の小計を他の費用へ自動加算しません。過去の損失から将来故障率を推測しません。
        </p>
      </details>
      <details>
        <summary>技術情報：比較データの原文</summary>
        <pre>{JSON.stringify(comparison, null, 2)}</pre>
      </details>
      <p className="notice">
        分析結果の表示です。変更準備・承認・実行は行いません。
      </p>
    </section>
  );
}
