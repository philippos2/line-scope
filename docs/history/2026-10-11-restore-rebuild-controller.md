# RestoreのRebuild controller接続

## 変更と責務

operations §10、transaction-design §19の既存仕様に従い、PGのactive_generationがNULLで未処理Outboxが残るRestoreを`RebuildController.run`へ接続した。leaderは引き続き呼出元が所有し、controllerは排他mutation transactionと全段階共通のdeadlineを所有する。

排他lock取得後、既存ProjectionStateでcommit済みOutboxの全状態集合を観測する。DEADがあれば作業用generationを構築せず、通常のdrain停止・失敗保存へ進む。未処理イベントがありDEADがなければ、正本Snapshotから作業用generationを構築・検証し、既存`RebuildControl.stage_restore`で適用先として設定する。取得した新ticketをdrain・heartbeat・失敗保存・最終公開に使用する。

その後Outboxをdrainし、正本を再読込して別の最終generationを構築・検証・公開する。作業用pointer設定だけではrebuild_flagとfatal_errorを解除しない。最終公開は全イベントAPPLIEDと実Neo4j検証を要求する既存fenceを維持する。古いイベントはmarkerのaggregate versionで巻き戻しを防ぎ、APPLIEDとして記録する。

新しいSQLは追加していない。既存のCore制御遷移、Snapshot、parameterized状態観測、Neo4j adapterを使用する。Router/API/Tool、DB schema、業務更新、Approval、Snapshot契約は変更していない。LogiScopeコードは再利用していない。

## 失敗と確定性

- 作業用generationの検証・設定前の失敗ではNULL pointerを維持する。
- staging後のdrainや最終build失敗では、新ticketで固定fatal_errorを保存し、作業用pointerを削除しない。状態はERRORであり正常公開しない。
- staging commit後にleader喪失などで新ticketを受け取れない場合、成功を推測せずunknownを記録する。保存済みpointer/flagを巻き戻さない。
- 作業用build・drain待機・最終buildは同じdeadlineを使い、cleanupは期限切れguardではなく元のleaderで行う。blocking I/O全体の強制中断保証を追加したものではない。

## 試験

既存controllerのbaselineはDockerで18件成功。追加9件を含むcontroller試験27件成功。関連control / staging / drainを含む追加途中段階の試験79件も成功した。最終差分でGraph全体429件成功（51.64秒）、ruff check / format（188ファイル）とgit diff --check成功。

追加試験は実PG/Neo4jで、現在versionと旧versionのイベント、stage→drain→別generation公開、DEADの無変更停止、stage検証失敗、drain失敗、最終build失敗、staging後leader喪失、作業用build期限切れ、drain待機期限切れを確認する。確定後のpointer、flag/fatal、Outbox、marker version/hash、成功ログの有無、lock解放を意味で検証する。最初の試験は全aggregateのmarker数をOutbox件数と誤って同一視したため、対象aggregate IDに限定して検証するよう修正した。assertionの保証対象はOutboxに対応するmarkerの維持である。

T-R12のRestore部分（AC-G13・15〜17）に対応する。切替前後の全crash復旧、常駐worker、運用全体の受入完了を示すものではない。Graph全体の回帰件数と必須CI実測結果はPR本文へ記録する。

## 残件

非NULL pointer先のNeo4j generation欠損、残存rebuild_flagのcrash復旧、worker/controllerのruntime組立・CLIと運用権限、blocking I/Oへの残時間伝播、Graph Read / RAG接続は後続。今回の小さな機能追加を、バックエンド全体の完成と扱わない。
