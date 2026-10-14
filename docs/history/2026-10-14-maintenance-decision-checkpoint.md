# 保全情報を対応判断へ接続するチェックポイント

これは再開用の作業記録であり、仕様正本ではない。仕様はdeliverables、残工程はroadmapを参照する。

- #218はmerge済み。基点mainは `6a5ba86`。
- 作業ブランチ `feat/maintenance-informed-decision`、commit `37202fd`、PR #219。
- 対応判断APIへ認証済みの設備別保全予定・実績とPostgreSQL Evidenceを接続。各最大100件、取得打切りと障害を明示。保全記録を故障／修理分類や将来予測へ昇格させない。
- 登録→Prepare→別ActorのApproval→requesterのExecute→比較結果への反映まで実PG/Neo4j API試験と専用Composeのcurlで確認。
- 関連回帰43件成功（追加7件）、4.36秒。lint・format315ファイル成功。実Embedding/Qdrantの引用と費用計算もsmoke成功。計算入力はmock、LLMは未使用。
- 各読取りはLATEST_PER_CALLであり、全体の同時snapshotではない。PO-B01〜08は未確定。空の保全実績から故障なし、最初の予定から次回保全を推測しない。
- 既存のStarlette/httpx警告と終了時logging output failedは未調査。

## 開発者の指示と次の区切り

PRを内部部品単位に細分化せず、入力から出力まで利用できる業務機能を単位にまとめる。今回も取得処理、結果への接続、認可／障害／上限、登録後の反映試験を一つのPRに含めた。PR数は進捗率の根拠にしない。

次は#219のmerge確認から再開する。正式データとmock、受入済みと未検証を分け、roadmapの残工程に沿って次の業務機能をまとめる。履歴・roadmap整理は機能PRと分離する。ガントチャートの見出し修正と履歴の保存方法は次の文書整理に残っている。

CI全成功：3703件成功・1skip。収集3704件・hash一致、選択1837＋1867＝3704。試験時間158.46秒／259.96秒。runtime・migration・PR title・集約checkも成功。所有する使い捨て環境は片付け済み。
