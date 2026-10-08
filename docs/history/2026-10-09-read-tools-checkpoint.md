# ID参照Read Toolsチェックポイント

2026-10-09。利用者がPR #3をmergeした後、mainをc31c8beへfast-forwardし、`feat/read-tools`で参照機能を追加した。退避stash・旧ローカルブランチは保全。LogiScopeのコード・構成は再利用していない。

## 対象

api-tools §8・15のRead Toolから、ID参照8種とget_operation_equipment_assignmentsの計9種に限定。search系、設備状態履歴、更新履歴、Agent HTTP APIは次の単位に残した。

execution.pyにサーバ所有のExecutionContextを定義し、既存API認証middlewareが認証設定とrequest_idから生成する。LLMのschemaはContextを含めず、未知field・identity偽装引数・不正UUIDを拒否する。内部Tool呼出しは型付きContextを必須にする。

reads.pyは固定catalogのSQLをparameter化し、READ COMMITTED / READ ONLYで正本を参照。getは該当record、不存在はTARGET_NOT_FOUND。現在状態未登録をUNKNOWNとして捏造しない。ReadResultはdataとPostgreSQL出所・Tool名・観測時刻・LATEST_PER_CALLのEvidenceを返す。UUIDと日時をJSON向けに正規化する。

設備割当と親versionは一つのstatement Snapshotで取得。未指定は全active、explicit_as_ofはtimezone必須・未来拒否・半開区間評価。inactive行を過去時点指定で復活させず、CURRENT_REGISTRATION_AT_AS_OFを示す。親不存在と割当0件を区別する。

DB接続障害はDEPENDENCY_UNAVAILABLE、lock/statement timeoutはRESOURCE_BUSY、内部SQL不整合はINTERNAL_ERROR。引数・credential・内部SQLをエラー結果へ含めない。api-toolsに既存healthでも使っているDEPENDENCY_UNAVAILABLEを明記した。業務権限・承認・更新意味論は変更していない。Pydanticを直接使用するため既にlockに存在する同じversionを直接依存へ記載した。

## 検証

Docker内Python 3.14.4 / PostgreSQL 18.6で全113テスト成功（既存45 + 今回68）。コンテナ内ruff check / format成功。既存Starlette/httpx非推奨警告1件。実行用imageの起動・同梱Read Tool 9種・DB接続を確認し、検証専用projectのコンテナとvolumeを片付けた。

- AC-01 / AC-02: 全Read実行前後で全正本・migration管理表が不変。誤ったUPDATEもDBのREAD ONLY制約で拒否。
- AC-04: 全9Toolの不存在、未登録現在状態、割当0件を正しく区別。
- AC-05 / T-R17: 全4ロールの通常Readを許可。user/role偽装・Context欠落をDB接続前に拒否。API層がBodyの偽装identityより認証設定を優先。
- AC-18 / T-R08（参照側のみ）: active割当、開始含む・終了含まない・NULL無期限、ID順・親versionを返す。
- AC-04 / T-R15: 過去as_ofは現在登録情報の評価に限定し、inactiveを当時activeと推測しない。
- T-R19（内部Toolのみ）: JSON Schema・未知field・UUID・timezone・未来値、既知Tool限定、DBエラーの構造と秘匿。

更新・Graph・Outboxの受入基準全体が達成されたとは扱わない。Read Toolsは内部呼出し口だけを提供し、新しいHTTP endpointを仮設しない。

## 後続

検索Read Toolsとpagination、更新スキーマと履歴参照、Prepare/Approval/Execute、Outbox/Projection、Graph、RAG/Agentをそれぞれcheckpointに分ける。Frontendはサーバサイド完了後。今回のReadはNeo4j/Qdrant/LLMの可用性に依存しない。
