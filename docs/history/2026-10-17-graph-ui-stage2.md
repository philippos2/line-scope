# Graph中心UI 第2段階：共通依存・代替・SPOF

## 目的と範囲

PR #256 merge後のmain `0b10a1b`から着手。ノード間の関係と影響範囲を調査するため、Graphの選択ノードを重要対象・除外対象・SPOF候補へ追加し、既存の3種類の分析を実行する。第3段階の判断・変更との連動は別工程とする。

## 実装判断

- LLMへの自然文指示で選択IDとTool引数を再生成させると、選択の欠落・探索条件の変更を防げない。「関係分析」厳密JSONを既存POST /agentで受け、既存AgentToolSessionへ直接渡す。
- 許可対象は5 Graph分析と5種類のノード属性Readのみ。汎用Tool HTTP endpointは作らず、Prepare・Approval・Executeを許可しない。認可・schema・時刻固定・deadline・Tool trace・Evidenceは既存処理を使う。
- サーバの共通依存候補、除外前後の構造、代替候補、重要対象とSPOF候補の組別判定を表示する。構造判定と業務上の停止・能力・安全・経済影響を分ける。
- 共通依存は重要対象2件以上。代替は重要対象と除外対象各1件以上。SPOFは必須上流からの自動探索か明示候補を選ぶ。明示候補空での実行を無効にし、省略と空配列を取り違えない。
- 根拠経路が空でも、サーバが返した重要対象・除外対象等のノードを表示する。関係は推測しない。

## 検証状況

- Backend関連単体テスト：35 passed / 1 skipped、0.32秒。skipは実DB未設定のintegration。認可拒否、厳密JSON・書込み拒否、UUID不正、選択IDと空候補配列・Evidenceの保持を含む。追加8ケース。
- Backend ruff check / format：成功（Docker、変更ソースを明示mount）。
- Frontend：最終ソースのcheck・追加1ケースを含むtest、常設ブラウザ検証、最新CIは作業中。過去headの結果を完了根拠としない。
- 常設デモのAPI・Frontendへ初版を反映。データ・volumeは保持。最終版の反映と確認は後続。

## 引継ぎと残工程

- 作業ブランチ：`feat/graph-structural-investigation`。
- 常設デモ：`linescope-browser-demo`。API 8000、Frontend 5173、認証情報は既存private env／tokenファイルを使い、本文・ログへ転記しない。
- 所有する検証image：`linescope-graph2-check-tests`、`linescope-graph2-frontend-check`、`linescope-graph2-browser-check`。検証ログは`.git/verification/service/graph2-*`。通常デモのvolumeを片付け対象にしない。
- 全体約80%、残り概算2 PR（本工程＋第3段階）。本工程の検証完了だけで100%としない。
