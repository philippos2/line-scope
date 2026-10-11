# Rebuildの単一drain step

## 範囲

transaction-design §9 / §11 / §17、operations §13、T-R12 / T-L07に従い、`RebuildStep.run_once`で既存claim → 保存payload適用 → APPLIED確認／失敗保存を接続する。callerがRebuild ticket、leader、取得済みexclusive mutation lockを所有する。stepはlockを再取得・解放せず、待機・ループ・generation公開を行わない。

- 一回につき最大一イベント。APPLIEDは単一イベント成功、全イベント集合がAPPLIEDであるDRAINEDのみdrain完了。WAITING / RETRYABLEは後続の期限付き反復が必要。DEAD / FENCED / 未知障害はcontrollerを停止すべき状態。
- 保存payload不正・marker整合性不正は恒久不正。既知の一時DB障害、retryable driver障害、generation不在／未検証はretry対象。未知の例外、設定／query異常、leader喪失を恒久不正と推測しない。
- failure保存自体が失敗した場合はUNKNOWNログと例外を返し、PROCESSINGを後続のlease回収対象として残す。commit結果を推測しない。
- workerとRebuildで障害分類／allowlisted完了ログを共有する小さな関数を抽出し、通常workerの分類・transaction・lock順序は維持する。middleware例外はこのGraph実装境界で扱い、HTTP handlerへ持ち込まない。
- 各stepに新しい内部request_idを設定し、finallyで元Contextへ戻す。既存のretry／DEAD遷移ログとattempt完了ログを同じrequest_id・Outbox ID・Rebuild ID・generationで追跡する。payload・例外本文を記録しない。
- claimされていないWAITING / DRAINED / 既存DEADに架空のattempt完了を記録しない。上限claimによるDEADはqueueの確定済み遷移ログのみ。

## 検証と後続

実PG / Neo4jで3イベント適用後のDRAINED、pointer / flag / fatalの保持、既知のretry・恒久不正・上限、未知／設定障害、failure保存失敗、leader喪失、ACK fenceを検証する。通常workerの既存試験で共通化の回帰を確認する。

全体hard timeout付きdrain loop、Rebuild開始／終了ログとcontroller、Restore / crash復旧、管理role / CLIは後続。Graph構築／generation公開は本stepの成功だけで許可しない。SQL・migration・HTTP / Agent公開の追加なし。LogiScopeコード再利用なし。
