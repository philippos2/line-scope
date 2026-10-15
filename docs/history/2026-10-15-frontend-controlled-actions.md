# 承認付きAction画面の引き継ぎ記録

本書は非正本の作業履歴。仕様はrequirements / API / transaction / frontend-consoleを参照する。

## 開発者の指示と再開地点

- 会話消失後、docsとRepositoryから開発を再開。紹介動画は後回しにし、業務機能の完成を優先する。
- PRは内部部品ごとに細分化せず、利用できる業務経路を単位として適切な大きさにする。
- 進捗・判断・検証・未完了と次工程をRepositoryへ残す。
- 開発者はLineScopeを「オーソドックスなライトウェイト・オントロジーシステム」と位置付けている。型付きObject・属性・関係・業務意味・Actionを結ぶ構造として理解する。工場の意思決定支援はその業務目的。この発言だけでRDF / OWL等の新技術採用や既存契約変更を意味しない。
- #239 merge後、mainを752892fへff-only更新。merge済みPRのheadと一致する83ローカルブランチを削除。別worktree・確認保留の枝とstash20件は保持。

## 今回の変更

- 作業ブランチ: feat/frontend-controlled-actions。
- features/actionsへActionPanelを追加。明示指示からPrepare、要求IDによるGET、保存Snapshotのbefore / proposed / requester / hash / 状態 / 承認期限を表示する。
- Snapshot確認チェックと承認・拒否・実行を別操作とし、承認hashは保存GET結果を送る。接続解除して承認者／元requesterで読み直す。
- Prepareは同一指示の再送キーを保持。書き込みの自動再送なし。失敗後は操作用Snapshotを解除し再取得を要求する。
- 確定結果とExecute応答の現在値・観測時刻・partial warningを分離。Execute試行時は元の分析を古い結果と表示する。
- 接続画面へ移るとAction表示を破棄し、進行中のfetchをabortする。遅延応答は表示を復元しない。abortはサーバ更新の取消しを意味しないため、実行済みか不明な場合は要求IDで再取得する。
- BackendのAPI・認可・Snapshot・transaction契約は変更しない。API clientと画面・ブラウザ検証用credential配線のみ追加。

## 検証と保証範囲

- ケース選定: 既存実ブラウザ1フローを本人Prepare→別承認者Approval→本人Executeまで拡張。追加Unitは通信失敗後の再確認、unmount後の遅延Prepare応答、不確定なPrepare失敗後の旧要求IDクリアと同一キー再送の3件。直積生成なし。
- DockerでFrontend lint / typecheck / format / build成功。Unit 14件PASS（既存11＋追加3）。
- 専用Composeの実Chromium / HTTP / PostgreSQL / Neo4jで、比較・Graph・Evidence・F5接続復元・Prepare・承認者切替・Approval・requester切替・Execute・確定結果表示・接続解除を確認。費用等の入力はMOCK_FIXTURE、LLM未使用。
- 専用実ブラウザフローは2回PASS。旧要求IDクリアの追加修正後はFrontend静的検証・build・Unit14件で再確認。390pxのAction画面も目視確認。専用container / volume / network / 一時credentialを片付け済み。
- 不確定な新規Prepareでは入力欄の旧要求IDを消去する。要求IDが不明な場合は同じ指示・同じキーでの明示再送を案内する。
- 変更したPython検証scriptのruff check / formatをDocker内で確認。Backend実装は無変更。CI結果はPRへ記録し、CI成功前にmerge可能とは報告しない。

## 残件と次工程

- 現在状態変更の代表経路の確認であり、全UI受入・全BS / Goldenの合格ではない。
- UIでの全更新カテゴリ・拒否・期限切れ・version競合・Execute後の現在値取得失敗、実RAG引用、keyboard / 画面幅の操作受入を必要な範囲で追加確認する。
- Actionの確定結果はサーバ保存結果。画面を跨ぐ分析結果・再送キーの永続保存は追加していない。
- このPRのmerge確認後、UI仕上げ・業務受入・ガイド整備へ進む。正式業務入力はPO-B01〜08の確定が必要。動画は着手しない。
