# P1：複数設備の影響と登録停止損失の実装

## 確定した判断

2026-10-18、開発者が同一製品・同一損失範囲は1回だけ計上し、独立加算可能な異なる範囲だけ合算する案を承認した。不一致・未登録・期間不一致では完全合計を出さず、まずJPY/hourの推定を実装する。正本はrequirements / domain-model / API / AC / transaction-designへ反映した。

## 変更

- EconomicInputの任意incident_lossesへ製品UUID・scope_key・率・独立性・出典・区分を登録。修理案内のSTOPPAGE項目とは別の根拠にした。
- 同一scopeの宣言を照合し、一致なら1回、不一致なら当該範囲全体を除外。入力不足・期間・探索不完全・状態の適用不明を完全合計に変換しない。
- 認可された読取API `POST /incidents/investigate` を追加。Applicationが既存ReadTools・GraphAnalysis・EconomicInputsを組み合わせ、HTTP handlerにはDB操作・業務計算を置かない。LLMへ新Toolや確定操作を追加していない。
- Snapshot v7とmigration 013を追加。before / afterのどちらかに新根拠があればv7。過去v2 / v6のcanonical形状は維持し、承認・version・retry・履歴・監査の共通制御を再利用した。
- 専用デモの初期Graphと正式入力9件（経済2、安全2、修理／交換4、能力1）を同じ管理transactionで投入。既存の名称・状態・version・入力payloadは再投入で上書きしない。初期管理データにApprovalや業務履歴を捏造しない。
- 共有P-100は12万円／時間、個別P-200は8万円／時間、P-300は5万円／時間の架空根拠。登録範囲の両設備停止時合計は25万円／時間。参考文書と専用環境の投入・読取手順を追加した。

## 検証

- 新規テストはP1全体で展開後20件。実装前の見込み18件から、互換Snapshotと承認経路の検証を含め20件へ変更すると報告した。全直積を生成していない。
- 新規20件：4.72秒で成功。最終コードで再実行も成功。
- 経済入力・Snapshot・承認・Golden・DB role・旧デモの関連回帰193件：22.26秒で成功。
- Docker内Ruff check成功、format checkは389ファイル成功。
- 最終Backendから配布runtime imageをbuildし、所有する使い捨てDBでmigration→seed-demo-incident→再投入を確認。正式入力9件、再投入の新規0件、読取API用selectionを確認した。
- ローカル試験は既存test imageへ変更後のBackendを明示mountして実行した。hostでBackendテスト・lintは実行していない。
- Starletteのhttpx非推奨警告1件と試験終了後のlogger出力失敗メッセージが残る。試験の失敗ではないが、ログに残し無警告とは報告しない。
- 最新headのCI・scope・required checks・片付けの結果はPR本文に追記する。

## 保持した境界と残項目

常設サービス・既存DB・volumeは変更していない。配布CLIの初期データとHTTPの実DB／実Graph経路を確認したが、この参考文書の実Embedding取込みや実UIからの一連操作は今回未実施。

P2で常設デモへの導入方法を確認し、Graphに隣接する金額要約、複数異常の入口、内訳・根拠、追加損失範囲を保持する編集、対応と変更後再取得を接続して実ブラウザ・実検索を確認する。P1 merge後の残工数はP2の1 PR＋必要な修正予備0〜1 PR。P1のAPI成功でUI受入やプロダクト完成を宣言しない。
