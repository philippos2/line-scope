# ログ設計の改善検討メモ

日付: 2026-10-10。確認時点: `d198058`。
位置付け: POの依頼に基づく参考メモ。正式仕様・実装指示・採用決定ではない。既存の業務規則、API、Transaction、監査の意味を暗黙に変更しない。

## 目的と維持する方針

個人開発の規模では「失敗した場所」と「業務変更が確定したか」を追えることを優先する。ログ件数や収集製品を増やすこと自体を目的にしない。

- 運用ログはJSON標準出力。障害・拒否・処理時間・関連IDを追う。
- 業務監査はPostgreSQL。成功変更と同一Transactionに保存し、stdoutで代替しない。
- 分析Evidenceは既存の分析結果・正本参照で扱う。Snapshot、入力、回答全文を運用ログへ複製しない。
- 許可項目による秘匿、サーバ生成request_id、Docker容量制限を維持する。集中ログ基盤・APM・ログ検索UIの追加は当面不要という提案。

正本: [operations §13](../implementation-design/operations.md)、[data-model](../design/data-model.md)。

## 確認できた事実

- `backend/src/linescope/logging.py`はイベント・code・項目のallow-listと構造化例外診断を持ち、例外message / args / localsを出力しない。
- HTTP、Agent Tool、Approval、Execute、監査保存失敗にイベント出力がある。一方、operations §13.8には「DB監査とToolへの接続は未実装」という古い実装状況記述が残る。各経路の完了範囲を確認して更新する必要がある。
- ExecuteはDEPENDENCY_UNAVAILABLEをexecution.outcome_unknownとして記録する。接続前失敗・rollback確認済み・commit結果不明を区別する改善余地があるが、現状の分類が業務更新を誤らせるとの断定はしない。
- SafeHandlerはshutdown時のflush失敗でも固定診断をstderrへ出す。SQL試験追加後の全体回帰は2207 passed / 1 skipped / 1 warning、exit code 0だったが、終了後にlogging output failedの出力があった。原因は未調査。テストstreamの終了処理と実出力障害のどちらかを断定しない。

## 改善候補

### 変更確定と応答完了の分離

運用上、次の状態を区別できるようにする。正式なDB状態やAPI codeを追加する決定ではなく、内部ログの意味を整理する案。

| 状況 | 調査上の意味 |
|---|---|
| validation / 権限拒否 | 今回の業務変更なし |
| rollback確認済み | 今回の変更は未確定 |
| commit確認済み | 業務変更確定 |
| commit結果不明 | 正本の再確認が必要。成功・rollbackを断定しない |
| COMPLETED再送 | 既存結果の返却。追加更新なし |
| commit後の応答送信失敗 | 業務変更は確定していても利用者が応答を受け取れていない |

request_idは一要求、context_idは会話、tool_call_idは一呼出し、要求・承認IDは変更ライフサイクル、Outbox / generationは同期を関連付ける。相関IDを権限・冪等性の根拠にしない。workerは新しい実行IDと保存済み業務IDを使い、元HTTP IDを推測しない。

### 秘匿を維持した障害分類

第三者loggerの生メッセージを解禁せず、責任を持つアダプター境界で接続失敗・timeout・制約違反・provider応答不正等の固定分類を付ける案。既存codeと重複しない最小項目を検討する。SQL本文・bind値・認証情報・質問全文・provider生応答はDEBUGでも出さない。

### 出力失敗とhandlerのライフサイクル

handlerの所有者、終了時の解除・flush、閉じたstreamの扱いを確認する。同一出力障害の診断が大量に繰り返されない仕組みを検討する。ログ出力失敗で確定済みcommitやHTTP結果を変えず、再帰・大量retryを避ける。業務監査保存失敗は別扱いで、既存rollback規則を維持する。

## 推奨順序と検証

1. 全体試験終了後の出力失敗を再現し、handler / stream終了処理を確認。
2. operationsの実装状況を現状へ合わせる。実装済み・部分実装・未実装を区別。
3. Executeの障害段階と変更確定状態を調査し、必要最小限のログ分類案を具体化。
4. worker実装時に既存イベント契約を接続する。

検証候補: 秘密を含む例外の非露出、並行要求のContext分離、commit前成功ログの禁止、rollbackと結果不明の区別、再送の非重複、commit後応答失敗、出力障害時の業務結果維持、handler終了時の診断増殖防止。API経由の業務受入試験をログテストで代替しない。

このメモ作成ではプロダクションコード・設定・正式仕様を変更せず、追加テスト・原因調査を実行していない。改善候補は採用時に既存契約と整合を確認する。
