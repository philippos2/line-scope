# LineScope 運用設計・運用手順書

## 1. 監視

API / PostgreSQL / Neo4j / Qdrant / Projection worker / Outbox / Agentを監視する。

## 2. Outbox Metrics

- PENDING count
- PROCESSING count / age
- RETRYABLE count
- DEAD count
- oldest non-APPLIED age
- projection latency

## 3. Graph Sync

- rebuild flag -> REBUILDING
- DEAD > 0 またはfatal_errorあり -> ERROR
- PENDING/PROCESSING/RETRYABLE > 0 -> LAGGING
- otherwise CURRENT

outbox_id watermarkだけで判定しない。

## 4. Projection Worker

v1は単一active worker。PostgreSQL Advisory Lockでleader選出。

PROCESSING中にworkerが死んだ場合、lease timeoutを超えた行をRETRYABLEへ戻す。

## 5. DEAD

DEAD発生時:
1. Graph=ERROR
2. 後続Projection停止
3. Graph分析停止
4. 原因調査
5. データ修正またはevent修正
6. 管理操作でRETRYABLEへ戻す
7. 適用後CURRENT判定

## 6. Rebuild

Graph-affecting更新をAdvisory Lockで停止し、安全な一貫Snapshotから再構築する。

再構築中はGraph分析を停止する。

## 7. Backup / Restore

PostgreSQLを正本として最優先バックアップ。
Neo4j/Qdrantは再構築可能。

## 8. Runbook

- PostgreSQL unavailable
- Neo4j unavailable
- Qdrant unavailable
- LLM unavailable
- Graph LAGGING
- Graph ERROR
- Graph REBUILDING
- DEAD event
- advisory lock timeout
- ambiguous execute outcome

## 9. Demo Authentication

固定デモユーザーを許容するがcredentialをrepositoryへ平文保存しない。

## 10. 同期障害・設定・復旧の具体化

重大障害は正本にfatal_errorを保存する。初期未構築、generation欠損、検証不一致、worker内部整合障害を含む。Neo4j接続不可は利用時にGRAPH_UNAVAILABLEとし、原因解消・generation / version検証後だけfatal_errorを解除する。状態判定順はREBUILDING → DEAD / fatal_errorのERROR → 未処理LAGGING → CURRENT。管理操作をAgent Toolに公開しない。

Rebuildはtransaction-design §11・17のcontroller drain・世代切替手順に従う。active_generation未検証のままflagやfatal_errorを消さない。DEAD payload訂正は同じaggregate_versionの正本状態・監査履歴から復元した投影と照合し、元payload/hash・変更理由・操作者を監査に残す。最新versionの値を古いversionのpayloadとして書き込まない。業務データ修正は通常の承認付き更新経路を使う。同version不一致はmarkerを手で書き換えず原因調査・Rebuildを行う。

| 設定 | v1デモ技術既定値 |
|---|---|
| system_max_depth / nodes / paths / timeout_ms | 16 / 1000 / 1000 / 5000 |
| lock_timeout_ms / rebuild_timeout_ms | 5000 / 60000 |
| worker lease / Neo4j transaction timeout | 30秒 / 10秒 |
| Outbox最大attempt / backoff | 5回 / min(2^(attempt-1), 60)秒 |
| context TTL / Agent deadline / 最大Tool回数 | 30分 / 60秒 / 12回 |
| Read / Graph一時障害retry | 最大2回、全体deadline内 |
| RAG limit / system最大 | 5 / 20 |

全値は正の有限値、設定不正は起動拒否。通常Neo4j timeoutはleaseより短くし、Rebuildはheartbeatを更新し、leader / mutation lock取得後の専用処理として通常PROCESSING回収と競合させない。Graph lock待ち・探索・状態確認は同じtimeout予算。context TTLはcontext最終更新から30分であり、Approval成立後30分とは別の時計。技術閾値は業務上の承認30分を変更しない。

デモユーザーは各ロール1名以上、依存関係自己承認を避けるため工場管理者は2名とする。資格情報は環境secret等から注入し、LLMに渡さない。言語・Framework・LLM / embedding modelの具体製品・versionは実装開始時に、schema validation・Transaction・Tool calling対応を検証して選定・固定する。文書整合性を左右しないため今回の文書修正で製品を追加選定しない。

起動時に正本migration / seed → 初期Rebuild → Graph検証の順を守る。Qdrant ingestion完了前はRAGを有効化しない。Restore後は派生ストアを検証・再構築し、空OutboxだけでCURRENTにしない。

Restore等でactive_generationが存在せず未処理Outboxが残る場合、controllerはdrain開始前に正本から作業用generationを一貫Snapshotで構築・検証し、REBUILDINGのまま適用先として設定する。新規Graph-affecting更新は排他lockで停止しているため、そのmarkerはcommit済みイベントのversion以上となる。その後通常と同じdrain（古いeventはmarker確認後APPLIED）と最終再構築・検証を行う。DEADはこの手順でも無視・消去しない。

## 11. Backend基盤チェックポイント

実装言語・HTTP基盤はPython / FastAPI、PostgreSQL driverはPsycopg 3、ASGI serverはUvicornとする。
Pythonの対応範囲はbackend/pyproject.tomlで管理し、基盤検証環境はPython 3.14.4 / PostgreSQL 18.6。
package versionはbackend/pyproject.tomlに記録する。Neo4j / Qdrant / LLMの接続は最初の基盤コミットへ含めない。

初回基盤PRは管理表と疎通用SQLのみ。後続の業務スキーマPRで10テーブルを追加済みであり、seed・業務APIは未実装。
標準起動はDocker Compose。`python3 scripts/create_demo_env.py`でGit管理外の資格情報を生成し、`docker compose up --build -d --wait api`でPostgreSQL → migration → APIの順に起動する。
API・migrationは非rootコンテナ、DB portは非公開、APIは127.0.0.1に公開。通常の`docker compose down`は正本volumeを保持する。
テストは独立した`compose.test.yaml`とtmpfs PostgreSQLで実行し、デモの永続volumeを共有しない。
資格情報・ホストport・volume保持・Dockerテストの具体手順はREADME.mdを正とする。
`GET /health`はプロセス応答、`GET /health/ready`はPostgreSQL接続を確認する。両方にBearer認証を要求し、共通Envelopeを返す。
認証なしは401、readinessのDB利用不可は503。接続先・credentialをResponseへ返さない。
health / readinessは基盤の運用Endpointであり、Agent Toolへ公開しない。詳細な設定・テスト手順はREADME.mdを参照する。
Runtime依存はbackend/requirements.lock、開発依存はbackend/requirements-dev.lockで固定する。ホストで補助的に開発する場合は、ルートから以下を実行する。Python 3.12以上が必要であり、標準検証経路はDockerとする。

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.lock
.venv/bin/pip install --no-deps -e ./backend
.venv/bin/ruff check backend scripts
.venv/bin/pytest backend/tests -q
```

ホストDBテストは専用DBのLINESCOPE_TEST_DSNを明示指定する。未指定時はDBテストがskipされる。ホストAPI起動の設定例はbackend/.env.exampleで、ホストでは.envを自動読込みしない。Dockerの資格情報はルート.envを使い、PostgreSQL 18の永続volumeは/var/lib/postgresqlへmountする。Python packageのimport名はlinescope、配置先はbackend/src/linescope。
最終製品の初期化・復旧手順は§10を維持し、基盤だけのreadinessをGraph CURRENT・RAG準備完了の根拠にしない。
