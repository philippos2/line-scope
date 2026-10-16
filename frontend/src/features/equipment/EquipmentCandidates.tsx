import { object, type Envelope } from "../../api/client";

export interface EquipmentCandidate {
  equipment_id: string;
  equipment_code: string;
  equipment_name: string;
}

export function EquipmentCandidates({
  result,
  disabled,
  onSelect,
}: {
  result: Envelope;
  disabled: boolean;
  onSelect: (equipment: EquipmentCandidate) => void;
}) {
  const rows = Array.isArray(result.data.tool_results)
    ? result.data.tool_results.filter(
        (row) => object(row) && row.tool === "search_equipment",
      )
    : [];
  const latest = rows.at(-1);
  if (!object(latest) || !object(latest.data)) return null;
  const data = latest.data;
  if (!Array.isArray(data.items)) return null;
  const candidates = data.items.filter(
    (item): item is EquipmentCandidate =>
      object(item) &&
      typeof item.equipment_id === "string" &&
      typeof item.equipment_code === "string" &&
      typeof item.equipment_name === "string",
  );
  return (
    <section aria-label="設備検索の候補">
      <h2>設備を選ぶ</h2>
      <p className="muted">
        直近の設備検索で取得した候補です。工場全体の一覧や現在状態ではありません。
        選択すると、この設備を調べる対象にします。
      </p>
      {candidates.length === 0 && <p>選択できる候補はありません。</p>}
      {candidates.length !== data.items.length && (
        <p className="notice">
          表示できない候補があります。構造化結果をご確認ください。
        </p>
      )}
      {candidates.map((item) => (
        <button
          key={item.equipment_id}
          className="object"
          disabled={disabled}
          onClick={() => onSelect(item)}
        >
          <strong>{item.equipment_name}</strong>
          <small>{item.equipment_code} · この設備を調べる</small>
        </button>
      ))}
      {data.next_cursor !== null && (
        <p className="notice">
          検索の続きは未取得です。設備名などで条件を絞って再検索してください。
        </p>
      )}
    </section>
  );
}
