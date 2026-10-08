# 検索Read Toolsチェックポイント

2026-10-09。利用者がPR #4をmergeした後、mainを503d87bへfast-forwardし、`feat/search-read-tools`で検索機能だけを追加した。退避stash・バックアップは保持。LogiScopeのコード・構成は再利用していない。

## 対象

search_equipment、search_maintenance_plans、search_maintenance_records、search_dependency_relationsを実装し、内部Read Toolは13種になった。履歴検索・Agent HTTP API・更新・Graph・Frontendは追加していない。

検索schemaは既存の未知field拒否を継承し、UUID・typed endpoint・状態値・strict bool・page_size 1〜100を検証。filterはAND、code/ID/状態/boolは完全一致、設備nameはDB lowerによるリテラル部分一致。% / _はwildcardにならない。maintenance_plan_idの明示NULLと省略を区別し、通常参照でactive未指定ならactive/inactive双方を返す。

SQLは固定catalogとparameter化したfilter、ID keyset、page_size+1のLIMITで必要な行だけ取得。空検索も同一statementの観測時刻を返す。全件をPythonへ取り込んでからpaginationしたり全件数を返したりしない。READ COMMITTED / READ ONLYと既存のエラー秘匿を維持する。

cursorはprocess-localのランダムkeyでHMAC-SHA256署名。version・最終ID・bindingを保持し、bindingは認証user/role、Tool名、正規化filterを含む。JSON key順・UUID表記差は正規化、明示NULLは省略と区別。page_sizeは途中変更可能。署名keyを共有しない新プロセス・ReadTools instanceではINVALID_ARGUMENT。更新/承認/retry keyとは別用途。

一致方式・NULL・active・cursorの詳細をapi-tools §15へ明記し、READMEと履歴indexの実装範囲を更新した。既存の権限・業務更新・承認・Graph意味論を変更していない。v1の単一APIプロセスを前提とする技術実装判断であり、複数worker化する場合は署名key共有を別途設計する。

## 検証

Docker内Python 3.14.4 / PostgreSQL 18.6で180テスト成功（既存113 + 今回67）。コンテナ内ruff check / format成功。既存Starlette/httpx非推奨警告1件。

- AC-01 / AC-02: 検索前後の全tableが不変。
- AC-04 / T-R19: 明示filter、空集合、同一UUIDでも異なるendpoint型、page default/max、未知field・型不正・SQL風文字列を確認。
- AC-05 / T-R17: 全4ロールの通常検索、cursorの別user・別role・別Tool流用拒否、identity偽装field拒否。
- T-R19: ID順で重複なく継続、page_size変更、改ざん・filter変更・再起動拒否、key順/UUID正規化・明示NULLの拘束を確認。
- AC-04 / api-tools §18: ページ間の更新・削除を次のページで観測し、複数ページを一つの固定Snapshotとして扱わない。

重大Failの全AC達成やリリース可を意味しない。AC-17の履歴閲覧境界は履歴schemaとともに後続で実装・検証する。

## 後続

更新スキーマと履歴参照、業務ルール・canonical Snapshot、Prepare/Approval/Execute、Outbox/Projection、Graph、RAG/Agentを小さなcheckpointへ分割。Frontendはサーバサイド完了後。
