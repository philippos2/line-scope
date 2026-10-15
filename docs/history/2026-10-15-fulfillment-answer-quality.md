# 代替・SPOFの説明品質

仕様正本ではなく作業記録。

## 再開地点と目的

#242のmerge（501df1c）を確認しmainをff-only更新。正式入力のPO-B01・B02・B07案は未承認のまま維持し、独立して進められるGraph説明品質を選択した。業務入力の未決定ルールや新しい権限は追加していない。

単一の代替・SPOF Tool結果をAgent層で日本語要約する。代替は除外後の構造判定と一段代替のavailability、SPOFは対象・候補の組ごとの独立除外判定を表示。完全探索と判定未確定を分け、UNKNOWN・空SPOF・過去時点・参照失敗・未評価次元を保持する。元の対象別判定・理由・経路・Evidenceを変更せず、追加DB参照も行わない。複数Graph分析は対象外で、既存の自由説明経路を維持する。

## 検証

- backend-verification / test-designの手順を適用。追加は17件（代表判定6、不完全＋過去2、空候補1、非対応結果4、Agent配線2、既知availability2）。直積を生成せず、境界と意味の異なる同値クラスを選定。
- Docker内の関連Agent・実PG/Neo4j API・Business Scenario試験: 69 passed、5.93秒。既存Starlette警告1件、既存logging出力失敗メッセージあり。
- 最初はno-depsでDB依存テストも選んでしまい52 passed / DB未起動による1 error。専用DBを起動して上記の全件を再実行し成功。テストの削除・弱体化はしていない。
- formatterの初回mount先を誤りコンテナ内の書込権限エラー。正しい/workspaceをmountして修正。Docker内ruff check成功、format checkは340ファイル成功。

## 残件

一般LLM品質閾値・モデルdigest固定・繰返し条件、複数Graph説明、通常Read/RAGの一般品質は未受入。正式業務入力とGolden受入はPO判断を含む別工程。紹介動画は保留を維持する。

## 実モデル確認

モデルqwen3:30b-a3b-instruct-2507-q4_K_M、既定context 16384 / temperature 0 / num_predict 700 / Agent予算60秒。各環境は初期seedとRebuildを実行した実PG / Neo4j専用Compose。明示のwarm/cold統制やdigest固定はしていない。

初回はDemoFixtureのDEMO_DECISION_MOCK=trueを残したため、代替質問がデモ判断支援ルートへ入りHTTP 200 partial、Graph Tool結果なしとなった。SPOFはHTTP 503 AGENT_LIMIT_REACHED。前者は試験条件の不備、後者の原因は未特定であり、後続成功によって解消済みとはしない。初回記録は/tmp/linescope-fulfillment-quality-report.json（0600）に保持。

デモ判断支援を明示無効にした専用環境で再確認。89f8bfb（開始時clean）の実装を使い、既存verify_graph_agent.validate_fulfillment_resultで対象・候補・除外、CURRENT / 完全性 / 判定、未評価次元、8代表経路、状態versionとEvidenceを照合した。代替・SPOFともHTTP 200 / 構造化probe PASS。代替は除外後成立1件・代替利用可能1件、SPOFは指定組の非候補1件。両回答をレビューし、実停止・能力・安全・経済は未評価、SPOFは故障原因の確定でない説明を確認した。名前だけの対象解決や一般品質の受入ではない。

再確認記録は/tmp/linescope-fulfillment-quality-read-only-report.json（0600）。両probeの専用Composeはvolumeまで削除済み。ローカル関連試験専用環境linescope-fulfillment-qualityも片付け済み。継続デモへはデプロイしていない。

## ロードマップ表示の修正

開発者から、ガントチャート上は残作業がないように見えるとの指摘があった。旧図が代表UI工程だけを描いていたことが原因であり、正式入力のモック置換・PO判断・全BS / Golden・LLM/検索品質・運用復旧受入を含む工程図へ変更した。0〜2 PRはUI修正予備だけで、製品全体の残工数ではない旨も明記。新しい業務規則の承認や機能の対象外化は行っていない。

開発者の残PR数の質問に対し、#243を除く本体残工程を12〜20 PR（中心16前後）と暫定見積もりしroadmapへ内訳を記録した。機能ごとの画面・API・保存・検証を含み、細かな内部部品PRを数えない。PO未決定と受入結果による変動を明示。紹介動画は本体完成後の最終工程に分け、見積もりへ含めない。
