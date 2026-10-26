# 質問欄デモの仕切り直し

2026-10-26、開発者は#276を閉じ、最新mainから単一Draft PRで技術検証デモを完成する計画①〜⑧を承認した。観点判定はコードと固定データ、回答もコード。LLM候補/H6確認/H7選択UIと専用fixturesは移さない。

元PR最終headは2a54c466d2d7b072e792707b5d328e18c065d90d、mainは0ab829fef10cedfcef6dff973492893dd6b60b73。既存同名タグがないことと最終headを確認し、注釈付きarchive/pr276-20261026を作成・pushした。元枝・全コミット・H6/H7実測は保存し、書換え・force-push・削除はしない。

実装前にdocs/design/demo-question-chat.mdとscripts/fixtures/demo-question-cases.jsonへ、9観点・近い候補基準・保留4問・46問各3回の期待を固定した。旧fixtureから写したのは質問原文だけで、旧ラベルや結果を新成功へ変更しない。旧H6の58/63・15/18、誤受理5=不適切確認5（同じ応答）、口語取りこぼし3・UNVERIFIABLE0、H7の記録は元タグ/PRへ保存する。

移植はe13ac9cの検索、057e261/1053c04/d879f68の取得・回答・Evidenceの必要部分に限る。コミット全体をcherry-pickせず、H6/LLM依存を切って移す。作業中の新PRと元PRに相互参照を残す。
