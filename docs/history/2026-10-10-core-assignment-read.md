# 割当ReadのCore移行

## 範囲と判断

PR #95 merge後main `181d9f5`からget_operation_equipment_assignmentsをSQLAlchemy Coreへ移行する。migration 002と一致するquery-only割当宣言を追加し、親ProductionOperationへactive割当をLEFT JOINする。親version・全割当・statement_timestampを一つのSELECTで観測する。

explicit_as_ofなしは期間で絞らない。指定時はeffective_from <= as_of、effective_toがNULLまたはas_of < effective_toとして[start,end)を維持する。期間条件をJOINのONへ置き、対象割当がなくても親行を失わない。親自体がない場合は従来のTARGET_NOT_FOUND。過去時点の完全なpoint-in-time復元ではなく、現在登録された割当への時点条件であることを維持する。

追加bindはUUIDとaware datetimeでpsycopg native adaptationの範囲と判断する。Core compile結果のSQL本文とparameter辞書を分離実行し、既存のreadonly transaction・接続寿命・dict_row・JSON正規化・Evidence・例外変換を維持する。DB schema / GRANT・Tool契約を変更せず、Engine / pool / autobegin / ORMを導入しない。LogiScopeコードの再利用はない。

## 検証

- Docker内の実PostgreSQLでRead / search / SQL Injection / READ_DSN / DB role関連251件成功（追加6件）。
- readonly実UPDATE拒否を割当Toolへ拡張（1件）。
- 期間指定なし・開始境界・終了境界・割当前の空集合・UTC以外のoffset入力（5件）について独立した既存SQLと全native値を比較する。
- 同じtransactionで未commitの親version・割当version変更を観測し、接続を継続利用できることを確認する。実行1statement、全行の同一観測時刻、UUID / aware datetimeのbind分離も検証する。
- 既存の無期限・inactive除外・現在登録の変更・空割当・不存在の親・不正 / future時点拒否を回帰確認する。
- ruff check / format check成功（128 files）。
- 全体回帰2300件成功、1件skip、既存Starlette warning 1件（159.12秒）。

NFR-04、AC-01・04、T-SQL01〜03の対象Read部分と割当期間Read契約の確認であり、SQL方針全体・T-R08の更新受入全体の完了とは扱わない。既存Starlette warningと終了時logging output failed表示は別のログ改善対象。

## 次の工程

ReadToolsの全13本はCore SELECTへ移行済み。SET TRANSACTIONはreadonly境界を明示する固定PostgreSQL SQLとして維持する。Prepare / Approval / Execute、Graph / Outbox関連、migration / role設定には引き続き安全なRaw SQLが残る。

次は重要更新の棚卸しと既存lock / rollback契約を確認し、通常処理のCore化を意味を維持できる単位で進める。JSON / custom typeや更新RETURNING等へ今回のnative Read用橋渡しを無条件に展開しない。PostgreSQL固有機能は選択理由を明示して隔離する。
