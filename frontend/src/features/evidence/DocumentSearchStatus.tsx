export type DocumentObservation = {
  equipmentId: string;
  equipmentLabel: string;
  completedAt: string;
  epoch: number;
};
export function DocumentSearchStatus({
  observation,
  executionEpoch,
}: {
  observation: DocumentObservation | null;
  executionEpoch: number;
}) {
  if (!observation)
    return <p>この検索結果の対象・検索時刻は記録されていません。</p>;
  return (
    <section aria-label="文書検索の取得状態">
      <p>検索時の対象：{observation.equipmentLabel}</p>
      <p>
        検索完了時刻：
        {new Intl.DateTimeFormat("ja-JP", {
          timeZone: "Asia/Tokyo",
          dateStyle: "short",
          timeStyle: "medium",
        }).format(new Date(observation.completedAt))}
        （日本時間）
      </p>
      {observation.epoch !== executionEpoch && (
        <p className="notice">
          更新前の検索結果です。変更の実行操作後はまだ再検索していません。最新の検索結果を見るには、関連文書を再検索してください。
        </p>
      )}
      <p>
        検索時点で得た文書抜粋です。文書自体の改訂の有無は、この表示からは判断できません。
      </p>
    </section>
  );
}
