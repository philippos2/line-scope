# Docker実行基盤チェックポイント

2026-10-09。利用者がPR #2をmergeした後、ローカルmainをc02aca1へfast-forwardし、`chore/container-runtime`で実行・検証基盤だけを追加した。退避済みstashとローカル旧ブランチは保持した。

## 対象と理由

ホストvenvで確認していたBackendをDockerで起動・検証する。業務APIやFrontendの実装を同時に追加しない。LogiScopeのコード・構成を再利用していない。

- backend/Dockerfile: Python 3.14.4、wheel化してSQL migrationを同梱、runtime/testを分離、UID/GID 10001で実行。
- requirements.lock: runtime依存を既存dev lockと同じversionに固定。pytest・ruff等はtest imageへだけ追加。
- compose.yaml: PostgreSQL 18.6 → migration成功 → API起動。PostgreSQLを永続volumeへ保存、APIのみ127.0.0.1へ公開。
- compose.test.yaml: 独立project、tmpfs PostgreSQL、ホストport・デモvolumeを共有しない。
- create_demo_env.py: 各ロール1名・manager2名のランダム資格情報をGit管理外.envへ権限600で新規生成。既存ファイル上書き・secret表示をしない。
- container_health.py: 認証付きreadiness。credentialや例外本文を出力しない。
- .dockerignore: Backendと必要scriptのみbuild contextへ含め、.env・Git・Frontend・backup等は含めない。
- Backend CI: Docker内lint/format/全テスト、runtime起動・CLI・migration再実行へ変更。required job名「Tests and migrations」を維持。PR title workflow・GitHub branch protection設定は変更なし。

## 検証

実Docker Engine / Composeでimageをbuildし、Python 3.14.4 / PostgreSQL 18.6のコンテナ内で45テスト成功。lint / format成功。既存Starlette/httpx非推奨警告1件。

runtime API UID=10001、health/readyの200、認証なし401、001/002 migrationの同梱・適用と再実行skipを確認。Composeの起動依存・認証付きhealthcheckが正常動作。初回lint時に発見したキャッシュ書込み権限問題はtest imageのキャッシュ先を/tmpへ変更して修正した。

検証専用projectのコンテナ・volumeは削除し、デモの通常停止はvolumeを保持する手順をREADMEへ明記。生成済みローカル.envはGit管理外で保持。

文書変更はREADME、CONTRIBUTING、operations §11、履歴index。operationsの過去基盤段階説明を現時点の10テーブル・Docker手順に更新し、初期Rebuild等の完成後手順は維持した。業務仕様、API/Tool、承認、権限、Graph、Outboxの責務は変更していない。

## 後続

Read Tools、更新トランザクション、Approval/Execute、Outbox/Projection、Graph、RAG/Agentを機能単位で追加する。Neo4j/Qdrant/workerのコンテナは対応機能のチェックポイントで追加。LLM/embeddingは未選定。Frontendはサーバサイド完了後。
