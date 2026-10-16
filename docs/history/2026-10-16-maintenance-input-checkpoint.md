# 対応計画・故障履歴の実装checkpoint

## 再開時点と判断

- #249は開発者がmerge済み。mainをedafee554df63104461217ee48f6908829d0ce03へff-only更新した。
- #249 headとmainのtree一致を確認し、merge済みfeat/safety-inputsを削除した。他の退避・worktree・stashは変更していない。
- #249最終検証：CI 38826472199成功、Backend 3,882成功・1skip。実Qwen／実ブラウザの3回目は成功。詳細はPR #249本文。所有する試験環境と関連imageを片付け、WIP / Draft解除後に引き渡した。
- 次工程の仕様案を会話で提示し、開発者から「それで良いから」と明示回答を得た。PO-B05・B06・対応計画／故障情報B07、および共通評価期間・交換費算入の範囲を正本へ反映した。PO-B08は未決定のまま。

## 採用した業務ルール

- 修理・交換・暫定対応を区別し、調達待ち・作業・停止時間を別に登録する。
- 次回保全は将来のPLANNED予定の最早開始から選び、同時刻の候補は利用者が選択する。停止は保全予定として扱い、設備状態を自動変更しない。
- 共通費用評価期間と交換費の算入／非算入を明示する。期間外費用を黙って加除しない。
- 故障・修理・過去停止損失を出典・過去事象期間付きでPGへ登録し、指定期間で参照する。STOPPEDから原因や将来故障率を推測しない。
- 閲覧は保全・生産管理・工場管理。要求は工場管理者、承認は別の工場管理者、確定は要求者。既存保全予定・実績の権限を変更しない。

## 実装・検証状況

- 作業branch：feat/maintenance-decision-inputs。
- MaintenanceInput、Snapshot v5、migration 011、SQLAlchemy Core、共通承認／確定経路、実DB role、検索・取得HTTPとAgent Readを追加。
- 新しい画面で分類・期間・時間・費用・出典を登録／訂正し、次回保全候補を関連付け、共通Actionで承認・確定する。自動状態変更はない。
- 新規pytestは展開20件（domain 8、PG/HTTP 12）。既存DB role試験を拡張。無条件の直積やFrontend Unit caseの機械追加はしない。
- 初期試験で移植時のHTTP期待値の誤りを検出・修正。新規の業務拒否は既存のBUSINESS_RULE_VIOLATION=422に合わせて確認する。これは実装の認可を緩める変更ではない。
- Dockerの書込userとhost権限が不一致のため最初のmount上ruff修正が失敗。host uid 1000のuserを指定して実行する。最新backend/scriptsをmountした結果だけを検証記録に採用する。
- 関連121件成功（12.05秒）。FrontendのDocker内lint・型チェック・format・build成功。既存のStarlette/httpx警告と終了時logging出力失敗メッセージあり。
- 全体回帰は3,901成功・1skip・1失敗（362.08秒）。失敗はmigration後のtable一覧の期待値にmaintenance_inputを追加し忘れたこと。期待集合へ新tableを追加し、該当schema suite 29件が成功（2.53秒）。
- 実Qwen・実ブラウザの初回は設備検索でAGENT_LIMIT_REACHED、登録前に停止。2回目は実設備検索が成功したが検証scriptのselect指定が不一致で停止した。既存安全入力と同じcombobox指定へ修正した。
- 3回目はPASS。交換案CREATE→自己承認拒否→別manager承認→要求者Execute→実モデルget_maintenance_input参照→UNKNOWN費用／停止時間へのUPDATE（version 2）→故障履歴への分類訂正（version 3・過去損失120,000 JPY）を確認した。調達336時間、作業4時間、停止2時間、既知計画直接費小計30,000 JPYを分離して確認した。
- 実ブラウザで1440 / 768 / 390pxの非overflow、出典HTMLの非実行、storage非保存、接続解除時の消去を確認。390pxのスクリーンショットも確認した。一般LLM品質・全Business Scenarioの受入合格には拡大しない。初回時間切れの原因は未特定。
- 所有する試験Compose環境・volumeを片付け、関連image tagを削除した。継続デモ・他projectの環境は維持した。
- 最新headのCI確認・最終引渡し結果は[PR #250](https://github.com/philippos2/line-scope/pull/250)へ記録する。CI確認前はDraft・【WIP】を維持する。

## 次の再開点

- 関連試験・画面checkの結果を確認し、必要な修正後に全体回帰と実ブラウザを順番に実行する。同一DBにsuiteを並列投入しない。
- PRは登録から画面・Agent・業務経路までまとめ、WIP / Draftで作成する。force-pushせず、最新headのCI・結果記録・片付け完了後に引き渡す。mergeは開発者が行う。
- 全体約80%（75〜85%）、#249後の残り概算4〜9 PR（この作業を含む）。安全の代表経路完了を反映した主観見積りであり、作業中の計画・履歴は完了として加算していない。
