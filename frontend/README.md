# Frontend（後続フェーズ）

LineScopeのFrontendはBackendと同じリポジトリで管理し、サーバサイド完成後に実装する。
現在は方針文書のみで、画面コード・build設定・packageは追加していない。
仕様の正本は[19文書](../docs/deliverables.md)、UI方向性は[要件 §13](../docs/requirements/requirements.md#13-後続frontendフェーズ)。

## オペレーション・コンソール

Graphを主役としてObject / Graph / Evidence / Actionがつながるワークスペースを目指す。
AIP Analystの見た目・機能の忠実な再現ではなく、LineScopeの製造業務と承認境界を画面で説明する。

| 領域 | 設計候補 |
|---|---|
| 左 Object Explorer | Equipment / Process / ProductionOperation / Product / InfrastructureResourceの検索・選択 |
| 中央 Graph Canvas | 選択Objectの依存展開、エッジ種別、直接/間接影響、Tool Evidenceにある経路の強調 |
| 右 Agent Panel | 自然言語問い合わせ、回答、Evidence、公開Tool Trace、Graphへの表示連携 |
| 下部 Action Drawer | canonical Snapshot、before / proposed、承認主体・状態、確定結果・現在値、許可された監査履歴 |
| 上部 Status Bar | 検証済みGraph同期状態・正本接続・RAG準備状態・採用Agent情報 |

初回UIはExplorer / Graph / Agent Panelを優先する候補。Action Drawerは次の反復へ分ける。
Graph 50% / Object 20% / Agent 30%はデスクトップ設計の出発点とし、実データ・画面幅で検証する。
Object DetailをGraph選択と連動させ、正本項目・state version・観測時刻・許可された操作を示す。

## ヒーローデモ候補

権限のある利用者が「M-204が停止した場合の影響を調べて」と問い、Toolの代表経路を中央Graphで強調する。
設備から工程・製品へ至る直接/間接影響と根拠を同時に示す。IDや経路は実seed・正本・Tool出力に一致するものを使用する。
到達関係から生産停止を無条件に断定せず、必要性・代替・探索完全性に応じた表現にする。

## 視覚と技術の候補

charcoal / graphite、dark navy、off-white、細いborderを基調に、色を状態・選択・影響へ使う。
CURRENT緑 / LAGGING黄 / ERROR赤 / REBUILDING青を文字・記号と併用し、色だけに依存しない。
React + TypeScript + React Flowを候補とし、TanStack QueryとContext / Zustandの必要性も後続設計で評価する。
現時点ではframework、依存version、画面の完成仕様を確定しない。

## 仕様との整合

- Graph非CURRENTや不完全探索を正常な最新分析として扱わない。保存方向と影響探索方向を区別する。
- 現場ロールは通常Read中心。Graph分析・更新・承認・履歴の権限はサーバが最終判断する。
- RUNNING / STOPPED / UNDER_MAINTENANCE / UNKNOWNを使い、DEGRADED / MAINTENANCEや未定義Locationをモデルへ追加しない。
- AI Recommendation、Human Approval、requesterのExecuteを分ける。canonical Snapshotと確定after / current valueを混同しない。
- Tool Traceは公開可能な構造化結果に限り、内部推論・credential・SQL/Cypherを表示しない。
- 状態バーのReadyやmodel名は実設定・確認結果に基づく。Qwen等は未選定。

後続UI設計では画面レイアウト・Object選択状態・API/Toolの対応・ロール別表示・アクセシビリティ・UI受入基準を具体化する。
Explorerに必要な一覧/検索やGraph描画に必要な取得範囲も、その時点のBackend契約と照合する。今回の案を理由に未定義APIを追加しない。

## 外部レビュー

POからChatGPT / Claude / Geminiの支援を受けられる。最初のレイアウト案がまとまった段階で、視覚的な優先順位・情報密度・操作性と、業務フロー・権限・承認境界のレビュー依頼を検討する。
必要なときはCodexから案と具体的なレビュー観点を提示して依頼する。外部AIの提案をそのまま仕様・実装へ採用せず、19文書との整合を確認する。
