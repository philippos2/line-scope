# LineScope

[![Backend CI](https://github.com/philippos2/line-scope/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/philippos2/line-scope/actions/workflows/ci.yml)

**設備・工程の依存関係と根拠をつなぎ、製造現場の意思決定を支援する単一工場のデモ。**

「M-204で異常が起きた。どこまで影響する？ 修理・交換・代替ではどう違う？」という問いに、業務Object、依存Graph、文書、決定論的計算を組み合わせて判断材料を提示します。最終判断・承認・実行はエンドユーザーが行います。

> バックエンド開発中です。実APIから影響調査、仮置き入力による比較、Prepare→Approval→Execute、更新後確認まで接続しています。実Embedding/Qdrant検索とローカルLLMにも疎通済みです。費用・能力・安全条件にはモックが残り、一般LLMの説明品質と正式な業務受入は未完了です。Frontend・紹介動画は後続です。

## 主な機能と検証対象

| 領域 | 現在できること |
|---|---|
| 業務Object | 設備・状態・保全・工程・生産作業・製品・インフラ・依存関係を認可付きで参照 |
| Graph調査 | 下流影響・上流依存・共通依存・一段代替・SPOF候補を探索。経路、完全性、未評価項目を提示 |
| 判断材料の比較 | 影響候補と現在状態、仮置き費用・能力・対応案、保全根拠、不足情報をDecision Packageへ統合 |
| 文書検索 | 実Embedding/Qdrantで検索し、PostgreSQLのactive versionと管理本文を検証して引用。版更新・再構築に対応 |
| 承認付き更新 | 設備状態・保全・生産作業・依存関係の明示的Prepare。同一カテゴリの複数Target、要求置換、Approval / Execute |
| 監査・同期 | version検証、監査・履歴・Outboxの原子性、常駐Graph Projection、Rebuild / Restore、構造化運用ログ |

Graph上の到達や一段代替の構造成立は、実際の停止・十分な能力・安全性を保証しません。不明と0、影響なしと探索不完全を区別します。

## システム構成とデータの正本

```mermaid
flowchart LR
    Curl[HTTP / curl] --> API[FastAPI / 認証]
    UI[Frontend / 後続] -.-> API
    API --> App[Application / Service]
    App --> Agent[Agent / 固定Tools]
    Agent <--> LLM[ホストのOllama]
    Agent --> Tools[Read / Graph / Prepare]
    Tools --> PG[(PostgreSQL / 業務正本)]
    Tools --> Neo4j[(Neo4j / 派生Graph)]
    App --> Comparison[決定論的比較 / 仮置き入力]
    App --> RAG[文書検索 / 正本確認]
    RAG --> PG
    RAG --> Qdrant[(Qdrant / 派生Index)]
    RAG --> Embed[ホストのEmbeddingモデル]
    PG --> Outbox[Transactional Outbox]
    Outbox --> Projection[Projection / Rebuild]
    Projection --> Neo4j
    Operator[承認者 / requester] --> API
```

Python / FastAPI / Uvicorn、SQLAlchemy Core / Psycopg 3、PostgreSQL、Neo4j、Qdrant、Ollama、Docker Composeを使用します。pgvectorは使用しません。Frontendは後続のReact / TypeScriptを想定しています。

PostgreSQLが業務データ・更新要求・承認・監査・履歴・Outboxの正本です。Neo4jとQdrantは派生データです。GraphはCURRENTの場合だけ正常利用します。LLMに任意SQL / CypherやApproval / Executeを公開しません。[アーキテクチャ](docs/design/architecture.md)

## DBスキーマ・ER図

**[業務10テーブルのER図](docs/design/data-model.md#13-適用済み業務スキーマのer図)**

設備と現在状態、保全予定・実績、工程・生産作業・複数設備割当、製品、インフラ、型付きDependencyRelationを管理します。図はSQLのFKを示し、更新要求・承認・監査などの管理テーブルは別です。多態的参照と関係の意味は[ドメインモデル](docs/requirements/domain-model.md)を参照してください。

## APIを直接呼ぶ

[起動・APIデモガイド](docs/getting-started.md)で環境とBearer tokenを準備してから実行します。

```sh
curl -sS http://127.0.0.1:8000/agent \
  -H "Authorization: Bearer $LINESCOPE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"M-204の異常について影響・修理・交換・代替を比較して"}'
```

比較には`LINESCOPE_DEMO_DECISION_MOCK=true`を明示します。LLM未設定でも比較デモは動作します。一般的な日本語調査にはOllama設定が必要です。

共通応答は`answer`、`data`、`evidence`、`warnings`、`errors`、`request_id`、`context_id`、`status`を持ちます。比較の`data.decision_package`には影響・比較・根拠・unknownsを返し、仮置き入力を`demo_only` / `MOCK_FIXTURE`で明示します。

```text
調査・Evidence確認
  → 明示的Prepare（before / afterを固定、業務値は未変更）
  → 承認者のApproval（Snapshot hashを確認）
  → requesterのExecute（version再検証、更新・監査・Outboxを確定）
```

承認は成立後30分で期限切れになります。複数Targetは全体を一つのTransactionで扱います。確定after Snapshotと、その後の現在値は別です。承認・実行のcurl例は[ガイド](docs/getting-started.md#apiを直接呼ぶ)、再送・状態遷移・error codeは[API / Tool契約](docs/implementation-design/api-tools.md)を参照してください。

## デモシナリオ

| シナリオ | 確認する振る舞い |
|---|---|
| 最小業務経路 | 影響・仮置き比較→Prepare→承認前拒否→Approval→Execute→再送→更新後確認 |
| 複数設備の変更 | 同一要求に複数Targetを含め、要求置換・承認・一括更新を確認 |
| 文書と根拠 | 実Embedding/Qdrant検索、active version、引用、版更新、alias再構築 |
| 日本語の比較要約 | 実LLMは表示順だけを選択。サーバ側で数値・制約・不明事項を説明 |

```sh
python3 scripts/verify_minimal_flow.py
```

専用Compose環境で最小シナリオを実行し、終了時にその環境を削除します。通常の`.env`・volumeは共有しません。実モデルを含む4経路の一括検証と受入JSONの保存は[ガイド](docs/getting-started.md#実モデルを含む一括デモ受入)を参照してください。

最重要の業務目標は、影響・リスク・経済影響・対応策・制約・Evidence・Unknownsを比較可能に示すことです。固定デモのPASSと、[全Business Scenario](docs/implementation-design/business-scenarios.md)・Goldenの正式受入は区別します。

## セットアップ・データ準備・起動

[起動・APIデモガイド](docs/getting-started.md)に、clone、資格情報生成、migration、データ投入、Graph構築、Ollama設定、比較デモ、curl操作、停止手順をまとめています。

通常起動は`compose.yaml`、実Vector経路の追加構成は`compose.rag.yaml`です。API / migration / Projectionはコンテナで実行し、LLM / EmbeddingはホストのOllamaへ接続します。モデルは自動取得しません。

## テスト

独立した使い捨てPostgreSQL / Neo4jを使用し、通常環境の資格情報・volumeを共有しません。

```sh
docker compose -f compose.test.yaml build tests
docker compose -f compose.test.yaml run --rm --no-deps tests ruff check backend scripts
docker compose -f compose.test.yaml run --rm --no-deps tests ruff format --check backend scripts
docker compose -f compose.test.yaml run --rm tests
docker compose -f compose.test.yaml down --volumes --remove-orphans
```

CIはDockerビルド、Ruff、実DBテストを2 shardで並列実行し、runtime起動とmigrationも確認します。Fake LLMによる制御テストと実モデルの品質評価は別です。実LLM / Embedding試験はopt-inで、通常CIへ必須化していません。[テスト計画](docs/implementation-design/test-plan.md)

## 制限とスコープ外

- 費用・能力・安全・対応策には仮置き入力が残ります。正式な業務規則の未決事項をデモfixtureで補完しません。
- 自由な日本語回答の品質、根拠のない故障原因推定、全Business Scenarioの合格は保証していません。
- 過去時点分析は現在登録情報の期間評価であり、当時の状態を完全復元しません。
- Frontend・紹介動画は後続です。
- AIの自律的な最終判断・Approval / Execute、実設備制御、本番MES / ERP接続、複数工場・マルチテナントは対象外です。
- 材料・在庫・調達を含むSupply Chain Operational Intelligence、在庫・受注・BOMの完全管理はv1の対象外です。与えられた設備・工程の停止状態からの影響分析とは区別します。

範囲の正本は[要件定義](docs/requirements/requirements.md)、到達点と残作業は[ロードマップ](docs/roadmap.md)です。

## リポジトリ構成

```text
line-scope/
├── backend/
│   ├── src/linescope/  # interfaces / application / domain / persistence / graph / agent / integrations
│   └── tests/         # 対応する責務単位のテスト
├── frontend/          # 後続UIの方針文書
├── docs/              # ガイド・要件・設計・実装設計・履歴
├── scripts/           # 資格情報生成・デモ疎通・受入検証
├── .agents/skills/    # 開発・レビュー・検証手順
├── compose.yaml
├── compose.rag.yaml
└── compose.test.yaml
```

## 設計・検証資料

- [文書入口・各事項の正本](docs/deliverables.md)
- [Use Case](docs/requirements/use-cases.md)・[受入基準](docs/requirements/acceptance-criteria.md)
- [API / Tool契約](docs/implementation-design/api-tools.md)・[Transaction / Outbox / 同期](docs/implementation-design/transaction-design.md)
- [運用・ログ設計](docs/implementation-design/operations.md)・[変更・検証履歴](docs/history/README.md)
- [開発ガイダンス](AGENTS.md)・[開発・PR運用](CONTRIBUTING.md)

開発用SkillはCoding Agentの作業手順であり、LineScope実行時のAgent機能とは別です。
