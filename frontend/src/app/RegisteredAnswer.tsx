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
  const definitions = Array.isArray(sections.definitions)
    ? sections.definitions.filter(object)
    : [];
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
      {definitions.length > 0 && (
        <section aria-label="用語の説明">
          <h3>用語の説明</h3>
          {definitions.map((item, index) => (
            <p key={index}>
              {typeof item.text === "string"
                ? item.text
                : "説明を取得できません。"}
            </p>
          ))}
          <p>LineScopeの参照範囲の定義です。設備の現在値ではありません。</p>
        </section>
      )}
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
        <summary>
          {facts.length > 0 ? "回答に使った情報" : "質問の処理情報"}
        </summary>
        {facts.length > 0 ? (
          <p>
            登録情報から確認できた内容を表示しています。実際の稼働や運転許可を保証するものではありません。
          </p>
        ) : (
          <p>回答として示せる登録情報は取得・確認できていません。</p>
        )}
        {scope.length > 0 && <p>質問の読み取り：{scope.join("、")}</p>}
      </details>
    </div>
  );
}
