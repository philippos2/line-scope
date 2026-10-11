# Rebuild control遷移・公開のfence

## 内部サービス

RebuildControlはleader取得後の開始flag保存、検証済み世代の公開、失敗保存を短いPostgreSQL transactionで扱う。通常の業務更新やHTTP / Agentには公開しない。更新SQLはPersistenceのCore固定statementとbind parameterを使用する。

開始はcontrol行をlockし、既存fatal_errorを復旧対象として許容する。既存rebuild_flagがある場合は新IDで上書きせず、復旧工程が必要として拒否する。

公開はcallerのREAD COMMITTED / exclusive mutation lockを確認し、Neo4jからvalidated marker・snapshot_hash・検証時刻を再確認する。DTOだけを成功根拠にしない。Rebuild ID、開始時の旧generation、flag=true、全OutboxがAPPLIEDである条件付きUPDATEでactive_generationを切り替え、fatal_error / flagを解除する。未処理・DEADがあれば拒否する。排他transactionは公開後もcallerが保持する。

失敗は同じID・旧generationの所有条件でのみ固定code REBUILD_FAILEDを保存し、旧generationを保持してflagを解除する。古い失敗報告が後続Rebuildや公開成功を上書きしない。rebuild_idは追跡用に保持する。leader喪失時にflagを推測解除しない。

## 試験と残課題

実PostgreSQL / Neo4jで初期ERRORからの開始・公開、既存fatal復旧、同期gateの状態遷移、未処理全状態 / DEAD拒否、APPLIED許容、stale ID拒否、既存flag拒否、検証marker再確認、exclusive lock必須、leader喪失、PG pointer更新失敗のrollbackを確認する。T-R11 / R12のcontrol部分の試験であり、Rebuild受入全体の完了ではない。

readerのexclusive lock確認を共通Graph lock helperへ移した。実装の意味・取得順は変更しない。

常駐worker停止・drain・lease回収、Snapshot取得から公開までを接続するcontroller、hard timeout全体管理、crash後のflag復旧、restore作業用generation、管理role / CLI / ログは後続。Neo4j公開証跡とPG pointerを跨ぐcommitは分散transactionではなく、後続controllerが失敗状態を照合する。
