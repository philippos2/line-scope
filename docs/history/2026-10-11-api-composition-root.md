# API composition rootの分離

## 変更

APIの依存組立を `linescope/bootstrap.py` に集約し、Settings / Database / logging、Read Tools、Prepare、Human Approval / Execute、ConversationStore、LLM / Agentを構築する。`interfaces/api.py` は組立済みサービスを受け取り、handler内でProposalStoreを生成しない。

既存の `create_app` 引数と `app.state` を維持する。組立時にDB接続やmigrationを実行せず、起動・health・認証試験で確認する。ProposalStoreはDatabase参照のみを保持し、共有してもconnection / transaction / request stateを共有しない。既存のtransaction所有者・lock・version・Audit / Outbox原子性は変更しない。

## 境界と後続

composition rootは具象実装を知る場所として明示する。新しいミドルウェアの配線変更はここへ集約できるが、すべてのミドルウェア変更を無修正で吸収できるとは主張しない。ReadinessのDatabase probeとdriver例外処理は運用診断の既存経路として残る。ProposalStore内部の複合責務とApplicationのPersistence依存は今回の範囲外。

配置整理、Agent業務振り分け、LLM例外境界、API依存組立の改善を今回の区切りとする。後続はGraphの初期化・Rebuild / 運用へ戻り、具体的な変更箇所と回帰リスクを根拠に追加の境界改善を行う。
