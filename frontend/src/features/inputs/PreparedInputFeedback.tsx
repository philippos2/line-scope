import { useEffect, useId, useRef, useState } from "react";
import { object, type Envelope, type JsonObject } from "../../api/client";
import { ComparisonInputDetails } from "../decision/ComparisonInputDetails";

export function usePreparedInput(body: JsonObject) {
  const [prepared, setPrepared] = useState<{
    id: string;
    serialized: string;
    response: Envelope;
  } | null>(null);
  const serialized = JSON.stringify(body);
  const statusId = useId();
  return {
    prepared,
    serialized,
    statusId,
    alreadyPrepared: prepared?.serialized === serialized,
    remember: (id: string, response: Envelope) =>
      setPrepared({ id, serialized, response }),
  };
}
type Preparation = ReturnType<typeof usePreparedInput>;

export function PrepareInputButton({
  preparation,
  busy,
  preparing = busy,
  label,
  disabledReason = "",
}: {
  preparation: Preparation;
  busy: boolean;
  preparing?: boolean;
  label: string;
  disabledReason?: string;
}) {
  const { alreadyPrepared, prepared, statusId } = preparation;
  return (
    <>
      <button
        className="primary operation-submit"
        aria-busy={preparing}
        data-state={alreadyPrepared ? "prepared" : "editing"}
        disabled={busy || Boolean(disabledReason) || alreadyPrepared}
        aria-describedby={statusId}
      >
        {preparing
          ? "変更準備中…"
          : alreadyPrepared
            ? "変更準備を作成済み"
            : label}
      </button>
      <p id={statusId} role="status">
        {preparing
          ? "変更準備を作成しています。完了するまで再送できません。"
          : busy
            ? "別の処理を実行中のため、変更準備はできません。"
            : alreadyPrepared
              ? "この内容の変更準備は作成済みです。重複して作成できません。"
              : disabledReason ||
                (prepared
                  ? "作成後に編集した内容は未保存です。"
                  : "変更準備だけでは登録値は変わりません。")}
      </p>
    </>
  );
}

export function PreparedInputNotice({
  preparation,
  label,
  onOpen,
  equipmentLabel,
}: {
  preparation: Preparation;
  label: string;
  onOpen: (id: string) => void;
  equipmentLabel?: string;
}) {
  const { prepared, alreadyPrepared } = preparation;
  const [copyNotice, setCopyNotice] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (!prepared) return;
    setCopyNotice("");
    heading.current?.focus({ preventScroll: true });
    heading.current?.scrollIntoView?.({ block: "center" });
  }, [prepared]);
  if (!prepared) return null;
  const snapshot = prepared.response.data.canonical_snapshot;
  const targets =
    object(snapshot) && Array.isArray(snapshot.targets)
      ? snapshot.targets.filter(object)
      : [];
  const records = targets.map((target) => target.after).filter(object);
  async function copy() {
    try {
      await navigator.clipboard.writeText(prepared!.id);
      setCopyNotice("変更要求IDをコピーしました。");
    } catch {
      setCopyNotice(
        "コピーできませんでした。表示された変更要求IDを選択してコピーしてください。",
      );
    }
  }
  return (
    <section
      className="operation-completion"
      aria-label={`作成済みの${label}変更要求`}
    >
      <h3 ref={heading} tabIndex={-1}>
        変更準備が完了しました
      </h3>
      <p>
        登録値はまだ変更されていません。次は別の工場管理者による承認です。変更要求IDを承認担当者へ渡してください。
      </p>
      {!alreadyPrepared && (
        <p className="notice">
          作成後の編集は、この保存内容には含まれていません。
        </p>
      )}
      <p>
        変更要求ID：<code>{prepared.id}</code>
      </p>
      <button type="button" onClick={() => void copy()}>
        変更要求IDをコピー
      </button>
      {copyNotice && <p role="status">{copyNotice}</p>}
      {records.length ? (
        <details>
          <summary>保存した内容の要約</summary>
          {records.map((record, i) => (
            <ComparisonInputDetails
              key={i}
              record={record}
              names={
                equipmentLabel
                  ? { [String(record.equipment_id)]: equipmentLabel }
                  : {}
              }
            />
          ))}
        </details>
      ) : (
        <p>保存内容は「保存内容を確認・承認へ進む」から確認できます。</p>
      )}
      <button
        className="primary"
        type="button"
        onClick={() => onOpen(prepared.id)}
      >
        保存内容を確認・承認へ進む
      </button>
    </section>
  );
}
