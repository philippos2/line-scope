# PostgreSQL検索接続の分離基盤

日付: 2026-10-10。作業ブランチ: feat/read-database-connection。
開始点: d198058。PR #89の試験変更に依存し、記録時点で同PRはOPEN。POによるmergeを代行しない。

## 変更と境界

Settingsへ秘密非表示のoptional read_dsn / LINESCOPE_READ_DSNを追加。Database.for_readsで検索接続を選び、ReadToolsから利用する。通常HTTP Read・ToolDispatcher経由の検索に適用し、Prepareの要求保存、Approval / Execute、migration、既存lock / rollback / Snapshot / Outbox処理は変更しない。新SQL・Core依存は追加していない。

READ_DSN明示時に接続が失敗しても更新DSNへ再接続しない。未設定時の既存動作は移行用互換性として残す。したがってDB role分離やpolicy適合が完成したとは扱わない。設定された接続に実際のSELECT限定権限があるか、この実装だけでは保証しない。正本の接続・権限方針はoperations §14とarchitecture §15。

## 検証

追加7ケース: 不正設定4、環境設定と秘密repr1、異なるテスト用schemaで接続選択と更新接続非変更1、検索接続失敗でprivileged fallbackしない実PostgreSQL試験1。接続選択試験の異なるschemaはテスト用識別手段で、別業務正本を導入する仕様ではない。

Dockerの関連試験181 passed / 1 warning。全体回帰2214 passed / 1 skipped / 1 warning（146.83秒、exit code 0）。ruff check / format --check（124ファイル）、git diff --check成功。既知Starlette警告。テストfixtureの初回schema名誤りを修正して再実行した。前回と同じlogging output failed診断は全体回帰後にも出ており、別メモの未調査事項を維持する。

## 残課題・再開地点

Composeとcredential生成は未変更。DB role provision / grant、既存DBの非破壊upgrade、実roleでのmutation / DDL拒否、default privileges、監査表の閲覧制限、migration / runtime分離が次の工程。Prepare内部の読み取りを分ける場合も、保存処理と重要transactionを壊さない別設計が必要。Core導入、Graph workerも未完了。

ローカルcheckpointで保存。PR #89のmerge確認後にmainを更新し、この差分のPR化を行う。全体回帰成功をGitHub CI成功と混同しない。参考ログメモは正式仕様として取り込まず独立して保存する。
