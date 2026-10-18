import { object, type Envelope, type JsonObject } from "../../api/client";
import { label, node, type NodeRef } from "./model";

const reasons: Record<string, string> = {
  CYCLIC_REQUIREMENTS: "必須依存に循環があるため判定不明",
  INCOMPLETE_SEARCH: "探索不完全",
  UNKNOWN_AVAILABILITY: "利用可能性が未確認",
  BASELINE_NOT_ESTABLISHED: "除外前の構造成立を確認できない",
  NOT_MANDATORY_UPSTREAM: "この対象の必須上流ではない",
  EXCLUDED_DEPENDENCY: "除外対象への依存が残る",
  UNAVAILABLE_DEPENDENCY: "利用不可の依存先がある",
};
const verdicts: Record<string, string> = {
  ESTABLISHED: "構造成立",
  NOT_ESTABLISHED: "構造不成立",
  INDETERMINATE: "判定不明",
  CANDIDATE: "単一障害点候補",
  NOT_CANDIDATE: "この条件では候補外",
  AVAILABLE: "構造上利用可能",
  UNAVAILABLE: "利用不可",
  UNKNOWN: "不明",
};
export function GraphFindings({
  data,
  result,
  onSelect,
}: {
  data: JsonObject;
  result: Envelope;
  onSelect: (item: NodeRef) => void;
}) {
  const name = (value: unknown) =>
    node(value) ? (
      <button className="path-node" onClick={() => onSelect(value)}>
        {label(result, value)}
      </button>
    ) : (
      "対象未確認"
    );
  const verdict = (value: unknown) =>
    typeof value === "string" ? (verdicts[value] ?? "未確認") : "未確認";
  return (
    <section aria-label="対象別の構造判定" className="graph-findings">
      {Array.isArray(data.common_candidates) && (
        <>
          <h2>共通する上流依存先</h2>
          {data.common_candidates.length ? (
            <ul>
              {data.common_candidates.map((item, i) => (
                <li key={i}>{name(item)}</li>
              ))}
            </ul>
          ) : (
            <p>
              {data.complete === true
                ? "指定範囲で共通依存先は取得されませんでした。"
                : "探索不完全のため、共通依存なしとは判断できません。"}
            </p>
          )}
          <p className="muted">
            上流への到達が共通する候補です。故障原因や単一障害点の認定ではありません。
          </p>
        </>
      )}
      {Array.isArray(data.target_results) && (
        <>
          <h2>除外前後の構造</h2>
          <ul>
            {data.target_results.filter(object).map((row, i) => (
              <li key={i}>
                {name(row.important_target)}：除外前{" "}
                {verdict(object(row.before) ? row.before.determination : null)}{" "}
                → 除外後{" "}
                {verdict(object(row.after) ? row.after.determination : null)}
              </li>
            ))}
          </ul>
        </>
      )}
      {Array.isArray(data.alternatives) && (
        <>
          <h3>一段代替の候補</h3>
          <ul>
            {data.alternatives.filter(object).map((row, i) => (
              <li key={i}>
                {name(row.excluded_node)}：{verdict(row.availability)}
                {Array.isArray(row.candidates) && (
                  <ul>
                    {row.candidates.filter(object).map((candidate, n) => (
                      <li key={n}>
                        {name(candidate.candidate ?? candidate)}：
                        {verdict(candidate.availability)}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {Array.isArray(data.findings) && (
        <>
          <h2>重要対象ごとの単一障害点候補</h2>
          {data.findings.length ? (
            <ul>
              {data.findings.filter(object).map((row, i) => (
                <li key={i}>
                  {name(row.important_target)} ／ 候補 {name(row.candidate)}：
                  {verdict(row.determination)}
                  {Array.isArray(row.reasons) && (
                    <p className="muted">
                      {row.reasons
                        .filter((value) => typeof value === "string")
                        .map(
                          (value) =>
                            reasons[value as string] ?? "条件を確認できません",
                        )
                        .join(" / ")}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p>
              評価した対象と候補の組がありません。単一障害点なしとは判断できません。
            </p>
          )}
        </>
      )}
      {data.determination === "INDETERMINATE" && (
        <p className="notice">
          全体判定は未確定です。不明を「代替なし」「障害点なし」に読み替えないでください。
        </p>
      )}
    </section>
  );
}
