# 文書レビュー・変更履歴

このディレクトリはLineScopeの文書レビュー、仕様判断、変更経緯を保存する。現在の仕様は[deliverables.md](../deliverables.md)が指定する文書群を正本とする。履歴にある過去の指摘・未決定事項を現在の仕様として扱わない。

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

## 更新要求・Target・承認DB基盤チェックポイント

2026-10-09、PR #16 merge後、migration 003でupdate_request / update_target / approvalの3テーブルを追加した。requester単位retry key、global idempotency key、一要求一承認、Target ID・業務キーの重複、FK、状態列挙・操作種別、CREATE / UPDATEのNULL・version形状、hash形状、完了結果・承認期限・消費時刻をDB制約で防御する。既存migrationは変更せず、READMEとdata-modelの適用状況だけ更新した。状態遷移・要求と承認の許容組・権限・canonical/hash照合・Snapshot不変性は後続サービス層の責務で、今回のDB列挙制約だけで承認／実行機能の完了とは扱わない。

Docker内606テスト（追加54）、lint/format成功。業務行保持を含む002から003へのupgrade、再migration、保存3行のround-trip、保存途中失敗の全rollback、並行同retry keyの一意性、user scopeと終端要求のkey保持、孤立FK拒否、30分期限・消費境界を検証した。T-R02 / R04のDB防御部分に対応し、Prepare・Approval API・Execute、履歴・Outboxは後続。利用者の既存方針に従い、merge済み3ブランチは各squash commitとのtree一致確認後にローカル削除した。元の先行実装stashは保持した。LogiScopeコードの再利用はない。

## 更新提案の内部保存・再送チェックポイント

2026-10-09、PR #17 merge後、ProposalStoreでCanonical Snapshot・全Target・PENDING Approvalを一Transactionで保存する内部処理を追加した。requesterはTrusted Execution Contextに拘束し、単一カテゴリの更新要求権限を保存前に確認する。同retry keyの同正規化入力hashは元のID・Snapshot・状態を返し、異入力はDUPLICATE_REQUEST。保存Targetからhashを再構成しRequest / Approvalのhash・requester・operation_type・状態組も照合する。新規要求の置換は、原子的な旧失効を後続実装するまで明示拒否する。仕様正本は変更せずREADMEの実装状況だけ更新した。

Docker内660テスト（追加54）、lint/format成功。同一／異入力の並行再送、CREATE ID・before / versionの再取得後も元Snapshot保持、terminal再送、owner scope、全カテゴリ×ロールの要求権限、複数Target一括保存、承認保存失敗の全rollbackと同キー再試行、保存データ改変・不正状態組拒否、実DBロックtimeout・エラー秘匿を検証した。T-R02 / R03 / R07の内部保存・再送・hash・要求権限部分に対応する。Prepare Tool / HTTP公開、正本の一貫した取得と業務検証、正規化入力hashの生成・Agent受付、要求置換、Approval / Execute、履歴・Graph / Outboxは後続。内部保存をPrepare全体の完了とは扱わない。LogiScopeコードの再利用はない。

## 業務判断支援ユースケース・Business Scenarioの追加

[追加・整合性レビュー記録](2026-10-09-business-scenarios-review.md)に、PO提示案の反映、補足ケース、PO判断待ち、数値・対応表・責務境界の確認を記録した。Business Scenarioの独立文書を追加し、正本文書は従来19から20文書になった。実装は停止したままであり、コード・設定は変更していない。

## 更新提案の原子的な置換チェックポイント

2026-10-09、PR #19 mergeと業務判断支援の文書整備後、利用者の指示でバックエンド実装を再開した。transaction-design §19の確定済み仕様に従い、ProposalStoreのsupersedes_update_request_idについて旧要求・承認のINVALIDATEDと新しいSnapshot / Target / PENDING Approval保存を一Transactionへ統合した。元requesterのみ、旧WAITING_APPROVAL / PENDINGまたはAPPROVED / APPROVEDのみ許可する。旧UpdateRequest → Approval順でrow lockを取得し、保存済みcanonical・Target・hash・状態組を照合する。新保存が失敗すれば旧失効もrollbackする。旧Snapshot・Target・承認hash・承認時刻は編集しない。

同retry keyの並行置換ではold lock待機後に保存済み新要求を再検索して元結果を返す。別keyで同旧要求を置換する競合は一要求だけ成功し、異内容の同keyはDUPLICATE_REQUEST。異なる旧要求に同keyを使う競合でも、失敗側の旧要求を失効させない。終端旧要求・非owner・現在要求権限不足・保存データ不整合を拒否し、実DBのRequest / Approval lock timeoutでRESOURCE_BUSYを返す。

Docker内の実PostgreSQLで688テスト成功（既存660 + 追加28）、ruff check / formatとgit diff --check成功。新承認INSERT時と旧承認UPDATE時の障害で、旧状態・時刻の保持、新行全rollback、同key再試行を検証した。置換後の旧retry、置換連鎖、新要求終端後再送も元SnapshotとIDを維持する。T-R03 / R05の置換・hash・終端保護、T-R02のowner scope・再送、AC-07 / 09 / 13 / 16の内部保存境界に対応する。受入基準全体の完了とは扱わない。

READMEの実装状況を更新した。仕様正本・migration・依存・Frontendは変更していない。Prepare Tool / HTTP、正本の一貫取得・業務制約検証、入力hash生成、Approval / Execute、監査・履歴・Graph / Outbox、Agentは後続。今回の失効は内部保存処理に限定し、一般の承認・失効APIや監査保存の完成を意味しない。PO-Bの未決定ルールは補完していない。LogiScopeコードの再利用はない。

## ログ設計の具体化

2026-10-09、POの依頼でログ設計を文書化した。既存NFR-06と監査表の設計を土台に、NFR-L01〜04、AC-L01〜04、T-L01〜07を追加し、operations §13へJSON標準出力・項目allowlist・相関Context・レベル・秘匿・容量制限・閲覧・段階導入を集約した。新しい正本文書は増やさず、deliverables、non-functional-requirements、acceptance-criteria、operations、test-plan、data-model、transaction-designを対応させた。

Python標準logging、Docker local driverの10m / 3 filesという小規模な方式はCodexの技術判断。新しい収集製品や業務状態は追加しない。業務監査のTransaction・閲覧境界を維持し、例外stackのmessage / args / locals等を出さない方式を指定した。保持は運用ログ容量とDB正本を分離し、DB監査の自動期限削除は導入しない。

文書間の正本責務、秘匿、commit / rollback / 結果不明、相関、既存監査との整合、ローカルリンク・fence、追加IDとAC → Test、git diffを確認する。コード・設定・依存・migrationは変更しておらず、ログ設計は未実装・試験未実行。基本実装は次の独立PRで、DB監査やOutbox等は対応する業務機能のPRで導入する方針を推奨する。

## プロダクトの範囲と要件の順序

2026-10-09、PR #21 merge後、POの依頼で「やること／やらないこと」をrequirements §9〜11へ整理した。既存の対象業務・スコープ外に、確定済みの意思決定支援要件を対応させた。Frontendをスコープ外の列挙から後続フェーズへ移し、PO判断待ち・未実装・下位設計の限界を対象外と区別した。READMEへ概要、deliverablesへ正本の責務を反映した。新機能やPO-Bの未定義規則は追加確定していない。

POが示した業務目的 → Use Case → 受入Scenario → Ontology / DB / API → Outbox / Projection / lockの順序と、Safety / SecurityのHard Constraintを除き上位意図を優先して下位再設計する方針をrequirements §2.1とdeliverablesへ明記した。既存設計を変更不可としたものではなく、変更は契約・AC・Testへ明示反映する。コード・設定・UIは変更せず、ログ基盤実装は別チェックポイントとした。

文書の目的・対象内外・フェーズ区分をUC-B / R-B / Scenarioと照合し、ローカルリンク・fence・既存ID保持・git diffを検証する。新しい試験を追加せず、文書PRのCIで既存Backend / migrationを検証する。

## 構造化ログ基盤チェックポイント

2026-10-09、PR #22 merge後、利用者の指示でログ設計operations §13の基本実装を行った。Python標準loggingのJSON Formatter / 安全なHandler / EventLoggerを追加し、イベント関数とFormatterの両方でallowlistを検証する。未知field・不正型・長い文字列を除外し、例外message / args / locals / source lineを出さず最大20 frameのmodule / function / lineだけを診断に使う。stdout書込・flush障害のstderr診断は固定文で、例外内容を再出力せずHTTP結果を変更しない。

HTTP middlewareをASGI境界へ移し、認証前からサーバ生成request_idを設定・finally解除する。async / threadpool、並行要求、キャンセル、送信開始後の障害を検証する。Response Envelopeと相関し、route template / code / outcome / status / duration / 認証済み主体を記録する。正常healthはDEBUG、拒否INFO、依存障害WARNING、内部障害ERROR。partialは完全成功と区別する。サービスの起動・終了も記録する。LOG_LEVELは厳格検証し、appごとのloggerでhandler重複・レベル干渉を防ぐ。

標準CLIではUvicorn raw access logを無効にし、既知依存loggerをWARNING以上へ制限する。第三者のmessage / args / 例外は固定runtime診断へ変換し、raw URL・SQL等を転送しない。独自ASGI起動の第三者logger設定は起動側の責務としてREADMEに明記した。runtime ComposeのAPI / migrate / PostgreSQLへlocal driverの10m / 3 filesを設定し、native PostgreSQLログとAPI JSONイベントを区別する。

Docker内の実PostgreSQLで722テスト成功（既存688 + 追加34）、ruff check / format、git diff --check成功。秘密入りの認証・URL / query / body / response・例外・直接logger出力、Context解除・並行16要求・threadpool、stack上限、raw access抑制、ログ出力障害、partial、送信開始後の失敗を検証した。独立した一時Docker環境でmigration / API起動、認証200 / 未認証401、ResponseとJSONのrequest_id一致、ログのcredential不在、全3サービスの実際のlogging driver / 容量設定を確認し、検証用環境とvolumeを削除した。

AC-L01 / 02 / 03 / 04とT-L01〜03 / 05 / 06のHTTP・共通出力部分に対応する。DB監査INSERT・commit / rollbackログ統合、Tool操作ログ、Outbox / Rebuildは後続であり、AC-L全体やT-L04 / 07の合格とは扱わない。業務仕様、PO-B、migration、依存、Frontendは変更しない。READMEとoperationsの実装状態を更新した。LogiScopeコードの再利用はない。
