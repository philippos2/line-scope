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

初回基盤PRは管理表と疎通用SQLのみ。現在は業務10テーブルに加え、更新要求・承認・監査・実行履歴・Graph Outbox / 同期管理を実装済み。設備2台のseed、Agent API、更新要求閲覧、Approval / Reject / Execute APIも実装済み。起動可能な範囲と操作例はREADMEを参照する。
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

workerは新しい実行request_idとoutbox_id / update_request_idを記録する。同期状態確認だけでBLOCKED / IDLEとなった場合は架空のattempt完了ログを出さない。lease回収は実際にRETRYABLEをcommitした行、上限済みclaimの退役は実際にDEADをcommitした行だけを記録する。元HTTPとの関係は業務IDと監査を経由して追えるようにし、未保存の元request_idを推測しない。Graph結果はgenerationと観測時刻、経済分析は入力観測時刻と評価期間を区別する。

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
| projection.attempt.completed / retry_scheduled | 成功INFO、再試行・lease回収・再検証拒否WARNING、予期しない障害はERROR | Outbox / aggregate ID・version、attempt_count、code、duration_ms |
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

設計は本節、実装状況はREADMEとhistoryに分ける。HTTP境界の構造化ログ・相関・秘匿済み例外診断、標準CLIのUvicorn / 依存logger制御、runtime Composeのローテーションに加え、Prepare / Approval / ExecuteのDB監査とTool / workerの操作イベントを実装済み。常駐workerの標準Compose接続と運用監視は後続。

今回の基盤チェックポイントで、JSONイベント／許可項目制御、Context設定・解除、ログ設定、HTTP完了・拒否・例外・readiness障害、Uvicorn access log統一、Docker容量制限、秘匿と並行要求のテストを導入した。API / Tool / workerが増える前に共通基盤を揃える価値がある。

基盤導入時にはDB監査migrationとTransaction統合、Tool操作イベント、Outbox / Rebuildログを別チェックポイントへ分け、その後各機能へ追加した。初回に全監査・非同期処理・収集製品を詰め込む方針ではない。ログの合格だけで業務Scenarioの受入完了とは扱わない。

## 14. PostgreSQL検索接続の段階分離

SQL / DBアクセス方針はarchitecture §15。通常Read Toolの接続先は、信頼されたサーバ設定`LINESCOPE_READ_DSN`で分離できる。HTTP入力やTool引数から接続先を指定・変更できない。明示設定した検索接続の障害時は既存のDEPENDENCY_UNAVAILABLEへ変換し、更新用`LINESCOPE_DSN`へfallbackしない。接続秘密はSettingsのrepr・外部エラーへ出さない。

検索接続は同じ正本DB・schemaへ接続する検索専用role用とし、別の業務正本や非同期replicaを暗黙に導入しない。通常Read Toolは引き続きREAD COMMITTED / READ ONLY transactionで実行する。検索roleは業務検索に必要なSELECTだけを持ち、DDL・mutation・監査の無制限閲覧を許可しない。readonly transactionはrole権限制限の代替ではない。

Prepareは業務観測に加え要求・Approval・監査を保存するため、全体を検索接続へ切り替えない。Prepare / Approval / Executeはruntime role、migration / provisionは管理roleを使う。既存transaction semanticsとlock順序は変更しない。readinessはruntime接続の確認であり、検索接続の健康を別途保証するものではない。

READ_DSN未設定時は直接Python利用等の互換性として従来DSNで検索する。この状態はleast privilege適合ではない。空文字や非文字列の明示設定は起動時に拒否する。標準ComposeはREAD_DSNを必須設定し、この互換モードを使わない。


### 14.1 標準ComposeのDB role

| 主体 | role | 権限 |
|---|---|---|
| 管理・migration・デモ初期投入 | linescope（既存owner） | 管理用。role provisionのためsuperuserを維持しAPIへ渡さない |
| APIの認可済み変更 | linescope_runtime | 固定対象のSELECT / INSERT / UPDATE。DELETE・TRUNCATE・DDL不可。監査・成功履歴はINSERTのみ、OutboxはSELECT / INSERTのみ、Projection controlはSELECTのみ |
| 通常Projection worker（常駐起動は後続） | linescope_projection | graph_outbox / graph_projection_controlのSELECT、Outboxのstatus・attempt_count・next_attempt_at・processing_started_at・processed_at・last_errorのみUPDATE。業務表・承認・監査・payload・aggregate情報・control変更・DDL不可 |
| 通常検索Tool | linescope_query | 既存検索対象10表のSELECTと、Graph分析用のgraph_outbox.status、graph_projection_controlのcontrol_id・rebuild_flag・active_generation・fatal_errorのSELECT。Outbox payloadと更新権限は付与しない。要求・承認・監査・成功履歴・migration台帳は閲覧不可 |

3種類のLOGIN roleはNOSUPERUSER / NOCREATEDB / NOCREATEROLE / NOREPLICATION / NOBYPASSRLS / NOINHERIT、他roleへのmembershipとObject ownershipなし。業務利用者ごとの認可は既存API / applicationの責務であり、DB roleを工場長・保全等の業務roleと混同しない。

実装の固定allow-listはdb_roles.py。設備・工程・製品・インフラmasterは既存FOR SHAREに必要なUPDATE(version)だけをruntimeへ付与する（PostgreSQLのrow lockにはUPDATE権限が必要）。masterの他業務列の更新権限は付与しない。この限定権限でも直接DB接続はversion変更能力を持つため、DB credentialをAgent / 利用者へ公開せず、任意SQL経路を作らない。

### 14.2 管理処理と既存volumeのupgrade

標準migrateサービスは管理接続で`linescope migrate-and-provision`を実行し、その成功後にAPIが起動する。migration commitとrole provisionは別transactionである。provision失敗時はAPIを起動せず、修正後に同じ管理処理を再実行する。role / GRANTの変更はmigration lockを取得した一transactionで行い、途中失敗時はrollbackする。既存migration checksum・owner・業務行は変更しない。

新規環境はcreate_demo_env.pyで管理・検索・runtime・Projectionの別credentialを生成する。既存環境は次の手順とする（volume削除は禁止）。

```sh
python3 scripts/upgrade_demo_env.py
docker compose up --build -d --wait api
```

upgradeはmode 0600の既存.envへ不足する3種類のrole passwordだけを追加し、管理passwordと利用者tokenを保持する。存在する設定は上書きしない。不正・空の既存値はprovisionを失敗させ、値をログへ出さず管理者が修正する。credentialsの変更中はAPIを停止して管理処理を行い、接続中のsessionが即時失効するとの前提を置かない。

デモmasterの初期投入はAPI roleでは行わず、管理用migrateサービスを明示利用する。

```sh
docker compose run --rm migrate linescope seed-demo-graph
```

LineScope専用DBを対象とする管理処理であり、他製品とschema / roleを共有するDBへそのまま適用しない。既存の同名roleにmembership・Object ownership・特権属性があれば自動で流用せず管理者確認を要求する。APIには管理DSN・role provision用password環境変数を渡さない。

### 14.3 GRANTの再適用と将来Object

既存schemaのPUBLIC / 検索 / runtime / Projectionのtable・sequence・function権限と列ACLを除去して固定GRANTを適用する。schema CREATE、database CREATE / TEMPORARYもPUBLIC・3種類のLOGIN主体へ許可しない。既存row・table・schemaは削除しない。

管理ownerのdefault privilegesはfuture table / sequence / functionへPUBLIC・3種類のLOGIN主体の権限を自動付与しない。functionのPUBLIC EXECUTE既定はglobal defaultから除去する。将来migrationでObjectを追加する際は、必要性を確認して固定allow-listを変更し、migration後にprovisionを再実行する。未知tableをON ALL TABLESのGRANTで自動公開しない。現在schemaにアプリ独自function / sequenceはなく、追加時には個別権限を設計する。pg_catalogの標準機能の利用まで一律禁止する仕様ではない。

Raw SQLは管理専用のPostgreSQL DDL例外。passwordはbindしたtransaction-local set_configへ渡し、固定DO blockがPostgreSQLのformat(%I / %L)で固定role名・passwordを扱う。Python側でpasswordをSQLへ補間・手動escapeしない。schema / database名は管理接続のmetadata、table / privilege / role名は固定allow-list、列ACLの名前はcatalog metadataをIdentifierでquoteする。API / Toolへ管理処理や任意identifierを公開しない。CLIのDB障害は固定文に変換する。

公式根拠: [PostgreSQL role属性](https://www.postgresql.org/docs/18/sql-createrole.html)、[default privilegesの適用範囲](https://www.postgresql.org/docs/18/sql-alterdefaultprivileges.html)。

通常Projection用credentialは`LINESCOPE_PROJECTION_PASSWORD`。migration管理サービスだけがprovision用に受け取り、APIには渡さない。この段階ではworkerサービスは起動しない。既存.envは上記upgradeで不足credentialを追加してから起動する。worker roleはcontroller / Rebuild / heartbeat管理権限を兼ねない。

## 15. APIの通常Graph分析接続

APIは信頼されたサーバ設定`LINESCOPE_NEO4J_URI`、`LINESCOPE_NEO4J_USER`、`LINESCOPE_NEO4J_PASSWORD`、`LINESCOPE_NEO4J_DATABASE`（既定neo4j）から分析driverを構築する。URIへcredentialを埋め込まず、credentialと接続先はSettingsのreprに出さない。URI未指定ではGraph Toolを非公開とし、credentialだけの設定や不正URIは起動拒否する。接続不可から別のGraphやPostgreSQL探索へfallbackしない。

探索上限は`LINESCOPE_GRAPH_MAX_DEPTH`、`LINESCOPE_GRAPH_MAX_NODES`、`LINESCOPE_GRAPH_MAX_PATHS`、`LINESCOPE_GRAPH_TIMEOUT_MS`で指定する。既定値は§10のsystem上限に従い、正整数のみを受け付ける。エンドユーザーやLLMの入力から接続先・credential・timeoutを変更しない。接続プール待ちにもGraph timeoutを適用し、driverの自動transaction retryは無効とする。

APIが構築したdriverはサービス終了時に閉じ、構築途中の失敗でも解放する。テスト等で注入したdriverは呼出元が所有し、API終了時に閉じない。Graph read gateのCURRENT確認・generation検証・全体budgetを維持する。readinessは従来どおりPostgreSQLの確認であり、Graph利用可能性を保証するものではない。

接続アカウントは分析用に必要な読取権限へ制限する。driverのREAD_ACCESS指定をDB roleの権限制限の代替としない。標準ComposeではNeo4jとProjection workerを起動する。初回generationの構築とGraphデモ投入は別の明示操作であり、起動だけでGraph CURRENTを保証しない。Neo4j Communityの標準デモ接続は同じアカウントを使用するため、READ_ACCESSをサーバ側の読取専用role保証として扱わない。細粒度権限制御を持つ環境への接続は別途検証する。

## 16. 常駐Projectionの起動と停止

`docker compose up --build -d`はNeo4jのhealthとmigration完了後にAPI・projectionを起動する。既存の私有.envは`python scripts/upgrade_demo_env.py`で不足するrole秘密と`LINESCOPE_NEO4J_PASSWORD`を追記でき、既存credential・データは置き換えない。初回.env生成にもこの秘密を含める。Neo4jは専用volumeへ保存し、ホストへポートを公開しない。

workerのPostgreSQL接続はlinescope_projectionを使い、API tokenやLLM設定を渡さない。`linescope project-graph`は既存ProjectionWorkerの反復を行い、各反復ごとに専用session leaderを取得・解放する。BUSY / IDLE / BLOCKED / RETRYABLE等では1秒待機し、APPLIEDでは次の反復へ進む。各eventのclaim・lease・fence・適用・ACK・retry規則は変更しない。未知例外・leader喪失はプロセスを停止し、勝手にDEADへ変更しない。自動再起動は設定していない。

SIGTERM / SIGINTは終了要求を設定し、待機を解除する。処理中の場合は1反復を終えてから閉じ、途中のcommitを取消済みと扱わない。Composeの停止猶予は45秒とする。強制終了されたPROCESSINGは既存lease回復へ委ねる。Rebuildは次反復のleader取得との間で排他を獲得できる。

`linescope project-graph --once`は1反復だけ行い、起動・停止のJSON運用ログとstatus行を出力する。初回未構築やERROR / REBUILDINGはBLOCKEDであり、起動確認の成功をGraph分析可能と混同しない。normal workerが暗黙にschema / generationを構築・修復することはない。初回Rebuildは§17の管理CLIで実行する。業務Graphの初期投入は§18に従う。

## 17. 初回Graph構築の管理CLI

私有.envの準備と通常サービス起動後、管理者が次を明示実行する。`graph-admin`はtools profileの管理サービスで、通常起動に含めず、既定commandはhelpのみとする。API / Agent Toolへこれらの操作を公開しない。

```sh
docker compose run --rm migrate linescope seed-demo-graph
docker compose run --build --rm graph-admin linescope install-graph-schema
docker compose run --build --rm graph-admin linescope rebuild-graph
```

seed-demoは設備・現在状態のみ、seed-demo-graphは§18の業務Graph fixtureを投入する。いずれも新規追加は初回Rebuild前に行う。正本を直接seedで変更した後に既存Graphを最新と仮定せず、Rebuildで正本から構築する。

schema作成は専用leader → mutation排他lockの順で取得し、固定constraintだけを作成する。各Neo4j statementは既定10秒以下の明示transactionで行う。既存constraintを破壊せずIF NOT EXISTSで再実行できる。複数DDL全体を一つの分散transactionとは扱わず、途中失敗時に既に確定したconstraintが残り得る。schema作成だけでCURRENTにはしない。

Rebuildは既存controllerの60秒予算、leader、rebuild flag、排他lock、drain、正本Snapshot、generation検証・公開を使用する。未確認markerや未処理Outboxを無視してCURRENTを設定しない。旧generationは削除しない。成功結果は検証済みgeneration / Snapshot hash / 件数であり、全業務シナリオの合格ではない。

残存rebuild flagは通常Rebuildで暗黙に回復しない。状態と運用ログを確認後、必要な場合だけ`docker compose run --build --rm graph-admin linescope rebuild-graph --recover`を明示実行する。接続・leader喪失や応答不明時に自動再実行しない。終了codeだけから跨storeのrollbackを推測せず、CURRENTと検証済みmarkerを再確認する。

graph-adminは管理用PostgreSQL / Neo4j接続を使い、PostgreSQLのruntime / Projection roleへDDL・Rebuild権限を拡大しない。作成中の通常workerはleader競合またはREBUILDINGにより待機する。READ_ONLYのAPI・Agentから管理操作を起動できる経路は追加しない。

## 18. 業務Graphデモの初期投入

`linescope seed-demo-graph`は固定fixtureとしてEquipment M-204 / M-208、Process P-10 / P-20、ProductionOperation OP-30 / OP-40、Product P-100 / P-200、InfrastructureResource R-02を投入する。1件のEquipment割当からUSES、9件のDependencyRelationからSUPPLIES / PRECEDES / PRODUCES / CAN_SUBSTITUTEを生成する。正本9 nodeと10 aggregateをRebuildする。デモ日時は2026-01-01からの固定fixtureで、作業予定は2027-01-01まで、有効関係は終端なしとする。業務一般の期間規則へ昇格させない。

M-204停止を与えた条件で、通常下流分析は直接2対象（Process / ProductionOperation）、間接4対象（後続Process / ProductionOperation / 2 Product）へ到達する。上流分析ではR-02への経路を確認できる。M-208→M-204のCAN_SUBSTITUTEは通常到達探索へ混ぜず、能力十分や安全性を保証しない。損失・費用・生産能力・安全基準等の未決定データは追加しない。

seedは初期デモ用の管理操作であり、Approval / 業務履歴 / Outboxを捏造しない。全投入を一つのPostgreSQL transaction、mutation排他lock、control row lockの下で行う。新規投入時は同じtransactionで要Rebuild状態にし、エンドユーザー向け更新の代替として使わない。DB操作は固定table / columnのCore queryとbindで行う。

公開済みgenerationへ新規正本行をseedで追加する操作は拒否し、全rollbackする。初回Rebuild前に投入する。既存fixtureに他の関係が混在する場合や、設備がinactive、ID / 業務キー・既存関係が衝突する場合も拒否し、上書き・暗黙修復・既存データの削除をしない。公開後に追加不要の同一fixtureを再実行する場合はCURRENTを維持する。名称・現在状態・version等は保持し、関係の編集済み意味を初期値へ戻さない。

既存のGraph構築済み環境へのデモ切替は自動resetしない。新しい隔離デモ環境で初期投入するか、別途の明示管理手順を検討する。Graph Rebuild・実LLMの選択品質・業務Scenarioの受入は区別し、seedだけで分析可能と扱わない。

## 19. 実LLMの通常Graph読取probe

初期fixtureとRebuildが完了した隔離デモ環境で、APIに実LLM接続を設定してから実行する。`LINESCOPE_PROBE_TOKEN`には既存のmanagerロールの認証tokenを環境変数で設定し、command引数・ログ・Repositoryへ記載しない。

```sh
docker compose run --rm --no-deps \
  -e LINESCOPE_PROBE_TOKEN \
  -v "$PWD/scripts:/probe:ro" \
  api python /probe/verify_graph_agent.py --base-url http://api:8000
```

probeは`/agent`へ固定の読取質問を一回送り、M-204からの6対象・2製品・代表経路・CURRENT・サーバEvidence・初期state versionを照合する。変更済みfixtureは対象外であり、自動resetしない。Approve / Execute / Prepareは要求しない。HTTP redirectは拒否し、tokenや回答本文、外部例外を結果へ出さない。成功でも自然言語の品質・全Business Scenarioの合格・model選定完了を意味しない。LLMの60秒予算を延長しない。

同じprobeへ`--scenario alternative`または`--scenario spof`を指定すると、初期fixtureのProduct P-100を重要対象、M-204を除外／候補とした構造成立・SPOF分析を確認する。現在時点、初期state version、CURRENT、完全性、未評価次元、Tool結果に対応するサーバEvidenceを照合する。入力に既知typed IDを含むため、名前だけからの対象解決品質は保証しない。HTTP 200でもneeds_inputや必要Tool結果なしはprobe失敗とする。モデルロード時間はAPIの60秒予算と分離し、probe自体でdeadlineを緩めない。

管理CLIのleader競合を避けるため、初回schema / Rebuildを実行するときは通常workerを`docker compose stop projection`で停止し、管理操作完了後に`docker compose start projection`で再開できる。管理操作が失敗した場合は状態を確認し、応答不明の操作を自動retryしない。

Ollamaのコンテキスト枠はサーバ設定`LINESCOPE_LLM_CONTEXT_TOKENS`（既定16384、正整数）で指定する。modelの対応枠とGPU / RAMに合わせて設定し、エンドユーザーやTool引数から変更しない。既定8192では初期GraphのTool結果を含む約10880 tokenの入力がOllamaに拒否されたため拡大した。大きなGraph・会話履歴が常に収まる保証ではなく、LLM実行予算60秒・回答上限・Graph探索上限は維持する。入力超過時の自動枠拡張やTool結果の暗黙切捨ては行わない。
