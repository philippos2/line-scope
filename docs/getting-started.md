# 起動・APIデモガイド

通常の永続環境を起動し、調査・比較・承認付き変更をcurlで試す手順です。Docker Engine、Compose v2、ホストのPython 3、必要に応じてOllamaを使用します。ブラウザ画面でも調査・比較・根拠を確認できます。

開発中の継続プレビューを確認するときは、先に[現在のブラウザ確認環境](demo/environments.md)を参照してください。以下の5173番は新規環境の既定値です。

## 最短で通し検証する

clone後、永続環境を作らず最小経路を確認できます。

```sh
git clone https://github.com/philippos2/line-scope.git
cd line-scope
python3 scripts/verify_minimal_flow.py
```

Docker socketへのアクセスに既存のdockerグループが必要な環境では`--docker-group docker`を付けます。専用のCompose project、資格情報、volume、空きloopback portを作り、終了時に削除します。通常の`.env`やvolumeは使用しません。

このスクリプトは実PostgreSQL・Neo4j・HTTPを使い、影響・比較候補→Prepare→承認前Execute拒否→別の承認者によるApproval→requesterのExecute→再送→更新後確認を実行します。LLMは不要です。未選択の費用・能力・安全条件は不明を保持します。正式入力による数値比較は、登録・承認・確定した入力を選択して行います。

## 通常環境の起動

Docker Engine・Docker Compose v2と、資格情報生成用のPython 3を用意します。API / migration / ProjectionはPython 3.14.4の非rootコンテナ、PostgreSQLは18.6、Neo4jは5.26.31-communityです。通常Composeのファイル名は`compose.yaml`です。

```sh
git clone https://github.com/philippos2/line-scope.git
cd line-scope
python3 scripts/create_demo_env.py
docker compose up --build -d --wait api
docker compose run --rm -v "$PWD/docs/demo/data:/data:ro" graph-admin linescope seed-demo-file --file /data/scenario1.json
docker compose run --build --rm graph-admin linescope install-graph-schema
docker compose run --build --rm graph-admin linescope rebuild-graph
docker compose up -d projection
```

既存`.env`は上書きしません。既存環境では生成を省略し、`python3 scripts/upgrade_demo_env.py`で不足するrole用credential・Neo4j秘密を追加してから起動してください。資格情報ファイルはGit管理外・mode 0600です。管理者用と検索・runtime・Projection用のDB資格情報を分離します。

PostgreSQLのmigration / role付与とNeo4jのhealth確認後にAPI・Projectionを起動します。APIは`127.0.0.1:8000`に公開し、DB portはホストへ公開しません。API portは`LINESCOPE_API_PORT`で変更できます。

上記はM-204停止・M-208稼働中の新規環境向けデータです。値はJSONから読み込み、既存状態やversionを上書きしません。[データ投入手順](demo/scenario1.md)を参照し、Graph Rebuild後に利用します。構築済みの別シナリオ環境への追加・置換は行いません。

## ブラウザで操作する

上記のseedとGraph Rebuildを完了してからFrontendを起動します。ホストにNodeをインストールする必要はありません。

```sh
docker compose -f compose.yaml -f compose.frontend.yaml --profile frontend up --build -d frontend
```

`http://127.0.0.1:5173`を開きます。接続欄には私有`.env`の`LINESCOPE_USERS`に登録されたtokenの値だけを貼り付けます。管理・生産・保全ロールでGraph分析を利用できます。tokenを共有、Git登録、スクリーンショット掲載しないでください。初回接続後はHttpOnlyのセッションcookieでF5後も接続を復元します。接続切替・解除は上部の「接続設定」から行えます。セッションは固定8時間で、API再起動・期限切れ後は再接続が必要です。

接続後は「設備調査」から進みます。

1. 設備名の一部、または大文字・小文字を区別する設備コード全体で検索します。検索前に固定設備は表示しません。
2. M-204を選ぶと、登録状態「停止中」、下流の影響先、推定損害額200,000円／時間を取得します。上流の依存先にも切り替えられます。
3. 稼働中のM-208が代替候補として自動表示されます。P-100の必要能力60・空き能力80と、安全・品質などの未確認条件を確認します。P-200は今回選択した能力入力では未評価です。
4. M-208を調査対象にすると「稼働中」と表示し、停止損害の算定対象外という理由を示します。
5. 下段の補助タブから、質問・比較・出典・入力の登録訂正・変更承認へ進めます。変更は明示準備、別の承認者による承認、元依頼者の実行を経て確定します。

FrontendのproxyがAPIへ接続するため、ブラウザへDB資格情報を渡しません。Frontendはloopbackの5173番で、`LINESCOPE_FRONTEND_PORT`により変更できます。変更後は同じComposeファイルとprofileで再作成します。通常の停止でvolumeを削除しないでください。

### キーボード操作と失敗時の確認

Tabで「調査領域へ移動」へ進み、Enterで中央の調査領域へ移れます。Graph上の対象は「Graphノードの一覧」から選択できます。折りたたみ領域やボタンはEnter、Snapshot確認チェックはSpaceで操作できます。要求の取得後はSnapshot見出し、失敗時はエラーへフォーカスを移します。

拒否・期限切れ・競合が生じた場合は変更要求IDから保存状態を読み直してください。画面の時刻だけで期限を判定せず、サーバの実効状態を表示します。Executeが確定して現在値取得だけが失敗した場合も、確定済み実行を未実行として扱いません。成否不明の書き込みを自動再送せず、要求IDがないPrepareは同じ指示のまま明示再送してください。接続解除・再読み込み後は画面内の再送キーを保持しないため、確認できた要求IDを控えておきます。

### ローカルLLM

ホストのOllamaにTool calling可能なモデルを用意し、`.env`へ`LINESCOPE_LLM_MODEL=<用意したmodel名>`を設定してAPIを再作成します。

```sh
docker compose up -d --no-deps api
```

コンテナの既定接続先は`http://host.docker.internal:11434`です。Ollamaはコンテナから接続できる待ち受け設定が必要です。必要に応じて`LINESCOPE_LLM_BASE_URL`を指定してください。モデルの自動取得は行わず、具体モデルの採用・日本語回答品質は別途評価します。実Embedding / Qdrantは`compose.rag.yaml`の追加構成で使用します。まず下記の専用環境による実Vector検証で疎通を確認できます。

Read Agent全体の上限は既定120秒です。`LINESCOPE_READ_AGENT_DEADLINE_SECONDS`で正の整数秒を設定できます。初回モデルロードや複数の参照で待ち時間が増え、形式不正・Tool選択ミスもあり得ます。一般質問の失敗と、画面の明示的な比較・Graph操作の結果を区別してください。

### ログ・停止・再起動

```sh
docker compose logs --no-log-prefix --since 10m api
docker compose run --rm migrate
docker compose down
```

APIの運用ログはstdoutのJSONで、request_id・結果code等を使って追跡できます。本文・token・Snapshot・SQL・例外messageは記録しません。DB業務監査とは別です。通常Composeのログ容量はlocal driverの10m / 3 files、ログレベルは既定INFOです。[ログ設計](implementation-design/operations.md#13-ログ設計)

通常の`down`は正本DB volumeを保持します。通常停止に`--volumes`を付けないでください。`.env`のDB passwordを変えても既存DBのpasswordは自動更新されません。migrationは適用済みchecksumの変更を拒否します。[role・volume運用](implementation-design/operations.md#14-postgresql検索接続の段階分離)

## 正式入力から比較する

経済・能力・安全・対応計画／履歴は、画面で登録・承認・確定してから利用する。「正式入力から対応案を比較する」で対象設備、登録入力、共通期間を選択する。分析だけで更新要求は作成しない。

入力が未選択なら候補と不明を返し、固定値で補完しない。従来の`LINESCOPE_DEMO_DECISION_MOCK` / `LINESCOPE_DEMO_DECISION_SCENARIO`は互換受付のみで、固定費用・能力・安全を有効化しない。Graphは現在の同期状態、入力は明示期間の条件付き評価として扱う。

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

次の質問でDecision Packageを取得できます。LLM未設定でもサーバ側の決定論的経路で動きます。

```sh
curl -sS "$BASE_URL/agent" \
  -H "Authorization: Bearer $LINESCOPE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"M-204の異常について影響・修理・交換・代替を比較して"}'
```

`data.decision_package`に実Graphの影響候補、現在設備状態、選択した正式入力の比較、Evidenceとunknownsを返します。未選択時は候補と不明を返し、固定値で補完しません。LLMは明示選択した比較Toolを参照でき、数値・制約・要約はサーバが構築します。

## 実モデルを含む一括デモ受入

ホストOllamaへTool callingモデルとEmbeddingモデルを事前に用意し、コンテナから接続可能にします。モデルの自動取得は行いません。Embeddingの正確なdigestはOllamaの`/api/tags`で確認し、モデル名と対応付けて指定します。以下のモデル名は検証済みの例であり、採用モデルを固定する要件ではありません。

```sh
python3 scripts/verify_demo_acceptance.py \
  --embedding-model embeddinggemma:latest \
  --embedding-digest '<インストールしたモデルの64桁digest>' \
  --llm-model qwen3:30b-a3b-instruct-2507-q4_K_M \
  --report /tmp/linescope-acceptance.json
```

最小経路・複数設備更新・実Embedding/Qdrant文書検索・実LLMの正式比較Tool参照を、独立した専用環境で順次検証します。reportは既存ディレクトリ内の新規ファイルを指定し、0600で保存します。再実行時は別のファイル名にしてください。

全4経路を確認した場合だけPASS（終了code 0）、失敗はFAIL（1）、モデル指定を省略した未実行経路がある場合はPARTIAL（2）です。報告にはrevision・作業ツリー変更有無・時刻・各結果と受入範囲を残します。一般LLM groundingと全UI variantの網羅は保証しません。ブラウザの代表比較経路は別の検証で確認します。

実Vector経路は`compose.yaml`と`compose.rag.yaml`を重ね、API用read keyと管理用write keyを分離します。文書本文・metadataの正本は管理ファイルとPostgreSQL、Qdrantは再構築可能な索引です。一括検証ではこれらの設定・取込み・版更新・alias再構築も専用環境で行います。通常環境へ手動導入する場合は[運用設計](implementation-design/operations.md)と[追加Compose構成](../compose.rag.yaml)を確認してください。

## 確認できる範囲

- 固定デモの構造化結果と承認付き更新を確認できます。
- 正式な費用・能力・安全入力、Golden代表経路はAPIと画面の検証で確認しています。一般Read品質と任意質問の成功は保証しません。
- 過去時刻は現在登録情報の期間評価であり、完全なpoint-in-time復元ではありません。
- 現在の制限と残作業は[ロードマップ](roadmap.md)、仕様は[文書入口](deliverables.md)を参照してください。

## Read Agentの実モデル評価

```sh
python3 scripts/verify_read_agent_quality.py \
  --model qwen3:30b-a3b-instruct-2507-q4_K_M \
  --report /tmp/linescope-read-quality.json
```

必要な環境では`--docker-group docker`を付けます。専用環境で状態と原因不明、下流到達、存在しない設備、上流依存、共通依存の5質問を実行し、回答・Tool結果・Evidenceを0600の新規reportへ保存します。構造化結果成功でも`STRUCTURED_PASS_REVIEW_REQUIRED`であり、文章は別レビューが必要です。モデル名は記録しますがdigestを固定していないため、同名モデルの更新差は保証しません。

単一の下流・上流・共通依存回答は、それぞれの分析種別に沿ってサーバ側で件数・完全性・未評価事項を要約します。共通依存の質問には既知typed IDを含み、名前だけの対象解決は未受入です。代替・SPOF・複数分析や通常Readの自由説明は別の品質評価対象です。

## 全部品を含む常設環境

実文書検索には `compose.rag.yaml` も重ねます。私有envへAPI用read keyと管理用write key、導入済みEmbeddingモデル名・正確なdigest・次元数を設定します（変数名は追加Composeを参照）。通常起動・再起動でも同じ3ファイルを使い、Vector構成を外さないでください。既存のDB資格情報を生成し直したりvolumeを消したりしません。

```sh
docker compose --env-file .env.browser-demo -p linescope-browser-demo \
  -f compose.yaml -f compose.frontend.yaml -f compose.rag.yaml \
  --profile frontend up --build -d --wait frontend projection qdrant
```

検索用参考資料は `docs/demo-documents/equipment-investigation.md` です。業務の安全規則や実工場の保全手順ではありません。管理用CLIで取り込む例：

```sh
docker compose --env-file .env.browser-demo -p linescope-browser-demo \
  -f compose.yaml -f compose.frontend.yaml -f compose.rag.yaml \
  run --build --rm --no-deps -v "$PWD/docs/demo-documents:/demo-documents:ro" \
  knowledge-admin linescope ingest-knowledge \
  --code DEMO-EQUIPMENT-INVESTIGATION --version 1 \
  --title '設備状態と保全調査の参考資料（デモ）' \
  --file /demo-documents/equipment-investigation.md
```

取込みは管理操作です。既に同じcode/versionを取り込んだ環境では無条件に再実行せず、登録済み文書を確認してください。新規環境は通常起動節のenv生成・seed・Graph構築も先に実施します。
