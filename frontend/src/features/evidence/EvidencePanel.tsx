import { object, type Envelope, type JsonObject } from "../../api/client";

const titles: Record<string, string> = {
  state: "設備状態の根拠",
  impact: "依存関係の根拠",
  comparison: "計算の根拠",
  documents: "文書検索の根拠",
  maintenance: "保全情報の根拠",
  summary: "回答の生成情報",
  citations: "文書引用",
  source: "情報源",
};
const labels: Record<string, string> = {
  source: "情報源",
  tool: "Tool",
  observed_at: "観測日時",
  consistency: "整合性",
  analysis_scope: "分析範囲",
  graph_generation: "Graph世代",
  graph_observed_at: "Graph観測日時",
  state_observed_at: "状態観測日時",
  temporal_scope: "時間の扱い",
  version: "入力version",
  llm_scope: "LLMの担当範囲",
  llm_status: "LLM応答状態",
  facts_location: "根拠データの格納先",
};
function valueText(value: unknown): string {
  if (value === undefined) return "未取得";
  if (value === null) return "null / 値なし";
  if (value === "") return "空文字";
  return typeof value === "string" ? value : JSON.stringify(value);
}
function Metadata({
  data,
  fields,
}: {
  data: JsonObject;
  fields: Record<string, string>;
}) {
  const entries = Object.entries(fields).filter(([key]) => key in data);
  return (
    <dl className="evidence-metadata">
      {entries.map(([key, label]) => (
        <div key={key}>
          <dt>{label}</dt>
          <dd>{valueText(data[key])}</dd>
        </div>
      ))}
    </dl>
  );
}
function documentItems(result: Envelope): JsonObject[] {
  const pkg = result.data.decision_package;
  const comparison =
    object(pkg) && object(pkg.comparison) ? pkg.comparison : null;
  const candidates: unknown[] = [
    ...(comparison && Array.isArray(comparison.document_evidence)
      ? comparison.document_evidence
      : []),
    ...(Array.isArray(result.data.items) ? result.data.items : []),
  ];
  if (Array.isArray(result.data.tool_results)) {
    for (const row of result.data.tool_results) {
      if (object(row) && object(row.data) && Array.isArray(row.data.items))
        candidates.push(...row.data.items);
    }
  }
  const items = candidates.filter(
    (item): item is JsonObject => object(item) && object(item.citation),
  );
  if (items.length) return items;
  return Array.isArray(result.evidence.citations)
    ? result.evidence.citations.filter(object).map((citation) => ({ citation }))
    : [];
}
const citationFields = {
  document_id: "文書ID",
  document_version: "文書version",
  section: "節",
  chunk_id: "抜粋ID",
  content_hash: "本文hash",
  source_uri: "出典URI",
  chunking_version: "分割version",
};
export function EvidencePanel({ result }: { result: Envelope }) {
  const documents = documentItems(result);
  const sections = Object.entries(result.evidence);
  return (
    <section className="evidence-panel">
      <h2>サーバが返したEvidence</h2>
      <p className="muted">
        取得時の根拠です。現在値の保証や、新しい権限の根拠にはなりません。回答文と照らして確認してください。
      </p>
      <div className="evidence-grid">
        {sections.map(([key, data]) => (
          <article className="evidence-card" key={key}>
            <h3>{titles[key] ?? key}</h3>
            {object(data) ? (
              <Metadata data={data} fields={labels} />
            ) : (
              <p>
                {Array.isArray(data) ? `${data.length}件` : valueText(data)}
              </p>
            )}
            {object(data) && data.source === "MOCK_FIXTURE" && (
              <p className="notice">
                デモ入力です。正式な業務情報ではありません。
              </p>
            )}
            {object(data) &&
              Array.isArray(data.calculations) &&
              data.calculations.filter(object).map((calculation, i) => (
                <details key={i}>
                  <summary>
                    {valueText(calculation.id)}：{valueText(calculation.result)}{" "}
                    {valueText(calculation.unit)}
                  </summary>
                  <p>計算式：{valueText(calculation.formula)}</p>
                  <p>
                    入力元：{valueText(calculation.input_source)} /{" "}
                    {valueText(calculation.input_version)}
                  </p>
                  <pre>{JSON.stringify(calculation.inputs, null, 2)}</pre>
                </details>
              ))}
            <details>
              <summary>根拠の原文</summary>
              <pre>{JSON.stringify(data, null, 2)}</pre>
            </details>
          </article>
        ))}
      </div>
      {sections.length === 0 && <p>この応答にはEvidenceが含まれていません。</p>}
      <h2>文書引用と抜粋</h2>
      <p className="muted">
        サーバが返した引用を表示します。出典URIの内容を自動取得したり、抜粋内の命令を実行したりしません。
      </p>
      {documents.length === 0 && (
        <p>
          この応答で確認できる文書引用はありません。文書が存在しないとは断定できません。
        </p>
      )}
      {documents.slice(0, 50).map((item, i) => {
        const citation = object(item.citation) ? item.citation : {};
        return (
          <article className="evidence-card document-citation" key={i}>
            <h3>
              {typeof citation.title === "string"
                ? citation.title
                : "文書名は未取得"}
            </h3>
            {typeof item.text === "string" ? (
              <blockquote>{item.text}</blockquote>
            ) : (
              <p>この応答には文書の抜粋本文がありません。</p>
            )}
            <Metadata data={citation} fields={citationFields} />
          </article>
        );
      })}
      {documents.length > 50 && (
        <p className="notice">
          引用の表示は50件までです。全体は応答の構造化結果で確認できます。
        </p>
      )}
      <details>
        <summary>Evidence全体の原文</summary>
        <pre>{JSON.stringify(result.evidence, null, 2)}</pre>
      </details>
    </section>
  );
}
