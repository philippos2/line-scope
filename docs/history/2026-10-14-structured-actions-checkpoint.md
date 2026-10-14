# 同一カテゴリ明示JSONの更新経路

再開用作業記録であり仕様正本ではない。

- #223はmerge済み。main0db9140からfeat/structured-controlled-actions、commit d7c976c、PR #224。
- 「設備状態／保全／生産作業／依存関係の変更準備を{targets...}で作成して」という元の要求文を認識。最大10入力、登録済みPrepareだけ、全Target同一カテゴリ。
- 元の明示入力→型／権限検証→正本参照とSnapshot→別ActorのApproval→requesterのExecute→再送を公開APIで接続。LLMへ任意操作の権限を与えない。
- 設備パーサは他の設備状態形式に未一致ならNoneを返し、新形式を次の認識処理へ渡す。命令文規則v7。
- 関連67成功、3.53秒。追加10ケース。4カテゴリ、保全複合と再送、混在／Execute指定／version持込み／上限／権限拒否を確認。lint・format323ファイル成功。
- verify_multi_equipment_flow.pyの専用Compose/curlで明示JSONの2Target要求置換→旧要求INVALIDATED→承認→一括実行→再送成功。LLM未使用、専用volume／認証情報とローカル試験環境は片付け済み。
- DB／SQL／lock／transaction／Outbox／Snapshot形式は変更していない。自由な日本語や曖昧対象の確認継続は未追加。既存警告とlogging output failedは未調査。

次は#224のmergeを確認して再開する。個人開発デモとして、正式業務データの未確定を理由に試作の完走を止めず、固定入力と実装の範囲を明示する。認可・承認と実行の分離・更新原子性は維持する。現在のroadmapと最新のチェックポイントを参照し、内部部品数を進捗としない。

CI全成功：3741成功・1skip、収集3742件・hash一致、選択1861＋1881＝3742。試験時間258.07秒／265.63秒。runtime・migration・PR title・集約checkも成功。
