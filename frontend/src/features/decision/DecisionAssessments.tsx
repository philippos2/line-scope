import { CostRecoveryResult } from "../economics/CostRecoveryResult";
import { object, type JsonObject } from "../../api/client";

const names: Record<string, string> = {
  REPAIR: "修理",
  REPLACE: "交換",
  CONTINUE: "継続",
  INTERIM: "暫定対応",
  SUBSTITUTE: "代替",
};
export function DecisionAssessments({
  comparison,
}: {
  comparison: JsonObject;
}) {
  const costs = object(comparison.cost_comparison)
    ? comparison.cost_comparison
    : {};
  const pairs = Array.isArray(costs.pairs) ? costs.pairs.filter(object) : [];
  const history = Array.isArray(comparison.history)
    ? comparison.history.filter(object)
    : [];
  return (
    <>
      <CostRecoveryResult value={comparison.simple_cost_recovery} />
      <section aria-label="登録費用差">
        <h2>登録費用差</h2>
        <p>
          選択した共通期間・費用範囲の比較です。安全条件・実行可否・未登録費用は別途確認します。
        </p>
        {pairs.length === 0 && (
          <p>総額を計算できる案が不足しています。費用の優劣は未確認です。</p>
        )}
        <ul>
          {pairs.map((row, i) => (
            <li key={i}>
              {names[String(row.left)] ?? String(row.left)} −{" "}
              {names[String(row.right)] ?? String(row.right)}：
              {String(row.left_minus_right_jpy)} JPY。 登録費用が低い案：
              {row.lower_cost === "TIE"
                ? "同額"
                : (names[String(row.lower_cost)] ?? String(row.lower_cost))}
              。
              {Array.isArray(row.excluded_from_execution) &&
                row.excluded_from_execution.length > 0 &&
                "実行候補から除外された案を含みます。制約を確認してください。"}
            </li>
          ))}
        </ul>
        <details>
          <summary>費用差の範囲・未算出の案</summary>
          <pre>{JSON.stringify(costs, null, 2)}</pre>
        </details>
      </section>
      <section aria-label="選択した故障・修理履歴">
        <h2>選択した故障・修理履歴</h2>
        <p>過去損失は将来案の費用へ加算せず、将来故障率も推測しません。</p>
        {history.length === 0 && (
          <p>履歴は未選択です。故障履歴なしとは判断しません。</p>
        )}
        {history.map((row, i) => (
          <details key={i}>
            <summary>
              {object(row.input) ? String(row.input.input_code) : "選択履歴"}
            </summary>
            <pre>{JSON.stringify(row, null, 2)}</pre>
          </details>
        ))}
      </section>
    </>
  );
}
