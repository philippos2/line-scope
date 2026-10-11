# Rebuildの失敗報告と確定後ログ

## 範囲と判断

transaction-design §9 / §11 / §17、operations §13、T-R12 / T-L07に従い、Rebuild専用queueへ失敗報告を追加する。controllerの例外分類・drainループはまだ接続しない。

- callerが既知の一時／恒久障害を分類し、`RebuildQueue.fail`へ構造化metadataを渡す。未知の障害を恒久不正と推測してDEADにしない。
- leaderと取得済みexclusive mutation lockを確認し、別の短いREAD COMMITTED Transactionでexact attempt（status / attempt_count / processing_started_at）とflag / rebuild_id / 旧generationを照合する。lockを再取得・解放しない。commit前にもleader / lockを確認する。
- transientはRETRYABLE、permanentまたは回数上限はDEAD。attemptは増やさず、backoffは通常queueと同じ1・2・4…最大60秒。last_errorは既存の固定codeのみ。
- lease期限だけで報告のattempt identityを変更しない。期限切れ回収／再claim後の古い報告は一致しないため拒否する。APPLIED / DEADは上書きしない。
- 共通のfailure metadata計算とCore UPDATE builderを使用し、通常queueの意味論を変更せず二重実装を避ける。Rebuildの所有条件は専用入口で固定し、Raw SQLを追加しない。
- loggingは任意の既存EventLoggerを注入する。実際にcommitされたretry / DEAD遷移のみ、既存projection.retry_scheduled / projection.deadイベントへrebuild_id / graph_generationを付ける。payload・例外本文を渡さない。
- claim内のlease回収／上限DEADも確定後だけ記録する。同じTransactionで再claimされた候補の中間RETRYABLEはcommitされないため、回収ログから除外する。WAITING / DRAINEDや既存DEADの再観測で架空の遷移ログを生成しない。request_idは将来のcontroller実行Contextが設定する。

## 検証と残課題

実PGでbounded backoff、attempt不増、所有条件／終端fence、caller lock保持、保存失敗とleader / lock喪失のrollback、ログのID相関とpayload非露出を検証する。通常queueのretry試験を保持する。

例外分類・attempt完了ログを含むdrain orchestration、全体hard timeout、Rebuild開始／終了ログ、Restore / crash復旧、管理role / CLIは後続。ログだけで業務監査を代替しない。LogiScopeコードの再利用なし。
