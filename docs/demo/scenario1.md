# シナリオ1：JSONデータの投入とAPI確認

M-204停止→影響先P-100／P-200→登録条件による200,000円／時間→稼働中M-208を代替候補として提示する初期データ。[JSON](data/scenario1.json)だけに値を置き、Pythonには固定の形式検証とコード参照の変換を置く。

この段階で提供するのはBackendの読取経路と再現データ。単一画面UIは後続PR 2の別承認後に実装する。[計画](../design/scenario1-implementation-plan.md)を参照する。

## 専用環境への初期投入

既存のデモ環境に投入しない。新しい私有envとCompose project・volumeを用意する。秘密値の生成・DB role設定は[起動ガイド](../getting-started.md)を参照し、既存envを上書きしない。例えば新しい.env.scenario1-demoでAPIポートを8002に設定する。DB role用passwordは64桁の小文字hexを別々に生成する。

以下はRepository直下で実行する。ファイルは管理用コンテナへread-onlyでmountする。JSONはruntime imageへ同梱せず、明示したファイルだけを読む。

```sh
docker compose -p linescope-scenario1 --env-file .env.scenario1-demo -f compose.yaml up --build -d --wait api
docker compose -p linescope-scenario1 --env-file .env.scenario1-demo -f compose.yaml run --rm --build \
  -v "$PWD/docs/demo/data:/data:ro" graph-admin \
  linescope seed-demo-file --file /data/scenario1.json
docker compose -p linescope-scenario1 --env-file .env.scenario1-demo -f compose.yaml run --rm graph-admin linescope install-graph-schema
docker compose -p linescope-scenario1 --env-file .env.scenario1-demo -f compose.yaml run --rm graph-admin linescope rebuild-graph
docker compose -p linescope-scenario1 --env-file .env.scenario1-demo -f compose.yaml up --build -d projection
```

APIは初期投入前でも起動するが、正常な関係分析は投入と再構築の完了後に行う。LLMを利用しない明示読取にもReadAgentの組立が必要なので、現行構成ではLLMのmodel設定自体は必要。検証時は専用環境だけmodelを設定し、LLM接続先を到達不能にして非依存を確認した。共有モデルを停止していない。

同じJSONの再投入は既存値・名称・登録状態・版・履歴を保持する。既存関係の不一致は拒否する。再構築中を拒否し、公開済みGraphへ新規データを追加する操作も拒否する。新しいシナリオへの変更を再投入で上書きせず、新しい専用環境で試す。通常の停止でvolumeを削除しない。

## ファイル形式と制約

- schema_version=1。ルートはequipment、processes、products、infrastructure、operations、assignments、relations、economic_inputs、capacity_inputs。
- 最大1,000,000 bytes、各配列最大200件。未知field・重複キー・未知版・コード重複・存在しない参照・不正な宣言型は拒否する。数量は既存domainと同じ十進文字列。
- コードは全区分で一意。IDは既存demo_idのnamespaceでコードからuuid5生成する。旧シードの固定設備UUIDは変更しない。
- 設備種別は既存bootstrapと同じmachine。equipmentはequipment_code・equipment_name・state_codeを持つ。
- 関係と作業は固定schemaを通し、既存DB制約で業務整合性を検証する。正式入力は既存make_recordのdomain正規化を通す。
- 全投入を一transactionに収める。既存のGraph mutation lockとcontrol行lockを保持し、途中の正式入力失敗でもGraph・設備・入力・control変更をrollbackする。
- CLIは管理用。HTTP／Agentからファイル投入を公開しない。ファイル内容・SQL・秘密値をCLI失敗メッセージへ出さない。

既存seed-demo／seed-demo-graph／seed-demo-incidentのデータと動作は変更しない。新データの安全入力・保全入力は登録しない。

## 照合する読取操作

1. POST /agentの「関係分析」へsearch_equipmentを送る。nameは部分一致、equipment_codeは大文字・小文字を区別する完全一致。空欄検索は空filter。
2. 候補から得た設備IDで下流・上流を取得する。デモの固定IDを画面へ埋め込まない。
3. equipment_id完全一致で経済入力を検索し、詳細の適用期間とIDからPOST /incidents/investigateを送る。
4. 下流到達製品すべてをimportant_targets、選択設備をexcluded_nodesとしてfind_alternative_pathsを送る。candidates内の候補、representative_paths、evidence.current_statesを確認する。
5. 候補のequipment_idで能力入力を検索・取得し、元設備IDと候補の入力IDをPOST /decisions/compareへ送る。安全・保全の入力IDは空配列、期間は入力と同じ値。

期待値は損害額200000、P-100のrequired_rate=60、available_rate=80、capacity_status=SUFFICIENT。実測では候補のstructure.determination=ESTABLISHEDだがavailability=UNKNOWN、比較のstructural_basis.statusもUNKNOWN。能力は充足するが安全・品質・運用許可・全体の代替成立を保証しない。これは入力を増やして隠す対象ではない。

製品別未評価の一覧は返らない。P-200の表示は、下流の到達製品IDと今回選択した能力入力のproduct_idを照合した「今回選択した能力入力ではP-200を評価していません」という選択範囲の説明に限る。not_evaluatedを製品一覧と解釈しない。
