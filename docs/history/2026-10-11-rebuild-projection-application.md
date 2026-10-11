# Rebuild中のOutbox適用とAPPLIED確認

## 判断と範囲

- transaction-design §11 / §18、T-R12、AC-G13・15〜17に従い、controllerが取得済みleader / exclusive mutation lockを保持したまま、一つの保存済みOutbox attemptを既存Neo4jProjectionへ適用する入口を追加する。
- `RebuildApplication`はlockを再取得・commit・解放しない。保存済みpayloadを検証し、Neo4j commit後に別の短いPG TransactionでAPPLIEDを保存する。
- 通常workerと共通の適用順序・Core statement builderを使用する。通常のflag=false / fatal_errorなし条件と、Rebuildのflag=true / rebuild_id / 旧generation一致条件は専用入口で固定する。外部からfenceを無効化するAPIは設けない。
- Rebuildは既存fatal_errorを復旧対象として許容するが、全OutboxのDEAD、exact attempt / lease、generation、leader、取得済みlockの検証は維持する。
- Neo4j成功でもPG確認が失敗・fence不一致の場合はAPPLIEDとしない。同じ保存済みイベントの再適用は既存adapterのmarker / hash / version検証に委ねる。GraphとPGに跨る原子的commitを仮定しない。
- 共通化は適用・確認の順序を二重実装しないための小さな抽出であり、通常workerのtransaction所有・lock取得順・例外分類を変更しない。

## 検証と残課題

実PGで保存済みpayload、caller lock保持、外部I/O中にrow lockを持たないこと、前後のticket / lease / DEAD / generation fence、leader / lock喪失、APPLIED rollbackを確認する。実Neo4j commit後にPG triggerでACKを失敗させ、markerを残して同じイベントを再適用・APPLIED保存できることを検証する。

今回は単一attemptの適用まで。controllerのdrainループ・待機とhard timeout、失敗分類とログ、Restore / crash復旧、role / CLI接続は後続。通常workerのエラー処理をRebuild controllerの完了扱いとして流用しない。LogiScopeコードの再利用なし。
