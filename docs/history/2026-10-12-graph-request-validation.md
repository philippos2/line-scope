# 通常Graph探索の入力・認可境界

正本はaccess-control §9とapi-tools §9・§10・§17。今回の変更は接続前のApplication処理であり、Graph Toolの公開ではない。

- trace_downstream_impact / trace_upstream_dependenciesの二つだけを対象とし、固定の論理方向へ解決する。認証済みExecutionContextを要求し、保全・生産管理・工場管理に限定する。現場ロールは通常Readの既存権限のまま、Graph分析を拒否する。
- targetの型付きUUID、明示時刻、通常探索のrelation filter、requested depth / nodes / pathsを厳密に検証する。未知field、role / user_id / request_id、SQL / Cypher、client timeoutは受け付けない。入力を変更せずUUID・時刻・filterを正規化する。
- サーバ側の正整数system limitsを必須とし、requestedとsystemの小さい方を使う。未指定はsystem。timeoutはサーバ値だけ。受信時のサーバ時刻を一度だけ使ってas_ofを固定し、未来・naive時刻を拒否する。
- この境界だけで対象存在・active・CURRENT / generation・状態正本・Evidenceを確認したとは扱わない。Graph read serviceへの接続、TIMEOUT partial、公開Tool / Agent登録は後続。
- DB・API schema・既存Read / 更新処理を変更しない。SQL / Cypherを追加せず、LogiScopeコードは再利用していない。退避した開発原則のdocs変更は保留のまま。
