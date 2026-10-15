# 起動・APIデモガイド

通常の永続環境を起動し、調査・比較・承認付き変更をcurlで試す手順です。Docker Engine、Compose v2、ホストのPython 3、必要に応じてOllamaを使用します。ブラウザ画面でも調査・比較・根拠を確認できます。

## 最短で通し検証する

clone後、永続環境を作らず最小経路を確認できます。

```sh
git clone https://github.com/philippos2/line-scope.git
cd line-scope
python3 scripts/verify_minimal_flow.py
```

Docker socketへのアクセスに既存のdockerグループが必要な環境では`--docker-group docker`を付けます。専用のCompose project、資格情報、volume、空きloopback portを作り、終了時に削除します。通常の`.env`やvolumeは使用しません。

このスクリプトは実PostgreSQL・Neo4j・HTTPを使い、影響・仮置き費用比較→Prepare→承認前Execute拒否→別の承認者によるApproval→requesterのExecute→再送→更新後確認を実行します。LLMは不要です。費用・能力・安全条件の入力はモックであり、正式な業務受入全体の合格を意味しません。

## 通常環境の起動

Docker Engine・Docker Compose v2と、資格情報生成用のPython 3を用意します。API / migration / ProjectionはPython 3.14.4の非rootコンテナ、PostgreSQLは18.6、Neo4jは5.26.31-communityです。通常Composeのファイル名は`compose.yaml`です。

```sh
git clone https://github.com/philippos2/line-scope.git
cd line-scope
python3 scripts/create_demo_env.py
docker compose up --build -d --wait api
docker compose run --rm migrate linescope seed-demo-graph
docker compose run --build --rm graph-admin linescope install-graph-schema
docker compose run --build --rm graph-admin linescope rebuild-graph
docker compose up -d projection
```

既存`.env`は上書きしません。既存環境では生成を省略し、`python3 scripts/upgrade_demo_env.py`で不足するrole用credential・Neo4j秘密を追加してから起動してください。資格情報ファイルはGit管理外・mode 0600です。管理者用と検索・runtime・Projection用のDB資格情報を分離します。

PostgreSQLのmigration / role付与とNeo4jのhealth確認後にAPI・Projectionを起動します。APIは`127.0.0.1:8000`に公開し、DB portはホストへ公開しません。API portは`LINESCOPE_API_PORT`で変更できます。seedはM-204（STOPPED）・M-208（RUNNING）と工程・生産作業・製品・インフラの関係を初期投入し、再実行で既存の状態やversionをリセットしません。seed自体は依存Graphの生成を行いません。後続の管理CLIで正本から検証済みgenerationを構築します。未構築の間はworkerがBLOCKEDとなり、Graph分析は利用できません。

## ブラウザで操作する

上記のseedとGraph Rebuildを完了してからFrontendを起動します。ホストにNodeをインストールする必要はありません。

```sh
docker compose -f compose.yaml -f compose.frontend.yaml --profile frontend up --build -d frontend
```

`http://127.0.0.1:5173`を開きます。接続欄には私有`.env`の`LINESCOPE_USERS`に登録されたtokenの値だけを貼り付けます。管理・生産・保全ロールでGraph分析を利用できます。tokenを共有、Git登録、スクリーンショット掲載しないでください。初回接続後はHttpOnlyのセッションcookieでF5後も接続を復元します。接続切替・解除は上部の「接続設定」から行えます。セッションは固定8時間で、API再起動・期限切れ後は再接続が必要です。

比較デモを使う場合は私有`.env`で`LINESCOPE_DEMO_DECISION_MOCK=true`を明示設定し、APIを再作成します。既存の値がある場合は重複追記せず編集します。

```sh
docker compose up -d --no-deps api
```

「比較デモ」→「問い合わせを送信」でGraph・対応案・Evidenceを確認できます。費用・能力・安全入力は仮置きで、実設備の安全判断には使えません。比較の定型説明はLLMがなくても表示します。通常の自然言語調査には下記のローカルLLM設定が必要です。画面の「変更準備・承認・実行」から明示Prepareと保存Snapshotの確認ができます。要求IDを控え、接続を解除して承認者で再接続し、IDから要求を読み直して承認します。その後、元requesterで再接続して要求を読み直し、実行と更新後の結果を確認します。

FrontendのproxyがAPIへ接続するため、ブラウザへDB資格情報を渡しません。Frontendはloopbackの5173番で、`LINESCOPE_FRONTEND_PORT`により変更できます。変更後は同じComposeファイルとprofileで再作成します。通常の停止でvolumeを削除しないでください。

### ローカルLLM

ホストのOllamaにTool calling可能なモデルを用意し、`.env`へ`LINESCOPE_LLM_MODEL=<用意したmodel名>`を設定してAPIを再作成します。

```sh
docker compose up -d --no-deps api
```

コンテナの既定接続先は`http://host.docker.internal:11434`です。Ollamaはコンテナから接続できる待ち受け設定が必要です。必要に応じて`LINESCOPE_LLM_BASE_URL`を指定してください。モデルの自動取得は行わず、具体モデルの採用・日本語回答品質は別途評価します。実Embedding / Qdrantは`compose.rag.yaml`の追加構成で使用します。まず下記の専用環境による実Vector検証で疎通を確認できます。

### ログ・停止・再起動

```sh
docker compose logs --no-log-prefix --since 10m api
docker compose run --rm migrate
docker compose down
```

APIの運用ログはstdoutのJSONで、request_id・結果code等を使って追跡できます。本文・token・Snapshot・SQL・例外messageは記録しません。DB業務監査とは別です。通常Composeのログ容量はlocal driverの10m / 3 files、ログレベルは既定INFOです。[ログ設計](implementation-design/operations.md#13-ログ設計)

通常の`down`は正本DB volumeを保持します。通常停止に`--volumes`を付けないでください。`.env`のDB passwordを変えても既存DBのpasswordは自動更新されません。migrationは適用済みchecksumの変更を拒否します。[role・volume運用](implementation-design/operations.md#14-postgresql検索接続の段階分離)

## 比較デモを有効にする

`.env`へ次を追記してAPIを再作成します。実データの参照と仮置き計算入力を混同しないため、比較機能は明示的なopt-inです。

```dotenv
LINESCOPE_DEMO_DECISION_MOCK=true
LINESCOPE_DEMO_DECISION_SCENARIO=AUTO
```

```sh
docker compose up -d --no-deps --force-recreate api
```

`AUTO`は現在状態に応じたデモ入力を選びます。固定ケースは`STOPPED`、`DEGRADED`、`SAFETY_STOP`、`SUFFICIENT_CAPACITY`、`MISSING_LOSS`、`MISSING_REPAIR_COST`、`NONADDITIVE_LOSS`です。これはサーバ設定であり、質問文から費用や安全条件を正本として登録する機能ではありません。

## APIを直接呼ぶ

以下は上記のセットアップ後、ホストから実行します。`.env`の`LINESCOPE_USERS`にあるtokenを設定してください。tokenをGitや共有ログへ保存しないでください。

```sh
BASE_URL='http://127.0.0.1:8000'
LINESCOPE_TOKEN='<.envにあるBearer token>'

curl -sS "$BASE_URL/health" \
  -H "Authorization: Bearer $LINESCOPE_TOKEN"

curl -sS "$BASE_URL/health/ready" \
  -H "Authorization: Bearer $LINESCOPE_TOKEN"

# 自然言語調査には上記のOllama設定が必要
curl -sS "$BASE_URL/agent" \
  -H "Authorization: Bearer $LINESCOPE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"M-204の現在状態を調べて"}'

# floor / maintenance / managerのいずれかで設備状態の変更準備を作成
# この呼出しだけでは業務値は変わらず、LLM設定も不要
curl -sS "$BASE_URL/agent" \
  -H "Authorization: Bearer $LINESCOPE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"設備M-204の状態をRUNNINGに変更して"}'
```

共通応答は`request_id`、`context_id`、`status`、`answer`、`data`、`evidence`、`warnings`、`errors`を持ちます。調査の`data`には`tool_results`・`tool_trace`・`needs_input`、Prepare結果には`update_request_id`・`approval_id`・canonical Snapshot・hash等を含みます。正常healthは200、認証なしは401、PostgreSQL利用不可のreadinessは503です。readinessはGraph / RAGの準備完了を保証しません。

保存した変更準備を確認する例です。`UPDATE_REQUEST_ID`にPrepare応答のIDを設定します。

```sh
UPDATE_REQUEST_ID='<Prepare応答のupdate_request_id>'
curl -sS "$BASE_URL/update-requests/$UPDATE_REQUEST_ID" \
  -H "Authorization: Bearer $LINESCOPE_TOKEN"
```

承認者とrequesterの操作を分けて実行します。次のIDとhashはPrepare応答から取得し、承認者はSnapshotを確認してください。

```sh
APPROVAL_ID='<Prepare応答のapproval_id>'
SNAPSHOT_HASH='<Prepare応答のsnapshot_hash>'
LINESCOPE_APPROVER_TOKEN='<承認者のBearer token>'

curl -sS "$BASE_URL/approvals/$APPROVAL_ID/approve" \
  -H "Authorization: Bearer $LINESCOPE_APPROVER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"snapshot_hash\":\"$SNAPSHOT_HASH\"}"

curl -sS -X POST "$BASE_URL/update-requests/$UPDATE_REQUEST_ID/execute" \
  -H "Authorization: Bearer $LINESCOPE_TOKEN"
```

承認／拒否は`POST /approvals/{approval_id}/approve`・`/reject`、実行は`POST /update-requests/{update_request_id}/execute`です。approveは`{"snapshot_hash":"<保存済みhash>"}`をJSONで送り、reject / executeはBodyなしです。承認者とrequesterのtokenは権限要件に従って使い分けます。Agentから承認・実行はできません。再送・状態遷移・error codeは[API契約](implementation-design/api-tools.md)を参照してください。

比較を有効にした場合、次の質問でDecision Packageを取得できます。LLM未設定でもサーバ側の決定論的経路で動きます。

```sh
curl -sS "$BASE_URL/agent" \
  -H "Authorization: Bearer $LINESCOPE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"M-204の異常について影響・修理・交換・代替を比較して"}'
```

`data.decision_package`に実Graphの影響候補、現在設備状態、仮置き比較、保全根拠、unknowns、次の操作を返します。`partial`、`demo_only`、`MOCK_FIXTURE`は境界の表示です。損失不明を0にせず、安全情報不足を安全と断定しません。LLMを設定した場合の比較要約は表示順の選択のみをLLMへ委ね、数値・制約・文章はサーバで生成します。通常Read Agentの自由回答とは別の経路です。

## 実モデルを含む一括デモ受入

ホストOllamaへTool callingモデルとEmbeddingモデルを事前に用意し、コンテナから接続可能にします。モデルの自動取得は行いません。Embeddingの正確なdigestはOllamaの`/api/tags`で確認し、モデル名と対応付けて指定します。以下のモデル名は検証済みの例であり、採用モデルを固定する要件ではありません。

```sh
python3 scripts/verify_demo_acceptance.py \
  --embedding-model embeddinggemma:latest \
  --embedding-digest '<インストールしたモデルの64桁digest>' \
  --llm-model qwen3:30b-a3b-instruct-2507-q4_K_M \
  --report /tmp/linescope-acceptance.json
```

最小経路・複数設備更新・実Embedding/Qdrant文書検索・実LLMの表示順選択を、独立した専用環境で順次検証します。reportは既存ディレクトリ内の新規ファイルを指定し、0600で保存します。再実行時は別のファイル名にしてください。

全4経路を確認した場合だけPASS（終了code 0）、失敗はFAIL（1）、モデル指定を省略した未実行経路がある場合はPARTIAL（2）です。報告にはrevision・作業ツリー変更有無・時刻・各結果と受入範囲を残します。モック入力、一般LLM grounding未受入、Web UI未実装は、全4経路PASSでも残ります。

実Vector経路は`compose.yaml`と`compose.rag.yaml`を重ね、API用read keyと管理用write keyを分離します。文書本文・metadataの正本は管理ファイルとPostgreSQL、Qdrantは再構築可能な索引です。一括検証ではこれらの設定・取込み・版更新・alias再構築も専用環境で行います。通常環境へ手動導入する場合は[運用設計](implementation-design/operations.md)と[追加Compose構成](../compose.rag.yaml)を確認してください。

## 確認できる範囲

- 固定デモの構造化結果と承認付き更新を確認できます。
- 一般Read Agentの説明品質、全Business Scenario、正式な費用・能力・安全入力の受入は別途必要です。
- 過去時刻は現在登録情報の期間評価であり、完全なpoint-in-time復元ではありません。
- 現在の制限と残作業は[ロードマップ](roadmap.md)、仕様は[文書入口](deliverables.md)を参照してください。

## Read Agentの実モデル評価

```sh
python3 scripts/verify_read_agent_quality.py \
  --model qwen3:30b-a3b-instruct-2507-q4_K_M \
  --report /tmp/linescope-read-quality.json
```

必要な環境では`--docker-group docker`を付けます。専用環境で状態と原因不明、下流到達、存在しない設備の3質問を実行し、回答・Tool結果・Evidenceを0600の新規reportへ保存します。構造化結果成功でも`STRUCTURED_PASS_REVIEW_REQUIRED`であり、文章は別レビューが必要です。モデル名は記録しますがdigestを固定していないため、同名モデルの更新差は保証しません。

単一の下流回答はサーバ側で件数・完全性・未評価事項を要約します。上流・代替・SPOF・複数分析や通常Readの自由説明は別の品質評価対象です。
