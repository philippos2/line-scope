import { object, type JsonObject } from "../../api/client";

export function CostRecoveryResult({ value }: { value: unknown }) {
  if (!object(value)) return null;
  const recovery: JsonObject = value;
  return (
    <section aria-label="単純費用回収期間">
      <h3>単純費用回収期間</h3>
      <p>
        {recovery.status === "CONDITIONAL" && typeof recovery.days === "string"
          ? `${recovery.days} 日（登録条件による試算）`
          : recovery.status === "NO_RECOVERY_FROM_DECLARED_LOSS"
            ? "登録された劣化損失率が0のため回収日数は算出しません。"
            : "登録条件からは未算出です。日次稼働・損失解消の仮定・費用範囲を確認してください。"}
      </p>
      <p>
        劣化損失が全稼働時間へ適用される登録だけを計算します。両案の損益分岐や交換の推奨を意味しません。端数は日数を過小表示しないよう小数6桁で切り上げます。
      </p>
      <details>
        <summary>費用回収の入力・式・仮定・出典</summary>
        <pre>{JSON.stringify(recovery, null, 2)}</pre>
      </details>
    </section>
  );
}
