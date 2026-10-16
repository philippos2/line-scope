# 比較の条件・費用差・履歴根拠の統合

## 再開と対象

- PR #252のmergeを確認し、mainを`7bf8c1db08895eceeae127d1839e0cf36a73b9a2`へff-only更新。
- Squash後のtree一致を確認して旧feature branchを削除。退避・他worktree・push済み履歴は変更しない。
- 作業branchは`feat/business-acceptance`。

## 今回の実装

- 正式能力入力のProductと対象設備から実Graphの代替構造を取得し、下流・上流と世代を照合。
- 一段代替候補・現在の利用可能性・製品別能力・選択安全条件・品質未確認を別々に比較へ表示。
- 安全宣言は選択範囲に限定。停止必須が優先し、未知との混在を条件付き許容としない。
- 修理案の独立加算可能な停止損失率と小計を提示。異なる停止時間から同時の完全損失率を作らない。
- 共通期間の既知な二案について、登録費用の差と低い費用の案を表示。未算出案・除外案を残し、推奨や実運転許可にしない。
- 選択した故障／修理履歴・過去損失、六つのリスク次元の事実と不足を画面・Agent説明へ接続。
- DB schema・Snapshot・承認／確定・権限は変更しない。

## ガントチャートの修正

- 開発者から工程3に棒がなく工程4へ飛んでいるとの指摘。前回は総合受入の幅を縮め、後続の配置を直していなかった。
- #252 merge後の最大6枠へ再配置。工程1〜2=総合受入、3=条件付き安全対応、4=条件付き計画／履歴対応、5〜6=運用復旧。
- 条件付き枠が不要なら後続を前へ詰める。インフラは完了欄へ移し、独立PRを無条件に増やす計画とはしない。
- Chromiumで`/tmp/linescope-roadmap-gantt.png`へ描画し、空白工程と重なりがないことを目視確認。

## 検証と判明事項

- 新規試験はdomain 14＋API 2＋Agent Tool提示3=19ケース。独立した境界・代表値を選び、直積は作らない。
- 初回関連試験は45成功・1失敗。追加fixtureの状態table名誤りを修正し、次は53成功（14.46秒）。その後、停止時間の異なる損失率の境界1件とAgent提示3件を追加。
- 初回の実ブラウザは登録・費用差・代替条件・履歴表示を通過したが、実モデルがAGENT_LIMIT_REACHEDで失敗。
- 完全な選択JSONが元messageに明示された比較だけ、モデルへの提示をcompare_registered_inputsへ限定。通常／不正入力は既存Read Tool集合を維持する。元入力との一致・時刻・権限の実行時検証と60秒制限は維持。
- 最終関連試験は225成功（14.57秒）。新規19ケースを含む。Ruff check／formatは374ファイル成功、Frontend lint・型・format・buildも成功。
- 実モデル・ブラウザの再実行はPASS。登録・別管理者承認・requester確定後、損失率200000 JPY/hour、費用差1884000 JPY、構造AVAILABLE／能力不足30、履歴の過去損失120000 JPYと非加算、Agent参照を確認。1440／768／390幅のoverflowなし、HTML非実行、storage非保存、接続解除時の消去も確認。
- モデルは導入済み`qwen3:30b-a3b-instruct-2507-q4_K_M`。稼働モデルのdigestは`19e422b0231392335cfc49cfd172de7034bb1aeabb08aa307cce745c60b272fe`。再実行の成功はcold start性能や一般LLM品質の合格を意味しない。モデルのunload・download・制限時間変更は行わない。
- 試験Compose、2回分のブラウザ環境、図の描画containerを片付け、所有image tag 11件を削除。継続デモや他作業のimageは変更しない。
- 最終headのCI・件数・時間・収集hashとready化の記録はPR本文に保持する。初回の失敗を一般品質の成功で隠さない。
- ログ：`/tmp/linescope-business-tests3.log`、`/tmp/linescope-business-ruff-final.log`、`/tmp/linescope-business-frontend-final.log`、`/tmp/linescope-business-browser.log`（初回失敗）、`/tmp/linescope-business-browser2.log`（再実行PASS）。

## 次に必要なこと

- BS-03の150日：現行の正式入力には日次稼働条件と交換で損失が解消する仮定がない。480000 JPYの累積損失や既知二案の費用差と、150日の正式入力算出を区別する。受入基準は削除しない。
- Golden専用fixture全条件、全BSの自然言語経路、一般LLM／検索品質の受入。今回の代表経路を全体合格とはしない。
- 完成版schemaの運用・バックアップ復元・再構築・障害復旧。
