---
name: frontend-architecture
description: LineScopeのReact component、表示モデル、API client、Graph、Evidence、Action画面の責務境界・依存方向・認証情報の扱いを設計または変更するときに使う。
---

# Frontend architecture

[文書入口](../../../docs/deliverables.md)で対象事項の正本を選ぶ。[画面設計](../../../docs/design/frontend-console.md)と[API契約](../../../docs/implementation-design/api-tools.md)を参照する。開発者の指示とエンドユーザーの業務権限を区別する。

## 作業方法

- 問い合わせ→API→表示→次の操作を実コードで追い、React component、表示用変換、HTTP clientの責務を分ける。ComponentへDB SDK・業務計算・認可判定を持ち込まない。
- APIが返した値・経路・Evidenceを表示する。Graphで新たな依存探索や代替成立を判定せず、費用・能力・安全性をUIで推測しない。未知の業務ルールや必要な新APIは明示する。
- 非CURRENT、PARTIAL、不明、0、false、nullを無条件に同じ状態として表示しない。表示の上限や省略を明示し、取得時の結果と現在値を区別する。
- APIアクセスは固定の同一origin窓口へ集約する。tokenをURL・storage・ログへ保存せず、接続解除時に消去する。遅延responseが解除後の画面を復元しないことを確認する。
- 外部文字列・文書抜粋はHTMLとして実行しない。出典URIやmetadataを認可の根拠にしない。外部通信が必要なら、その目的・送信情報・許可対象を確認する。
- Analysis、Prepare、Approval、Executeの操作主体と状態を分ける。LLMに確定操作を許可しない。Snapshotの確定afterと最新currentを混同しない。
- 抽象化や追加libraryは具体的な変更負担を減らす場合に採用する。Middlewareの差し替えを理由に形式だけのlayerを増やさない。

## 管理されないアドホック実装・テストの禁止

[共通の設計規則](../backend-architecture/SKILL.md#管理されないアドホック実装テストの禁止)をFrontendにも適用する。特定の質問・設備・画面例だけに効く条件分岐や表示の特例で解決しない。要件と共通の状態・データ契約から表示と操作を設計する。必要な暫定対応は理由・範囲・担当・終了条件を計画／台帳へ記録し、限界を表示する。設定化やComponentの共通化だけで一般化・統一ができたと判断しない。検証は[test-design](../test-design/SKILL.md#アドホックなテストの禁止)に従い、例題だけを通す試験や、実装から逆算した期待値を作らない。

## レビュー

Public contract、サーバの権限検証、UIの状態、読みやすさ・keyboard操作を確認する。取得できない情報を表示上の推測で埋めない。実装済み・mock・未確認を分けて報告する。PR運用は[CONTRIBUTING](../../../CONTRIBUTING.md)を参照し、ここで再定義しない。
