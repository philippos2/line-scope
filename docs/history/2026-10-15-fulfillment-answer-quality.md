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
