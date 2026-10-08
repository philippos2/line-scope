# LineScope

製造業務の状況把握・依存分析・人による承認付き更新を支援するプロダクト。
仕様の正本は[19文書の成果物一覧](docs/deliverables.md)。文書レビュー履歴は[docs/history](docs/history/README.md)。

このチェックポイントはPython / FastAPI / PostgreSQLの基盤だけを含む。
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

## 起動

Python 3.12以上とPostgreSQLを用意する。検証環境はPython 3.14.4 / PostgreSQL 18.6。
以下のコマンドはリポジトリのルートで実行する。

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.lock
.venv/bin/pip install --no-deps -e ./backend
```

`LINESCOPE_DSN`へ接続先、`LINESCOPE_USERS`へサーバ側のデモ認証設定を渡す。
形式は`{"<secret-token>":{"user_id":"<user>","role":"floor|maintenance|production|manager"}}`。
実際のcredentialは環境変数または非管理の`.env`へ保管する。`.env`は自動では読み込まない。
設定例は`backend/.env.example`に置く。
空のユーザー設定では全HTTP要求が401となる。

```sh
.venv/bin/linescope migrate
.venv/bin/linescope serve
```

Bearer認証付き`GET /health`はプロセスの応答、`GET /health/ready`はPostgreSQL接続を確認する。
後者はDB利用不可時503。共通Response Envelopeを返し、接続先・credentialは返さない。
このreadinessは業務テーブルやGraphの準備完了を意味しない。

migrationはadvisory lock下の単一トランザクションでSQLを順に適用し、checksumを記録する。
再実行は適用済みをskipし、適用後のSQL改変は拒否する。初期SQLは疎通用で、業務テーブルは作成しない。

## 検証

```sh
.venv/bin/ruff check backend
.venv/bin/ruff format --check backend
.venv/bin/pytest backend/tests -q
LINESCOPE_TEST_DSN='<test PostgreSQL connection>' .venv/bin/pytest backend/tests -q
```

DBテストは明示された接続先に一時schemaを作成し、終了時にそのschemaだけを削除する。
未指定時はDBテストがskipされる。既存の業務DBでmigrationを試さず、専用の空DBを利用する。

## 次のチェックポイント

業務モデル・migration、Read Tools、Prepare / Approval / Execute、Outbox / Projection、Graph分析、RAG / Agentを機能単位で実装・テスト・commitする。
先行実装はGit stashへ退避し、レビューして必要な部分を段階的に取り込む。
stashは再構成前のパスを保持しているため、取り込むコードを`backend/`の構成へ合わせる。
LLM / embeddingの製品選定・品質評価、Docker起動、受入基準全体の検証は未完了。

サーバサイド完成後に、Palantir AIP Analystを参考にした、LogiScopeよりリッチなFrontendを構築する。
UI要件・画面設計・frameworkはそのフェーズで具体化する。現在のチェックポイントには含めない。

開発ブランチでは意味のあるチェックポイントcommitを残す。mainへは原則1 PR＝1 Squash commit、Conventional Commit形式で反映し、merge後にfeature branchを削除する。既存履歴をrewriteしない。
CIとGitHub設定の責務・required checksは[開発・PR運用](CONTRIBUTING.md)を参照する。
Backend CIは全PRで実PostgreSQLを使う`Tests and migrations`、PRタイトル規則は`PR title`で検証する。
