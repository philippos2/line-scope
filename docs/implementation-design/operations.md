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

## 12. 業務判断支援の運用前提

新しい入力・計算・基準が未確定または未実装なら、その機能をReadyや受入済みとして表示しない。運用・受入記録でPASS / FAIL / BLOCKED / NOT_IMPLEMENTEDを区別する。比較には入力version・観測時刻・評価期間を残し、後続の正本変更で過去の評価を現在の確定値と誤認させない。履歴保持や安全基準の登録・更新主体はPO-B04・06・07確定後に手順化する。既存のOutbox / Graph復旧手順は維持する。

## 13. ログ設計

### 13.1 目的・責務・規模

要求がどう処理され、どこで拒否・失敗したかを調査できることを目的とする。個人開発の単一工場デモではJSON標準出力とDocker logsを基本とし、集中ログ基盤、APM、分散トレーシング製品、独自ログ検索UIは初期導入しない。必要が生じたら同じ構造化イベントを収集できるようにする。

| 種類 | 内容 | 保存先と正本 |
|---|---|---|
| アプリケーション運用ログ | HTTP / Toolの結果・所要時間・拒否理由・依存障害 | JSON Linesでstdout。業務正本ではない |
| 業務監査 | 主体、Prepare / Approve / Reject / Execute / Invalidate / Expire等、状態遷移、結果 | PostgreSQL update_audit_event。変更前後は保存Snapshot・成功履歴を参照 |
| 非同期運用ログ | Projection試行・retry・DEAD、Rebuild開始・完了・失敗 | 同じJSON Lines。Outbox・control・監査のDB記録を状態正本とする |

監査表・状態・Transactionはdata-model §9とtransaction-designを正とする。本節は新しい監査テーブルや状態遷移を追加しない。認証失敗などUpdateRequestがまだ存在しないイベントは運用ログへ記録し、存在しないFKを作らない。

### 13.2 共通イベント形式

UTF-8、1イベント1行JSON、loggerはPython標準loggingを基盤とする。Formatterとイベント出力関数で許可項目を制御し、任意dictやオブジェクトのreprをそのまま出力しない。イベント名・結果コードを固定して機械検索可能にする。

| 項目 | 契約 |
|---|---|
| log_schema_version | 整数1。ログ形式の版でありSnapshot schemaとは別 |
| timestamp | サーバUTC、ISO 8601の末尾Z、microsecond精度 |
| level | DEBUG / INFO / WARNING / ERROR |
| service / component | linescope / api・tool・proposal・projection・rebuild等の固定識別子 |
| event | 固定イベント名。自由文や利用者入力を名前に使わない |
| outcome | success / partial / rejected / failure / unknown。業務状態とは別 |
| request_id | HTTP要求ごとにサーバ生成UUID。内部workerも試行・管理処理ごとにサーバ生成 |
| duration_ms | 完了イベントで必須の非負整数。monotonic clock差から求める |
| result_code | API / Toolの既存code、または固定した内部成功・障害code。自由な例外messageを使わない |

必要に応じてcontext_id、update_request_id、approval_id、outbox_id、rebuild_id、graph_generation、tool_call_id、actor_id、role、snapshot_hash、attempt_count、dependency、http_method、route、http_status、before_status / after_status、supersedes_update_request_id、replayed、aggregate_type / aggregate_id / aggregate_version、件数の固定項目、graph_observed_at、state_observed_at、評価期間、exception_type / stack_framesを付ける。UUID・hash・enum等を型検証し、未確定のIDは省略する。技術メタデータ以外を自動補完しない。経路はFastAPI route template（例 /update-requests/{id}）を使い、未解決は固定値UNMATCHEDとする。raw URL / query stringを出さない。

actor_id / roleは認証済みContextまたは内部サービス主体から取得する。非認証要求には付けず、入力されたBearer値や自己申告userを出さない。ログ全体をLLMや通常ユーザーへ公開しない。

例（基盤healthの完了）:

```json
{"log_schema_version":1,"timestamp":"2026-10-09T05:00:00.000000Z","level":"DEBUG","service":"linescope","component":"api","event":"http.request.completed","outcome":"success","request_id":"00000000-0000-4000-8000-000000000001","duration_ms":2,"result_code":"OK","http_method":"GET","route":"/health","http_status":200}
```

### 13.3 相関と並行処理

HTTPのrequest_idは受信ごとに新しく生成し、Response Envelopeと運用ログで一致させる。外部ヘッダーを正本request_idとして採用しない。middleware入口でContextを設定し、finallyで必ず解除する。async処理・threadpoolの境界ではContextを伝播させ、別要求へ漏らさない。内部Toolには既存Trusted Execution Contextのrequest_idを使う。Tool呼出しごとにローカルなtool_call_idを付ける。

context_idは複数ターン、update_request_id / approval_idは変更準備から承認・実行、outbox_id / graph_generationは反映・分析を結ぶ。retryではrequest_idを使い回さず、同じ業務IDと試行番号で関連付ける。context_id・retry key・request_idを権限や冪等性の根拠として混同しない。prepare_retry_key / idempotency_keyの生値はログへ追加せず、保存されたUpdateRequest IDで追跡する。

workerは新しい実行request_idとoutbox_id / update_request_idを記録する。元HTTPとの関係は業務IDと監査を経由して追えるようにし、未保存の元request_idを推測しない。Graph結果はgenerationと観測時刻、経済分析は入力観測時刻と評価期間を区別する。

### 13.4 レベルとイベント

| イベント | レベル・記録条件 | 必要な追加情報 |
|---|---|---|
| service.started / stopped | INFO、起動設定は秘密を除いた許可項目のみ | component、処理結果 |
| http.request.completed | 通常成功・partial・入力／認証／権限拒否はINFO、一時依存障害はWARNING、内部障害はERROR | route、method、status、result_code、duration_ms |
| health / readinessの正常完了 | DEBUG。失敗は原因に応じWARNING / ERROR | 同上。監視pollでINFOを埋めない |
| tool.call.completed | 成功・業務上の拒否はINFO、一時障害／再試行予定はWARNING、内部不整合はERROR | allowlisted Tool名、tool_call_id、code、duration_ms、対象技術ID |
| proposal.saved / replayed / replaced | commit後INFO | 要求・承認ID、hash、旧要求ID（replaced時）、replayed |
| approval.completed / execute.completed | commit後INFO、拒否はINFO | 主体、要求・承認ID、前後状態、code |
| execution.outcome_unknown | ERROR。commit結果を確認できないとき | 要求ID、code。成功／rollbackを断定しない |
| projection.attempt.completed / retry_scheduled | 成功INFO、再試行WARNING | Outbox / aggregate ID・version、attempt_count、code、duration_ms |
| projection.dead | ERROR | 同上。fatalな詳細は秘匿して固定code |
| rebuild.started / completed / failed | 開始・完了INFO、失敗ERROR | rebuild_id、generation、件数、duration_ms（終了時） |
| audit.persist_failed | ERROR | 関連要求ID、code。監査欠落を正常記録と扱わない |

通常は終了イベントを1件記録し、全層で同じ例外stackを重複出力しない。長時間Rebuildは開始も残す。実装時にイベント名を固定し、未実装処理のイベントを架空に発行しない。想定された認証・権限拒否は個別にINFOとして残し、拒否の頻発を調査できるようにする。初期段階で検知サービスは追加しない。

予期しない例外は責任を持つ境界でERRORを1件記録する。stack traceは例外クラスとframeのmodule / function / lineに限定した構造化診断にする。例外message・args・locals・source line・SQL・接続文字列・provider生応答は出さない。任意のexc_info=Trueやlogger.exceptionだけで秘匿済みとは扱わない。内部stack診断と完了イベントが同時に必要なら同じrequest_idで関連付け、詳細stackは1回だけにする。

### 13.5 秘匿と出力量

通常ログへ記録しないもの:

- Authorization、token、password、secret、DSN、cookie、全HTTP headers。
- request / response body、利用者発話、prompt、LLM内部推論、provider生応答、embedding。
- 文書本文・検索chunk、Snapshot / before / after全文、Outbox payload全文。
- 任意SQL / Cypher、自由な例外message、業務Objectのnameや自由記述。

DEBUGでも禁止項目を許可しない。allowlistを主防御とし、単なるkey名置換やtoken文字列maskだけに依存しない。ID・hash・版・codeによって正本を参照する。監査detailsも必要な技術ID・理由code等へ限定し、Snapshotを重複コピーしない。

event・result_code等は固定識別子、その他の文字列は最大256文字、stack frameは最大20件に制限する。許可されたfieldが型／長さ不正ならそのfieldを省略し、未知fieldは捨てる。JSON encoderで改行・制御文字をescapeし、1行に保つ。特にactor_id等の利用者設定値をevent名やログmessageへ連結しない。秘密を含む可能性がある不正値そのものをエラーとして再ログしない。

Uvicornのraw access logは無効にしてHTTP完了イベントへ統一する。server起動・終了と依存ライブラリのloggerも設定を確認し、DEBUGのwire / SQL出力を有効化しない。アプリloggerの許可項目制御が第三者loggerも自動的に安全にするとは考えない。標準CLIでは第三者のWARNING / ERRORを固定runtime.diagnosticへ変換し、生message / args / 例外を転送しない。独自ASGI起動では起動側で同じ制御を設定する。

### 13.6 Transaction・監査との境界

proposal保存・置換、Approval、ExecuteのsuccessログはTransactionのcommit成功後にだけ出す。rollback時はfailure / rejectedとして記録し、試行開始ログを更新完了と扱わない。COMPLETED再送はreplayedとして元結果を示し、二度目の業務更新成功と数えない。確定afterと後続current valueを混同しない。

成功監査は業務変更・状態遷移と同一Transaction。監査INSERT失敗時はTransactionをrollbackし、成功ログを出さない。rollbackした試行の失敗監査は別Transaction、PostgreSQL不可ならaudit.persist_failed付き運用ログへfallbackする。Prepare失敗でUpdateRequestが存在しなければFKなしの架空監査を作らずrequest_idの運用ログで追跡する。

stdout出力失敗は業務監査保存失敗とは別に扱う。logging経路の例外で確定済みcommitやHTTP結果を変えない。logging handlerの失敗診断はcredentialを含まない固定文でstderrへ最善努力し、ログの無限再帰や大量retryをしない。stdoutログだけで監査保存を済ませたことにしない。

### 13.7 保存・閲覧・調査

初期はDockerのlogging driverによる容量ローテーションを使う。技術既定値はlocal driver、max-size=10m、max-file=3を各サービスへ適用する設計とする。アプリはJSON標準出力へ書き、独自のコンテナ内ログファイル・volumeを追加しない。現在のruntime Composeの全サービスへ適用済み。新サービス追加時もlogging設定を継承する。容量制限であり日数保証ではない。コンテナ削除・rotationで運用ログは失われ得る。

DB監査・成功履歴は正本backup対象で、Dockerログのrotationと連動して削除しない。v1では監査の自動期限削除は導入しない。将来の保持期間・公開／削除要件は運用方針として別途決める。開発デモDBの意図的resetと監査の通常運用を区別する。

運用ログ閲覧は開発／運用管理者のDockerアクセスに限定する。通常APIやAgentから全ログを参照させず、外部共有時はactor・各種IDを含めて確認する。DB監査閲覧は既存access-controlの要求・カテゴリ境界を守り、一般のRead権限で全監査を公開しない。

調査は①Response request_idでHTTP結果確認 → ②Tool / dependencyのcode確認 → ③UpdateRequest / Approval / auditの正本確認 → ④必要ならOutbox / generationを確認、の順で行う。成功監査やOutbox状態をstdoutの順序だけで復元しない。LOG_LEVELはINFOを既定とし、不正設定は起動拒否。依存サービスの接続先や全設定dumpを起動ログへ出さない。

### 13.8 段階導入と今回の実装境界

設計は本節、実装状況はREADMEとhistoryに分ける。HTTP境界の構造化ログ・相関・秘匿済み例外診断、標準CLIのUvicorn / 依存logger制御、runtime Composeのローテーションは実装済み。DB監査とTool / workerへの操作イベント接続は未実装。

今回の基盤チェックポイントで、JSONイベント／許可項目制御、Context設定・解除、ログ設定、HTTP完了・拒否・例外・readiness障害、Uvicorn access log統一、Docker容量制限、秘匿と並行要求のテストを導入した。API / Tool / workerが増える前に共通基盤を揃える価値がある。

DB監査migrationとTransaction統合はPrepare / Approval / Executeの実装に合わせて別チェックポイントで行う。Toolの操作イベントは共通基盤導入後に対象処理へ接続し、Outbox / Rebuildのログは各機能の実装時に追加する。初回に全監査・非同期処理・収集製品を詰め込まない。ログの合格だけで業務Scenarioの受入完了とは扱わない。

## 14. PostgreSQL検索接続の段階分離

SQL / DBアクセス方針はarchitecture §15。通常Read Toolの接続先は、信頼されたサーバ設定`LINESCOPE_READ_DSN`で分離できる。HTTP入力やTool引数から接続先を指定・変更できない。明示設定した検索接続の障害時は既存のDEPENDENCY_UNAVAILABLEへ変換し、更新用`LINESCOPE_DSN`へfallbackしない。接続秘密はSettingsのrepr・外部エラーへ出さない。

検索接続は同じ正本DB・schemaへ接続する検索専用role用とし、別の業務正本や非同期replicaを暗黙に導入しない。通常Read Toolは引き続きREAD COMMITTED / READ ONLY transactionで実行する。検索roleは業務検索に必要なSELECTだけを持ち、DDL・mutation・監査の無制限閲覧を許可しない。readonly transactionはrole権限制限の代替ではない。

Prepareは業務観測に加え要求・Approval・監査を保存するため、全体を検索接続へ切り替えない。Approval / Execute / migration / readinessの既存接続とtransaction semanticsはこの段階では変更しない。

移行途中の互換性としてREAD_DSN未設定時は従来DSNで検索する。この状態はleast privilege適合ではない。空文字や非文字列の明示設定は起動時に拒否する。現Composeはまだ検索DSNを設定せず、role作成・GRANT・credential生成・既存volumeの非破壊upgrade・migrationとruntimeの分離は後続である。role分離完了時はこの互換モードの運用可否を再確認する。
