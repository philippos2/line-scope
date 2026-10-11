# 通常Projection workerのPostgreSQL専用role

## 範囲と判断

通常workerのPG接続用にlinescope_projectionを追加する。API runtimeの権限は拡張しない。Outbox/controlのSELECTとOutbox同期状態6列だけのUPDATEを許可し、payload・aggregate情報・業務データ・Approval・監査・controlの更新は許可しない。controller / Rebuildの権限を兼用しない。

既存の管理用provisionを拡張し、roleとGRANTはmigration lock下の一transactionで作成・再適用する。管理DDLは既存のPostgreSQL固有Raw SQL例外を維持する。passwordはbind parameter、identifierは固定allow-listまたは管理catalog由来のquoted identifierであり、通常workerのCoreクエリとtransaction境界は変更しない。

LINESCOPE_PROJECTION_PASSWORDは別の生成credentialとする。新規.env生成・既存.envの非破壊upgrade・migrateサービスだけに追加する。APIへは渡さない。不足・不正・重複passwordはmigration前に拒否する。既存環境はupgrade_demo_env.pyを実行してからComposeを起動する。業務行・volume・migration checksumは変更しない。

## 検証範囲と残課題

実LOGIN roleによるleader取得、claim、retry、lease recovery、application acknowledgmentを検証する。adapterはこの権限テストでは明示的なRecordingAdapterであり、Neo4j実接続を保証する試験とは区別する。禁止操作、未来Objectのdefault deny、再provisionでの余剰列・table権限除去も検証する。ACのleast privilege境界の部分検証であり、Graph受入全体の完了とはしない。

常駐worker CLI / Compose、Neo4j runtime credential、初期Graph生成、Rebuild / controller、heartbeatとGraph Toolは後続。LogiScopeコードは再利用していない。

## 次工程での構造整理

利用者から、backend/src/linescopeのフラット配置を責務に沿って整理すべきとの指摘があった。次工程で実際のimport依存を確認し、API入口・業務サービス・純粋な検証/計算・DBアクセス・Graph/RAG連携の境界に沿う段階的再配置を検討する。MVCという名前へ機械的に合わせず、フォルダ移動と依存境界の改善を区別する。このPRには大規模な移動を混ぜない。

検証結果: Docker内全体2,474 passed / 1 skipped / 1 warning（追加19件）。ruff check / format成功（148ファイル）。credential upgradeの追加assertは単独再実行で成功。
