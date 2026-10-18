import { object, type JsonObject } from "../../api/client";

export function availabilityLabel(value: unknown) {
  return value === "AVAILABLE"
    ? "利用可能"
    : value === "UNAVAILABLE"
      ? "利用不可"
      : "不明";
}
export function availabilityReason(candidate: JsonObject | undefined) {
  if (candidate?.reason === "UNAVAILABLE_DEPENDENCY")
    return "設備自身または必須の依存先を利用できません。";
  if (candidate?.reason === "EXCLUDED_DEPENDENCY")
    return "除外した設備への依存が残っています。";
  if (candidate?.reason === "UNKNOWN_AVAILABILITY")
    return "設備自身または必須の依存先の利用可否を確認できません。";
  return candidate?.availability === "UNAVAILABLE"
    ? "利用条件を満たさないため、代替案として提案しません。"
    : "利用できるか確認が必要です。";
}
function assessmentLabel(value: unknown) {
  const labels: Record<string, string> = {
    UNKNOWN: "未確認",
    STOP_REQUIRED: "停止が必要",
    CONDITIONAL: "条件付き",
    SUFFICIENT: "充足",
    INSUFFICIENT: "不足",
    NOT_REGISTERED: "未登録",
    LOW: "低い",
    MEDIUM: "中程度",
    HIGH: "高い",
  };
  return labels[String(value)] ?? "判定を確認できません";
}
const missingLabels: Record<string, string> = {
  economic_input: "代替案の費用データ",
  confirmed_continued_operation_conditions: "運転継続の確認条件",
  operational_feasibility: "運用上の実現条件",
  residual_risk: "残るリスク",
  structural_substitution: "代替候補の利用条件",
  operational_safety: "運転時の安全条件",
};
export function AlternativeAssessment({
  option,
  candidate,
  product,
  unevaluated,
}: {
  option: JsonObject;
  candidate?: JsonObject;
  product: string;
  unevaluated: string[];
}) {
  const basis = object(option.structural_basis) ? option.structural_basis : {};
  const assessment = object(option.condition_assessment)
    ? option.condition_assessment
    : {};
  const available =
    candidate?.availability === "AVAILABLE" && basis.status === "AVAILABLE";
  const unavailable =
    candidate?.availability === "UNAVAILABLE" ||
    basis.status === "UNAVAILABLE" ||
    basis.status === "NOT_REGISTERED";
  const availability = unavailable
    ? "UNAVAILABLE"
    : available
      ? "AVAILABLE"
      : "UNKNOWN";
  const structure = object(candidate?.structure) ? candidate.structure : {};
  const missing = Array.isArray(option.missing_information)
    ? option.missing_information
    : [];
  const max = Math.max(
    Number(option.required_rate) || 0,
    Number(option.available_rate) || 0,
    1,
  );
  return (
    <article
      className={`capacity-assessment ${available ? "available-proposal" : "unconfirmed-candidate"}`}
      aria-label={available ? "候補の能力評価" : "提案対象外の候補"}
    >
      <h3>
        {available
          ? `${product}は、${option.capacity_status === "SUFFICIENT" ? "能力面で吸収できる見込み" : option.capacity_status === "INSUFFICIENT" ? "能力が不足しています" : "能力条件を確認できません"}`
          : unavailable
            ? "利用できないため提案しない候補"
            : "利用できるか確認できない候補"}
      </h3>
      {!available && <p>{availabilityReason(candidate)}</p>}
      {unevaluated.length > 0 && (
        <p>
          今回選択した能力入力では{unevaluated.join("、")}を評価していません。
        </p>
      )}
      <div className="capacity-bars">
        {[
          ["必要能力", option.required_rate],
          ["空き能力", option.available_rate],
        ].map(([name, value]) => (
          <label key={String(name)}>
            {String(name)}：{String(value ?? "不明")}{" "}
            {String(option.quantity_unit ?? "")}／時間
            {value != null && Number.isFinite(Number(value)) && (
              <progress max={max} value={Number(value)} />
            )}
          </label>
        ))}
      </div>
      <dl>
        <dt>構造上の代替</dt>
        <dd>
          {structure.determination === "ESTABLISHED"
            ? "成立"
            : structure.determination === "NOT_ESTABLISHED"
              ? "不成立"
              : "未確認"}
        </dd>
        <dt>利用可能性</dt>
        <dd>{availabilityLabel(availability)}</dd>
        <dt>能力（{product}）</dt>
        <dd>{assessmentLabel(option.capacity_status)}</dd>
        <dt>安全</dt>
        <dd>{assessmentLabel(assessment.safety)}</dd>
        <dt>品質</dt>
        <dd>{assessmentLabel(assessment.quality)}</dd>
        <dt>残るリスク</dt>
        <dd>{assessmentLabel(option.residual_risk)}</dd>
      </dl>
      <p className="muted">
        利用可能性と能力の評価は、運転許可を意味しません。
      </p>
      <details>
        <summary>判定の出典と条件</summary>
        <ul>
          {missing.map((value, i) => (
            <li key={i}>
              {missingLabels[String(value)] ?? "追加の確認条件"}
              を確認してください。
            </li>
          ))}
        </ul>
        <p>
          {assessment.operational_permission === false
            ? "この評価は運転許可を出していません。"
            : "運転許可は別途確認してください。"}
        </p>
        <details>
          <summary>技術情報</summary>
          <pre>{JSON.stringify({ option, candidate }, null, 2)}</pre>
        </details>
      </details>
    </article>
  );
}
