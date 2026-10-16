import { object, type JsonObject } from "../../api/client";

export function UpstreamDependencies({ data }: { data: JsonObject }) {
  const resources = Array.isArray(data.reached_nodes)
    ? data.reached_nodes
        .filter(object)
        .filter((row) => row.entity_type === "InfrastructureResource")
    : [];
  return (
    <section aria-label="設備が依存する上流インフラ">
      <h3>設備が依存する上流インフラ</h3>
      <p>
        設備への供給・依存の経路です。設備停止による被影響対象とは区別します。資源の稼働状態・供給能力・安全性は未評価です。
      </p>
      {data.complete === true ? (
        <p>
          {resources.length
            ? `確認したインフラ資源：${resources.length}件`
            : "この探索範囲に依存インフラはありません。"}
        </p>
      ) : (
        <p className="notice">
          探索は不完全です（{String(data.limit_reason ?? "未確認")}
          ）。依存インフラなしとは判断できません。
        </p>
      )}
      <ul>
        {resources.map((row) => (
          <li key={String(row.entity_id)}>
            インフラ資源：{String(row.entity_id)}
          </li>
        ))}
      </ul>
      <details>
        <summary>上流依存の経路・探索範囲</summary>
        <pre>{JSON.stringify(data, null, 2)}</pre>
      </details>
    </section>
  );
}
