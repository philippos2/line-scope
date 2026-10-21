import { object, type Envelope } from "../api/client";

export function RegisteredAnswer({ response }: { response: Envelope }) {
  const sections = response.data.answer_sections;
  if (!object(sections) || sections.version !== 1) {
    return (
      <div>
        <p className="notice">
          AIが生成した回答です。登録情報にない内容を含む場合があります。
        </p>
        <p className="answer">{response.answer}</p>
      </div>
    );
  }
  const facts = Array.isArray(sections.facts)
    ? sections.facts.filter(object)
    : [];
  const unavailable = Array.isArray(sections.unavailable)
    ? sections.unavailable.filter(object)
    : [];
  const scope = Array.isArray(sections.scope)
    ? sections.scope.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  const sources = Array.isArray(response.data.tool_results)
    ? response.data.tool_results.filter(object)
    : [];
  return (
    <div className="registered-answer">
      {facts.length > 0 && (
        <section aria-label="確認できたこと">
          <h3>確認できたこと</h3>
          <ul>
            {facts.map((fact, index) => {
              const references = Array.isArray(fact.references)
                ? fact.references.filter(
                    (value): value is string => typeof value === "string",
                  )
                : [];
              const referenced = sources.filter((source) =>
                references.includes(String(source.tool_call_id)),
              );
              return (
                <li key={String(fact.id ?? index)}>
                  <p>
                    {typeof fact.text === "string"
                      ? fact.text
                      : "表示形式を確認できません。"}
                  </p>
                  <details>
                    <summary>この情報の根拠</summary>
                    <p>
                      今回の参照で取得した登録情報です。実際の稼働や運転許可を保証するものではありません。
                    </p>
                    <details>
                      <summary>技術情報：取得結果</summary>
                      <pre>{JSON.stringify(referenced, null, 2)}</pre>
                    </details>
                  </details>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {unavailable.length > 0 && (
        <section aria-label="確認できない事項">
          <h3>確認できない事項</h3>
          <ul>
            {unavailable.map((item, index) => (
              <li key={index}>
                {typeof item.text === "string"
                  ? item.text
                  : "取得状態を確認できません。"}
              </li>
            ))}
          </ul>
        </section>
      )}
      <details>
        <summary>回答に使った情報</summary>
        <p>
          登録情報から確認できた内容を表示しています。実際の稼働や運転許可を保証するものではありません。
        </p>
        {scope.length > 0 && <p>質問の読み取り：{scope.join("、")}</p>}
      </details>
    </div>
  );
}
