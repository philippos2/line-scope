# 文書レビュー・変更履歴

このディレクトリはLineScopeの文書レビュー、仕様判断、変更経緯を保存する。現在の仕様は[deliverables.md](../deliverables.md)が指定する19文書を正本とする。履歴にある過去の指摘・未決定事項を現在の仕様として扱わない。

## 2026-10-09

| 順序 | 記録 | 内容 |
|---|---|---|
| 1 | [初回レビュー](2026-10-09-review.md) | 19文書の理解、F-01〜F-05 / U-01〜U-20の指摘。初回レビュー時点の記録 |
| 2 | [文書修正・セルフレビュー報告](2026-10-09-documentation-update-report.md) | 利用者が採用した8業務方針、19文書への反映、全25項目の対応表、セルフレビューと持越し事項 |
| 3 | [実装前の最終確認](2026-10-09-preimplementation-check.md) | 追加伝言に基づく契約の細部の固定。利用者の停止指示で実装を停止 |
| 4 | [Backend基盤チェックポイント](2026-10-09-foundation-checkpoint.md) | 基盤だけの初回commit境界、技術構成の明記、先行実装の保全と残課題 |
| 5 | [業務スキーマチェックポイント](2026-10-09-domain-schema-checkpoint.md) | 10テーブル・DB制約の実装範囲、検証と後続課題 |
| 6 | [Docker実行基盤チェックポイント](2026-10-09-container-runtime-checkpoint.md) | コンテナ起動・テスト・CI、資格情報、検証と後続課題 |
| 7 | [ID参照Read Toolsチェックポイント](2026-10-09-read-tools-checkpoint.md) | 認証Context、内部Read 9種、非変更・期間境界・エラーの検証 |
| 8 | [検索Read Toolsチェックポイント](2026-10-09-search-read-tools-checkpoint.md) | 検索4種、filter、署名cursor、SQLページングと検証 |

同日に複数の判断・修正があったため、上表の順序で読む。履歴は変更経緯の記録であり、変更前の全ファイルや逐行diffを復元できる版管理ではない。過去の全文Snapshotは保存していない。

以後の文書変更は、日付・変更理由・判断主体・対象文書・検証・残課題を記録する。既存記録は過去時点の内容として保持し、後続変更は別記録として関連付ける。

## 履歴整理

2026-10-09、利用者の依頼でdocs直下のreview.mdとdocumentation-update-report.mdを日付付きファイル名で本ディレクトリへ移動した。文書内の相対リンクとdeliverables.md / implementation-design/AGENTS.mdの参照を更新した。業務仕様は変更していない。

## LogiScope参照条件の明文化

同日、利用者がLogiScopeを一般化可能な実装パターンの参考として参照することを許可した。LineScopeの19文書を正とし、相違時はLineScopeを優先、そのままのコピー・継承は禁止、再利用対象と一般化の理由を適用前に説明する条件を[実装支援Agent規則 §10](../implementation-design/AGENTS.md)へ反映した。この変更で業務仕様を変更したり、実装を再開したりしていない。

## 後続UIの方向性

[Frontendコンソール方針](2026-10-09-frontend-console-direction.md)に、2026-10-09のPO提示案と既存仕様との整合条件を記録した。Frontendの実装開始を意味しない。

## Canonical JSON基盤チェックポイント

2026-10-09、PR #7 merge後にmainを更新し、`feat/canonical-json`でtransaction-design §15・20の直列化・hashとUUID/日時/ID集合の正規化を実装した。通常文字列・ordered arrayを保持し、禁止数値・重複key・surrogate・精度欠落を拒否する。Docker内で239テスト（既存180 + 追加59）とlint/format成功。AC-07 / T-R03の直列化境界に対応するが、Snapshot schema・Target構築・保存・承認照合は後続であり、受入基準全体の達成とは扱わない。仕様正本の変更・LogiScopeコードの再利用はない。

## 設備状態Snapshotチェックポイント

2026-10-09、PR #8 merge後にmainを更新し、設備状態UPDATEに限定してCanonical Snapshot v1の構築・再検証を実装した。transaction-design §15・20に従い、業務項目・version・ID・Target順序・重複・明示NULL・hashを検証する。Docker内で293テスト（既存239 + 追加54）とlint/format成功。AC-07 / T-R03のSnapshot境界に対応する部分実装であり、正本読込・権限・永続化・Approval / Execute・その他カテゴリは後続。READMEの実装状況だけを更新し、19文書の仕様正本は変更していない。LogiScopeコードの再利用はない。
