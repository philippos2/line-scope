# 生産作業の設備割当アクセスのCore移行

## 判断と範囲

PR #106 merge後main `d83a2f0`から開始。ProductionAssignmentExecuteの割当Target存在判定、設備参照FOR SHARE、割当CREATE / UPDATEの4箇所を固定Core statementへ移行する。既存は安全なparameterized Raw SQLであり、脆弱性修正とは扱わない。query-only Columnはmigration 002 / 003に合わせ、DDL / ORM / Engine / poolは導入しない。LogiScope再利用はない。

## 維持する境界

割当Target存在判定はGraph lock取得のrouting hintに限定し、Request / Approval lock後に保存Snapshot全体を検証する。Graph exclusive lock → Request / Approval lockの順序を変更しない。設備ID配列はUUID配列としてbindし、ID順FOR SHAREで存在を確認する。設備状態やactiveから新たな割当可否ルールを導入しない。空配列も有効に扱う。

CREATEは確定済みID・親・設備・期間・active・versionを保存し、created_at / updated_atに既存executed_atを使う。UPDATEはID / expected_versionを条件にeffective_to / active / version + 1 / updated_atだけを更新し、親ID・設備ID・開始時刻・created_atを変更しない。UTC文字列と無期限終了のSQL NULLの解釈を維持する。

親更新 → 割当短縮 / 無効化 → CREATE、rowcount / UniqueViolation / ForeignKeyViolationの契約変換、期間・集合・循環検証、履歴 / Outbox / Approval消費 / 完了 / Auditの原子性は既存serviceに残す。DB schema / GRANT、API / Tool、Snapshot / hash、Graph設計を変更しない。

全体のrelation / assignment観測とcurrent snapshotの固定JSONB集約は単一statementの観測境界を明確に維持できるため、parameterized Raw SQLのままとする。

## 検証

- Docker内の対象143件成功（追加2、24.48秒）。
- 追加1件は実DBでstale versionによる上書き拒否、version + 1、不変キー保持、旧versionの再使用拒否を確認。
- 追加1件は空ID配列とUUID文字列配列を扱い、別接続の設備更新がFOR SHARE保持中にtimeoutし、transaction終了後に成功することを確認。SQL文字列の表記には依存しない。
- 既存の有界 / 無期限 / 空割当 / 再利用、親集合、並行実行、Graph lock順序・timeout、段階別rollback、Outbox、承認期限、SQL Injection・権限を回帰確認。
- Docker内のruff check / format check成功（backend 132 files）。
- Docker内の全体回帰試験2,328件成功、1 skipped、1 warning（168.72秒）。

NFR-04〜06、AC-05・10〜13、T-SQL01・03〜05の対象部分を確認し、受入基準全体の完了とは扱わない。既存Starlette warningは対象外。

## 残る工程

DependencyRelationの更新・endpoint lock、Graph / Outbox・管理処理等には安全なRaw SQLが残る。通常操作をCoreへ移行し、PostgreSQL固有の処理・複雑な集約は意味と可読性に基づき例外を判断する。
