# LineScope

製造業務の状況把握・依存分析・人による承認付き更新を支援するプロダクト。
仕様の正本は[19文書の成果物一覧](docs/deliverables.md)。文書レビュー履歴は[docs/history](docs/history/README.md)。

このチェックポイントはPython / FastAPI / PostgreSQLの基盤と業務正本の10テーブルを含む。
業務API、Approval / Execute、Graph、Outbox、RAG、LLM、UIは含まない。

## ディレクトリ構成

Backend / Frontend / 仕様文書を同じGitリポジトリで管理する。

```text
line-scope/
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── src/linescope/
│   │   └── migrations/
│   └── tests/
├── frontend/           # 現在は後続開発の案内のみ
├── docs/               # 19文書と変更履歴
└── README.md
```

`backend/src/linescope`の`linescope`はPythonのimport名。Frontendはサーバサイド完成後に実装する。
Backendのpackage・依存・テスト設定は`backend/pyproject.toml`で管理する。

## Docker起動

Docker EngineとCompose v2以降を用意し、リポジトリのルートで実行する。
API・migrationはPython 3.14.4の非rootコンテナ、PostgreSQLは18.6のコンテナで動作する。

```sh
python3 scripts/create_demo_env.py
docker compose up --build -d --wait api
```

初回の資格情報生成はPython標準ライブラリだけを使用する。既存`.env`は上書きしない。
`.env`は権限600で作成され、Git・Docker build contextへ入らない。各ロール1名、manager2名のランダムtokenを保持する。
`LINESCOPE_API_PORT`でホスト側portを変更できる（既定8000、127.0.0.1のみ）。
Bearer tokenはローカル`.env`の`LINESCOPE_USERS`から取得する。credentialをPRやログへ貼らない。

PostgreSQLのhealthcheck成功後にmigrationを実行し、成功後にAPIを起動する。
APIのhealthcheckもBearer認証付きreadinessを検証する。DB portはホストへ公開しない。
DBはCompose projectの`postgres-data` volumeへ保持する（PostgreSQL 18の配置に合わせ`/var/lib/postgresql`）。

```sh
docker compose logs api
docker compose run --rm migrate
docker compose down
```

`down`はDB volumeを保持する。通常停止時に`--volumes`を付けない。
`.env`のDBパスワードを変更しても既存volume内のパスワードは自動変更されない。

`GET /health`はプロセス応答、`GET /health/ready`はPostgreSQL接続を確認する。
両方にBearer認証を要求し、DB利用不可のreadinessは503、認証なしは401。
このreadinessは業務API・Graph・RAGの準備完了を意味しない。

migrationはadvisory lock下の単一トランザクションでSQLを順に適用し、checksumを記録する。
001は疎通用、002は業務正本の10テーブル。再実行はskipし、適用後のSQL改変は拒否する。
設備状態履歴はUpdateRequestへの必須FKを含むため、更新スキーマのチェックポイントで追加する。
期間重複、混在循環、Relation参照先の存在・active、保全計画と実績の設備一致は後続の更新トランザクションで検証する。

## Docker検証

テスト用Composeは独立した設定で、デモ資格情報や永続volumeを使用しない。
テスト用PostgreSQLはtmpfs、DB portは非公開。テストは一時schemaだけを作成・削除する。

```sh
docker compose -f compose.test.yaml build tests
docker compose -f compose.test.yaml run --rm --no-deps tests ruff check backend scripts
docker compose -f compose.test.yaml run --rm --no-deps tests ruff format --check backend scripts
docker compose -f compose.test.yaml run --rm tests
docker compose -f compose.test.yaml down --volumes --remove-orphans
```

Backend CIもこの方法で全テストを実行し、実行用imageの起動・同梱migration再実行を確認する。
Runtime依存は`backend/requirements.lock`、開発依存は`backend/requirements-dev.lock`で固定する。

## ホストでの補助的な開発

Python 3.12以上での編集・軽い確認も可能。標準の実行・検証経路はDockerとする。

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.lock
.venv/bin/pip install --no-deps -e ./backend
.venv/bin/ruff check backend scripts
.venv/bin/pytest backend/tests -q
```

ホストでDBテストを行う場合は専用DBの`LINESCOPE_TEST_DSN`を指定する。未指定時はDBテストがskipされる。
ホスト起動の`LINESCOPE_DSN`・`LINESCOPE_USERS`の例は`backend/.env.example`。ホストでは`.env`を自動読込しない。

## 次のチェックポイント

業務ルール検証・Read Tools、Prepare / Approval / Execute、Outbox / Projection、Graph分析、RAG / Agentを機能単位で実装・テスト・commitする。
先行実装はGit stashへ退避し、レビューして必要な部分を段階的に取り込む。
stashは再構成前のパスを保持しているため、取り込むコードを`backend/`の構成へ合わせる。
LLM / embeddingの製品選定・品質評価、受入基準全体の検証は未完了。

サーバサイド完成後に、Palantir AIP Analystを参考にした、LogiScopeよりリッチなFrontendを構築する。
UI要件・画面設計・frameworkはそのフェーズで具体化する。現在のチェックポイントには含めない。

開発ブランチでは意味のあるチェックポイントcommitを残す。mainへは原則1 PR＝1 Squash commit、Conventional Commit形式で反映し、merge後にfeature branchを削除する。既存履歴をrewriteしない。
CIとGitHub設定の責務・required checksは[開発・PR運用](CONTRIBUTING.md)を参照する。
Backend CIは全PRで実PostgreSQLを使う`Tests and migrations`、PRタイトル規則は`PR title`で検証する。
