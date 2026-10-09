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

## 保全予定UPDATE Snapshotチェックポイント

2026-10-09、PR #9 merge後、api-tools §16に従い保全予定UPDATEのSnapshot構築・再読込み検証を追加した。変更可能な3項目、全業務項目・version、業務キー、UTC日時・期間、一要求一カテゴリを検証する。Docker内で333テスト（追加40）とlint/format成功。AC-07 / T-R03のhash・schema境界、T-R07のカテゴリ拒否部分を検証した。Prepare・権限・保存・Approval / Execute、CREATEと他カテゴリは後続。仕様正本の変更・LogiScopeコードの再利用はない。

## 保全CREATE Snapshotチェックポイント

2026-10-09、PR #10 merge後、保全予定・保全実績CREATEのSnapshot生成・保存形式検証を追加した。サーバ生成ID、明示NULL、version=1、必須業務値と任意計画IDを固定し、予定・実績を同じMAINTENANCEカテゴリとして扱う。Docker内で370テスト（追加37）、lint/format成功。T-R03 / R07 / R21のSnapshot境界に対応する。参照先存在・設備一致・DB一意性・Prepare retry永続化・権限・Approval / Executeは後続。仕様正本の変更・LogiScopeコードの再利用はない。

## ProductionOperation予定UPDATE Snapshotチェックポイント

2026-10-09、PR #11 merge後、requirements §12 / api-tools §16に従い生産作業の予定UPDATE Snapshotを追加した。予定状態・開始・終了、全業務項目、期間・version、変更不可項目、監査時刻除外と保存形式を検証する。Docker内で414テスト（追加44）、lint/format成功。T-R03 / R07 / R21のSnapshot境界を検証。設備割当期間置換、正本取得・権限・保存・Prepare / Approval / Executeは後続。仕様正本の変更・LogiScopeコードの再利用はない。

## 設備割当期間置換・差分生成チェックポイント

2026-10-09、PR #12 merge後、domain-model §15.2に従い半開期間の設備集合置換を純粋な差分生成として実装した。期間外保持、不要分割の回避、空集合・明示NULL無期限、同業務キーactive / inactive行再利用、各Targetのbefore / after・version・IDを検証する。Docker内457テスト（追加43、うち1件で1,008区間組合せを時点評価）、lint/format成功。T-R08の区間差分部分に対応する。親version・全active集合のSnapshot固定、Snapshot統合、正本取得・FK/Graph制約・権限・DB保存・ロック・全rollbackは後続。仕様正本の変更・LogiScopeコードの再利用はない。

## ProductionOperation・割当Snapshot統合チェックポイント

2026-10-09、PR #13 merge後、予定値と設備割当差分を一つのPRODUCTION_OPERATION Snapshotへ統合した。親version増分1、全active割当のbefore / after固定、各差分のbefore照合とafter集合再現、複数親・ID重複・孤立差分の拒否を実装。保存形式equipment_assignmentsをdata-model §12に固定し、既存Transaction要件の検証手順とT-R08を補足した。業務意味・権限・承認ルールは変更していない。Docker内491テスト（追加34）、lint/format成功。正本の一貫した取得・Execute時再検証、DB保存・ロック・rollback・Graph/Outbox・権限・Approvalは後続。LogiScopeコードの再利用はない。

## README・適用済みER図の整理

2026-10-09、利用者のREADME整理依頼を受け、PR #14 merge後の短い文書チェックポイントとして実施した。実装状況と試せるHTTP APIを明確にし、概要・構成・起動・curl・検証・資料の順に整理した。LogiScopeはREADMEの情報配置・導線だけを参考にし、コード・構成・業務仕様は再利用していない。data-model §13へ適用済み10テーブルのER図を追加し、SQL FKと多態的論理参照を区別した。ホスト開発の依存lock手順はoperations §11へ整理した。判断主体は、利用者が委任した優先順位・文書整理の範囲でCodex。

独立した一時Docker環境で認証付きhealth / readinessの200と認証なし401をcurlで検証し、検証用環境・volumeを削除した。ERの業務列・7本のFKをmigrationと照合し、構成図・ER図のMermaid構文と変更文書のローカルファイルリンクを検証した。実装コード・設定・業務仕様の変更はなく、既存491テストのローカル再実行は省略する。PR CIで全テスト・migrationを検証する。残課題はDependencyRelation Snapshot、Prepare / Approval / Execute、Graph / Outbox、RAG / Agentなどのバックエンド実装で、Frontendはその完了後に進める。

## DependencyRelation Snapshotチェックポイント

2026-10-09、PR #15 merge後、DependencyRelationのCREATE / UPDATE / DISABLE Target構築とCanonical Snapshot保存形式の検証を追加した。endpoint型表・required未使用種別のfalse要求、明示NULL期間、現在versionと増分、ID固定、無効化・非変更拒否、同カテゴリ複数Targetを検証する。業務キー変更を許す既存要件に従いafterキーをTargetへ固定し旧キーをbeforeに保持する技術判断をCodexが行い、data-model §12とapi-tools §16へ必要な保存形式・入力補足を反映した。業務の関係意味・権限・承認条件は変更していない。

Docker内552テスト（追加61）、lint/format成功。独立した型表に基づく400組合せのSnapshot検証と350組合せのPostgreSQL CHECK照合、再計算hash付きschema改変の拒否、業務キー交換を検証した。T-R03 / R07のSnapshot・カテゴリ境界に対応し、AC全体の完了とは扱わない。正本全体のendpoint存在・active、期間重複・循環・最終一意性、Prepare・永続化・権限・Approval / Execute・Graph / Outboxは後続。LogiScopeコードの再利用はない。
