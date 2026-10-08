# 2026-10-09 Backend基盤チェックポイント

利用者の指示により、一括実装を中断し、最初の実装コミットを基盤だけへ切り出した。
作業ブランチは`feat/backend-foundation`。GitHub repository・remoteはまだ作成していない。

## コミット対象

- Python package、FastAPI起動、環境設定、デモ認証の基盤。
- 認証付きhealth / PostgreSQL readiness、共通Response Envelope。
- PostgreSQL接続、Transaction、checksum付きmigration実行と再実行。
- 最小テストとREADME。既存19文書・レビュー履歴は仕様の初期ベースとして保持。

architecture.md §12にPython / FastAPI / PostgreSQL / Neo4j / Qdrantの責務と実装時期を明記。
operations.md §11にBackend基盤の起動・health・検証環境を記録した。
既存のQdrant設計を維持し、pgvectorは採用しない。UIを実装しないv1ではReactも未採用。

## 保全と未完了

先行した業務モデル・Approval / Execute・Graph・Outbox・RAG・Agent・Docker構成・デモスクリプトは、
外部archiveと`wip: preserve pre-foundation implementation`というGit stashに保全する。
この試作は完成実装ではなく、機能別のレビュー・テストを経て段階的に取り込む。
LLM / embedding model評価、運用heartbeat、Docker起動、CI、AC全体との対応・検証は未完了。

## 基盤検証

Python 3.14.4の別仮想環境に、このチェックポイントの依存だけをインストール。
PostgreSQL 18.6の一時schemaで疎通・並行migration・改変検出・DDL rollback・Transaction rollbackを検証。
`pytest`は16件成功・skipなし。`ruff check`と`ruff format --check`も成功。
FastAPI TestClientにはhttpxに関する非推奨警告が1件あり、テストは成功した。
業務機能・製品全体の受入完了を意味しない。
