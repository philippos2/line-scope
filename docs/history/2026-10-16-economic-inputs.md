# 経済・損失入力の正式化

## PO判断

2026-10-16、開発者が経済入力に必要なPO-B01・B02・B07の具体案を「それで良し」と了承。共通期間と稼働時間を明示、JPYで直接費／停止損失／劣化損失を区別、独立項目のみ加算、不明値を0にしない。閲覧は保全／生産管理／工場管理、要求は工場管理、承認は別の工場管理、確定は元requester。能力・安全・故障情報の権限や他のPO項目は未確定のまま。

## 実装範囲

最初のPRはHTTPによる登録／訂正Prepare、共通Approval / Execute、登録入力取得・決定論的費用計算を接続する。画面・Agent接続は経済工程の次のPR。全BS / Goldenの完了ではない。テストは展開後20件を予定（計算／正規化8、実DB・HTTP12）。全直積は生成せず境界・認可・既知の競合／原子性を選ぶ。既存共通approval / execute試験も回帰する。

## 設計と検証中の確認

- 直接HTTP入力のPrepareと既存のHumanApproval / HumanExecuteを接続。PostgreSQL正本、Snapshot v2、version、固定CREATE ID、retry hash、別管理者承認、監査・履歴・承認消費の原子性を維持する。Graph対象ではないためOutboxを生成しない。
- 金額／時間は十進文字列（整数15桁・小数6桁まで）、計算はDecimal precision 64。共通期間・明示稼働時間、案別費用項目、適用期間、出典、推定／確定、独立性・網羅性を承認対象へ含める。部分期間の按分・将来費用・安全／能力判定は補完しない。
- 初回20件はテスト側UUIDのJSON変換忘れと案順の添字間違いで13件失敗。修正後19件成功、残る再送ケースは時間上限違反の入力を使っていたため有効入力へ変更した。監査履歴カテゴリのDB CHECK拡張も追加した。
- 関連282件の初回回帰は281成功、1件は新テーブルを既存スキーマ一覧へ追加し忘れ。新migration・v2の許可を期待値へ明示し、未知versionの拒否は3で維持する。assertionの削除・弱体化は行わない。
- 制限付きDB role経路を含む再確認106件が成功（11.11秒）。新規テストは予定どおり展開後20件。全体回帰とCIは後述する。

## 責務・安全境界のレビュー

HTTP handlerはJSON/envelopeとservice呼出しだけを所有し、SQLや業務計算を追加しない。EconomicInputsがTrusted Contextの認可・正規化・Prepareの読取と要求保存を所有し、domain/economicsは純粋な入力検証と十進計算、core_economicsはbindしたCore queryを所有する。通常ReadはDatabase.for_readsへ接続し、接続障害から強いroleへfallbackしない。

共通HumanApproval / HumanExecuteからカテゴリhandlerへ接続する。Request / Approval lock後、設備FKと既存経済行を安定順にlockし、承認hash、before全体、version、現在role、期限を検証する。manager自己承認例外をECONOMIC_INPUTへ拡張しない。COMPLETED再送も経済情報の現在閲覧権限を確認し、floorへ変更された元requesterへのSnapshot公開を拒否する。

DB制約変更は追加migration 008だけに置き、過去migrationのchecksumを変えない。Snapshot v1の既存canonical値を維持し、v2と経済カテゴリを相互拘束する。JSONBはCoreをpsycopgで実行する際に明示adaptする。DDLのcatalog制約名だけは固定対象テーブルから選択し、PostgreSQLのformat %Iで引用する。経済情報はGraph関係ではないためGraph mutation lock / Outbox / Projectionを追加しない。

## ローカル最終検証

Docker内の全体回帰 `pytest -p no:cacheprovider backend/tests -q --durations=15` は3829 passed / 1 skipped、331.87秒。skipは既存のopt-in live LLM試験（LINESCOPE_LIVE_LLM_MODEL未設定）であり、このPRの実LLM受入は未実施。既存Starlette/httpx非推奨警告と終了時のlogging出力失敗が残るが、今回の新規失敗はない。最遅callはshard網羅確認2.10秒。新規20件を含め収集は3830件で、前回3810件から想定どおり増加した。

ruff check / format check成功（345ファイル）、git diff --check、正本文書の存在・SVG XMLを確認。使い捨てCompose projectはlinescope-economic-inputsであり、通常デモ環境には変更・volume削除を行わない。CIの最終hash・件数・片付け結果は本ブランチのPR本文で追跡する。次はmerge確認後、正式入力の検索・画面・Agent接続へ進む。
