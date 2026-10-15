# 正式経済入力の画面・Agent接続

## 再開地点と範囲

開発者による#246 merge（0e57c67）を確認し、mainをff-onlyで更新した。経済入力の正式化の後続として、設備名・コード／入力コード検索、選択した登録入力の表示、フォームによる登録・訂正Prepare、既存Actionの別manager承認・requester確定、Agent Readへ接続する。能力・安全・計画・故障履歴のPO判断は推測で補完しない。

## 実経路と境界

検索HTTP / ToolはEconomicInputsで同じ認可・引数検証を行い、query接続とbindしたCoreで正本候補を取得する。候補にpayloadを含めず、role・主体・filterに拘束したprocess-local cursorを使用する。IDを明示選択してgetすると既存サーバ計算・観測日時・versionを返す。Agentには検索・取得だけを公開し、新しいPrepare / Approval / Executeは公開しない。

M-204と比較語を含む正式経済入力の質問が既存モック比較へ流れる条件を修正。要約は単一入力のサーバ計算から構築し、候補検索のみ／複数入力では計算済み・合算済みと説明しない。

UIは検索・編集・表示を分け、金額や時間を計算しない。未知nullと十進文字列0を維持。独立性・網羅性を自動肯定しない。Prepareの正規化前フォーム内容が同じ再送は同じretry keyを使い、自動再送しない。保存要求IDを既存Actionへ渡し、サーバSnapshotの承認・確定を分離する。解除時はunmount / AbortSignalで取得結果・editor・遅延応答を消去する。

## 試験計画と途中結果

当初Backend 10・Frontend 4件を予定。候補のみ／複数取得の要約と不正payload拒否を補い、追加予定は展開後Backend 12・Frontend 5の計17件。全直積は作らず認可・cursor・既知の入力境界・状態遷移を選ぶ。実ブラウザの代表業務経路を別に確認する。

初回の関連Backend 80件は78成功・2失敗。失敗はテスト側で権限拒否応答のanswer=nullを文字列として検査した点と、既存Tool数19の期待値を新規2 Tool分更新し忘れた点。修正後80件成功（5.25秒）。初回Frontend 26件は24成功・2失敗で、新規試験のcleanup不足を直して26件成功。その後不正payload拒否の1件を追加し27件成功。追加の型検証はTypeScriptのalias後の型絞り込みを明示して修正した。

初回実ブラウザは既存4カテゴリと拒否・引用まで通過し、新規経済入力工程で失敗。旧probeは工程名だけで操作を識別できなかったため、秘密を出さない段階ラベルとerror先頭行を追加。修正後のimageを再構築して原因を確認する。旧imageの成功範囲を最終headの合格へ流用しない。

## 最終ローカル検証・実ブラウザ

Backend全体回帰は3840 passed / 1 failed / 1 skipped、358.44秒。失敗はGraphありのTool数の旧期待値24（追加後26）だけであり、期待値を更新した対象19件（検索・要約・Graph Tool）を再実行して全成功（2.69秒）。検索のInjection / LIKE確認には別設備の対照登録も置いた。skipは既存opt-in live LLM試験。新しい業務制約を省いたり既存assertionを削除したりして成功扱いにしない。最終head全件はCIで再確認する。

Frontendは27件成功（既存22＋新規5、1.82秒）。Docker内のlint / 型 / format / buildを確認した。Backend lintも成功。新規自動試験はBackend 12＋Frontend 5＝17件で想定どおり。

実ブラウザは5回目の専用確認でPASS。導入済みqwen3:30b-a3b-instruct-2507-q4_K_Mを使用し、モデル取得・自動fallback・Agentの60秒上限変更は行わない。初回は経済工程内の操作位置を記録できず失敗。2回目は初期設備検索でAGENT_LIMIT_REACHED（API約60秒）。3回目の経済専用確認も設備候補待ちで失敗し、その応答の詳細は取得できなかった。4回目にsearch_equipmentの成功・M-204候補を明示確認し、停止箇所が費用種別selectのラベル完全一致を要求した試験側の操作と判明した。選択肢本文を含むlabelへ完全一致せずcomboboxを指定する修正後、5回目は下記を通過した。

- 実モデルで設備候補を取得・選択し、フォームから3案の経済入力をPrepare。
- 元requesterの自己承認を拒否。別managerで保存Snapshotを読み直して承認し、元requesterへ戻ってExecute。
- 登録値を検索・選択し、修理見積1900000 JPY、交換総額不明、既知小計と出典を表示。出典のHTML風文字列を実行しない。
- 訂正フォームへ取得済み入力を読み込み、同じ登録IDを実モデルのget_economic_inputで参照。Agentの構造化結果・サーバ要約でも交換総額不明を保持。
- 1440 / 768 / 390pxで横overflowなし。接続解除で結果を消去し、browser storageに保存しない。

コマンドは `python3 scripts/verify_frontend_flow.py --docker-group docker --llm-model qwen3:30b-a3b-instruct-2507-q4_K_M --economic-only`。このoptionは経済経路専用のfixture初期化とbrowser probeを選び、無関係な比較・引用・4カテゴリの再確認を繰り返さない。既存の全画面probeは維持した。ここで確認したのは単一の登録経済入力の代表業務経路であり、一般LLM品質・全BS / Golden・全更新variantのUI受入ではない。専用ブラウザ環境は各回のfinallyで削除された。

## 次工程

このPRのmerge確認後、ロードマップ順に能力・需要・納期入力へ進む。PO-B03およびその情報のPO-B07は未確定であり、経済情報の権限を自動転用しない。CIの最終head・実測件数・cleanupはPR本文で追跡する。

## 最終レビューの入力上限修正

PR作成後のレビューで、検索文字列の長さ判定がstrip後の文字列に対して行われ、空白を含む入力全体の100文字上限と一致しない点を確認。入力全体の長さと非空判定を分け、storageへアクセスする前に拒否する境界試験を1件追加した。追加自動試験は最終的にBackend 13＋Frontend 5＝18件。新規境界＋要約の3件は0.58秒で成功し、Docker内lintも成功。既存test imageを利用したが、backend / scriptsを明示mountして修正後ソースを実行した。最終CIはこの追加コミットを対象に再確認する。
