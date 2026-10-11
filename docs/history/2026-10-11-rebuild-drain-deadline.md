# Rebuild drainの絶対deadline

## 範囲と判断

transaction-design §11 / §17、operations §10、T-R12に従い、単一stepを繰り返す内部`RebuildDrain`を追加する。callerはRebuild全工程と共有する絶対monotonic deadline、leader、取得済みexclusive mutation lock、ticketを渡す。drain内で60秒を再起算せず、v1既定60000msの予算開始と設定注入は後続controllerが所有する。

- APPLIEDは件数を積み上げて続行。WAITING / RETRYABLEは正の有限poll間隔（既定1秒）と残り予算の小さい方だけ待つ。DRAINEDだけを成功として返す。
- DEAD / FENCEDは即時停止し、未知例外を自動retryしない。予期しないstep状態も成功として扱わない。deadline到達はtimeout例外とする。
- 各stepと待機の前後でleader / 取得済みlockを確認する。leaderへdeadline guardを委譲し、既存queue / application / Neo4j adapterの確認地点でも期限を検査する。再取得、reconnect、lock解放、バックグラウンドthreadでの強制中断を行わない。
- deadline到達後に返ったAPPLIED / DRAINEDを成功結果として採用しない。Neo4j成功とPG ACKを跨る結果不明は既存の冪等再適用／lease回収境界を維持する。確定済みcommitをtimeoutで取り消せるとは仮定しない。
- 同期I/O中の制御復帰は既存DB / driver timeoutに依存する。deadline checkpointは遅れた成功の採用を防ぐもので、任意のblocking呼出しを正確な時刻に強制停止するものではない。残り予算をI/O timeoutへ伝播することとRebuild全工程のhard timeout／cleanupは後続controller接続で検証する。

## 検証と後続

仮想clockのスケジューリング試験は睡眠を使わず、retryでのdeadline再起算なし、wait上限、期限境界、late result拒否、停止状態、未知例外を検証する。実PG lock / leader喪失を組み合わせ、実PG / Neo4jでdrain後もpointer / flag / fatalを保持すること、適用中の期限到達でAPPLIEDやDEADを捏造しないことを確認する。スケジューリングdoubleは実Graph成功の証拠として扱わない。

controller全体の開始・heartbeat・構築・検証・公開・終了／failure cleanup、残り予算のI/O timeout伝播、Restore / crash復旧、管理role / CLIは後続。drain自身はcontrol flagを解除せずgenerationを公開しない。新規SQL・migration・HTTP / Agent公開なし。LogiScopeコード再利用なし。
