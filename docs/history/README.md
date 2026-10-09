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

## 材料・在庫・調達の境界メモ

POとの議論を[スコープ境界メモ](2026-10-09-material-scope-boundary.md)へ保存した。Supply Chain Operational IntelligenceとTOCへの将来の関心、決定・表現案・未決事項を分離した。既存要件・設計・受入基準は変更していない。

## 設備状態UPDATEの内部Prepareチェックポイント

2026-10-09、PR #23 merge後、POが承認した次工程としてEquipmentStatePrepareを実装した。trusted contextで設備状態要求権限を確認し、設備ID・明示状態だけを受け付ける。expected_versionの入力を拒否し、全対象の現在状態・versionをPostgreSQLの単一statement Snapshotで取得する。業務行の変更lockを取得せず、Snapshot構築後のversion変化は後続Approval / Executeで再検証する設計を維持する。

入力hashはTool名・正規化済み対象IDと状態・明示置換IDから構築する。対象集合はID順とし、UUID表記・集合順による揺れを除く。before / versionを入力hashへ含めない。Agent入力hashとretry keyはtrusted orchestratorから注入し、Agent hashの内容生成はこの層で行わない。保存済みキーは現在値読込前に入力hash照合・integrity検証して返す。要求権限を失った主体は再送でも拒否する。異内容キー、重複対象、変更なし対象、不存在対象は全体拒否し、状態行欠落・version増分不能は内部不整合とする。

既存ProposalStoreへ全TargetのSnapshotを渡し、UpdateRequest / UpdateTarget / PENDING Approvalを原子的に保存する。明示置換は旧要求のowner / 状態を既存保存層で検証し、新保存失敗なら旧失効もrollbackする。正本業務値は変更しない。

Docker内の実PostgreSQLで753テスト成功（既存722 + 追加31）。ruff check / format、git diff --checkを確認した。対象一括取得・業務値非変更、権限、全体拒否、4並行同keyの1要求化、異入力拒否、owner scope、終端再送と確定Snapshot保持、旧要求置換時のDB障害・rollback・同key再試行、読込後の正本変更、読込timeout / 接続障害の安全なエラーを検証した。T-R02 / R03の内部Prepare範囲とAC-07 / 13 / 14 / 16のSnapshot固定・要求保存・置換部分を検証した。HTTP再送、CREATE重複、二重Execute防止、Approval時のversion失効、AC全体の完了を意味しない。

Prepare API / Tool公開、Agent入力hash生成、他カテゴリのPrepare、Approval / Execute、DB監査・Tool操作ログ、Graph / Outboxは後続。PO-B未決事項、材料関連の新機能、migration、依存、Frontendは変更していない。LogiScopeコードの再利用はない。

## 保全予定UPDATEの内部Prepareチェックポイント

2026-10-09、PR #24 merge後、POの指示でMaintenancePlanPrepareを追加した。保全・工場管理のtrusted contextだけを許可し、既存IDと非空patchを受け付ける。patchはplanned_start / planned_end / plan_statusのみ。日時をUTC・microsecondへ正規化し、全対象の全業務値・versionを単一statement Snapshotで取得する。全patch適用後の開始 < 終了と実変更を検証し、expected_versionを正本から導出する。設備ID・plan_code・versionの自己申告変更を拒否する。業務行の変更lock、保全予定や設備状態の更新は行わない。

Prepare入力hashはTool名・ID順の対象集合・正規化した明示patch・明示置換IDから生成する。before / versionや現在値からの補完項目を含めず、明示項目の有無を保持する。UUID表記、集合順、同じ瞬間を表すtimezoneの差は同入力として扱い、追加の明示項目や変更値・Agent hash・置換IDの差はDUPLICATE_REQUESTとする。保存済み再送は正本読込前に返し、終端要求や正本変更後も確定Snapshotを保持する。既存ProposalStoreで新保存と旧要求失効を原子的に行う。

Docker内の実PostgreSQLで795テスト成功（既存753 + 追加42）、ruff check / format、git diff --check成功。期間・timezone・no-op・禁止項目、全Target拒否、全業務項目保持と正本非変更、権限、retry owner scope・権限喪失・カテゴリ間key流用拒否、4並行同keyの1要求化、置換中Approval INSERT障害のrollbackと同key再試行、単一statement読込後のversion変化、BIGINT増分不能、読込timeout・接続障害を検証した。既存設備状態Prepareのテストも保持した。

T-R02 / R03の内部PrepareとAC-07 / 13 / 14 / 16のSnapshot・要求保存・置換部分を検証する。HTTP再送、承認時のversion失効、二重Execute防止、業務受入全体の完成ではない。Prepare API / Tool公開、CREATE系・生産作業・依存関係のPrepare、Approval / Execute、DB監査・Toolログ、Graph / Outboxは後続。要件・PO-B・migration・依存・Frontendは変更せず、LogiScopeコードも再利用していない。

## 保全予定・実績CREATEの内部Prepareチェックポイント

2026-10-09、PR #25 merge後、POの指示でMaintenanceCreatePrepareを追加した。保全・工場管理のtrusted contextだけを許可し、prepare_tool / inputの対象配列で既存2種類のCREATE入力を受け付ける。日時・UUID・任意maintenance_plan_idのNULLを正規化し、必須業務項目・状態・非空result・予定の開始 < 終了を検証する。設備・指定済み既存保全予定の存在、実績と予定のequipment_id一致、正本のplan_code / record_code重複を単一statement Snapshotで確認する。対象内の同種業務キー重複と異種カテゴリ混在を拒否する。同じcode文字列を予定・実績がそれぞれ使う場合は、別の業務キーとして扱う。

入力hashに各Tool名・正規化入力・明示置換IDを含め、生成ID・before・versionを含めない。対象集合はTool名と業務キーで整列する。保存済みキーは正本の再検証と新ID生成より先に照合し、元ID・Snapshotを返す。新規要求の業務検証後だけCREATE IDを生成し、before / expected_versionをNULL、after.versionを1に固定する。予定・実績CREATEを一保全要求にまとめて保存できる。実績の予定参照は登録済みUUIDを要求し、新規予定への自動紐づけは行わない。

Docker内の実PostgreSQLで839テスト成功（既存795 + 追加44）、ruff check / format、git diff --check成功。全業務項目保持・生成ID・正本非変更、権限、必須／禁止項目・期間・不正Unicode、参照不足・設備不一致・重複・カテゴリ混在の全体拒否、正本業務キー衝突、終端再送・UUID / timezone / 対象順 / 任意NULL正規化・ID非再生成、owner scope・異入力・権限喪失、4並行同keyの同ID化を検証した。複数CREATEと旧要求置換中のApproval INSERT障害で全rollback・旧状態保持・同key再試行、単一statementの参照／キー検証、読込timeout・接続障害の安全なエラーを検証した。

T-R02 / R03 / R21、AC-07 / 11 / 13 / 14 / 16の内部Prepare・Snapshot・要求保存・置換部分に対応する。Prepareは業務キーを予約しない。読込後の正本変更・CREATE競合はApproval / Executeで再検証し、Executeの業務DB UNIQUEが最終防御となる。CREATE重複防止や業務受入全体の完成ではない。

Prepare API / Tool公開、保全UPDATEとCREATEを混ぜる統合経路、生産作業・依存関係Prepare、Approval / Execute、DB監査・Toolログ、Graph / Outboxは後続。業務テーブルへINSERTせず、設備状態・既存予定状態を自動変更しない。要件・PO-B・migration・依存・Frontendは変更せず、LogiScopeコードも再利用していない。

## 保全UPDATE・CREATEの内部Prepare統合チェックポイント

2026-10-09、PR #26 merge後、POの指示でMaintenancePrepareへ保全予定UPDATE・予定CREATE・実績CREATEを統合した。既存のUPDATE専用MaintenancePlanPrepareとCREATE専用MaintenanceCreatePrepareは、従来入力schemaと対象Tool制限を保持する互換入口として共通処理へ委譲する。UPDATEだけの要求は従来のTool名＋対象入力配列のhash形式、CREATEだけの要求は従来のTool付き対象配列のhash形式を維持する。保存済みretry key・Snapshotを再生成せず、旧要求の移行やDB変更を行わない。

混在要求も単一カテゴリMAINTENANCEとして認可し、正規化対象集合・明示入力・置換IDをhashへ固定する。UPDATE対象と実績参照先の全業務値・version、設備参照、CREATE業務キー衝突を単一statement Snapshotで取得する。UPDATE ID重複、CREATE同種キー重複、異種カテゴリ、不存在・設備不一致・不正patch・期間・no-op・業務キー衝突は全体拒否する。全UPDATE検証後にCREATE IDを生成し、明示差分を一Snapshotへ含め、一回のProposalStore.saveでTarget・承認を保存する。UPDATEとCREATEの混在はCOMPOSITEになる。

Docker内の実PostgreSQLで866テスト成功（既存839 + 追加27）。保全関連113件の先行確認、ruff check / format、git diff --check、変更Markdownのリンク・fence確認を行った。3種混在の一要求化・業務正本非変更、権限、全体拒否・正規化後のUPDATE重複、UPDATE不正時のCREATE ID非生成、並び順・UUID・timezoneを正規化した再送、明示内容変更／Target省略／置換IDの不一致、旧保存hashを直接構築した互換再送を検証した。単一statement観測と観測後の直接SQL変更、4並行同keyの同Snapshot化、混在置換中Approval INSERT障害で全rollback・旧状態保持・同key再試行、読込timeout・接続障害も確認した。既存のUPDATE・CREATE・設備状態Prepareテストを削除していない。

T-R02 / R03 / R21、AC-07 / 11 / 13 / 14 / 16の内部Prepare・Snapshot・要求保存・置換部分に対応する。直接SQL変更のfixtureは読込後の競合を検証するためであり、設備IDを変更するAPIを許可したものではない。実績だけによる設備／予定状態の自動更新や、新規予定への自動参照解決は行わない。

Prepare API / Tool公開、呼出しTool名と先頭Targetの一致確認を含むTool dispatcher、生産作業・依存関係Prepare、Approval / Execute、DB監査・Toolログ、Graph / Outboxは後続。Prepareの正本観測後に生じるversion変化・CREATE競合はApproval / Executeで再検証する。業務受入全体やExecuteの完成ではない。要件・PO-B・migration・依存・Frontendは変更せず、LogiScopeコードも再利用していない。

## UI/UX意見書とAPIへの示唆

[UI/UX意見書レビュー](2026-10-09-ui-ux-opinion-review.md)に、POが共有した参考意見の採用・修正・保留とAPI設計上の注意を記録した。構造化した比較・Evidence・Unknown・人間の操作境界を重視する。画面構成・新しい業務データを正式要件へ昇格させず、Frontend実装は後続とする。

## 生産作業予定値UPDATEの内部Prepareチェックポイント

2026-10-09、PR #27 merge後、POの指示でProductionSchedulePrepareを追加した。生産管理・工場管理のtrusted contextだけを許可し、対象IDとplanned_status / planned_start / planned_endの非空patchを受け付ける。全対象の全業務値・versionを単一statement Snapshotで取得し、UTC正規化後の開始 < 終了と実変更を検証する。operation_code / process_id / active / versionの自己申告変更を拒否する。正本からexpected_versionを導出し、確定afterのversionを1増分した提案を保存する。業務行への変更lockやUPDATE、設備割当変更は行わない。

入力hashはTool名・ID順の対象集合・正規化した明示patch・明示置換IDから生成し、観測値・versionを含めない。保存済みretryは正本再読込より前に返す。複数対象の不正・不存在・no-opは全体拒否し、既存ProposalStoreで要求・Target・承認保存と旧要求失効を原子的に処理する。正本観測後のversion変化は後続のApproval / Executeで再検証する。

Docker内の実PostgreSQLで906テスト成功（既存866 + 追加40）、ruff check / format成功。予定値の全項目保持と業務正本・割当非変更、権限、期間・禁止項目・全Target拒否、timezone、状態変更、終端再送と正本変更後のSnapshot保持、owner scope、異入力、4並行同keyの一要求化、置換中Approval INSERT失敗の全rollbackと再試行、単一statement観測後のversion変更、BIGINT増分不能、読込timeout・接続障害を検証した。

T-R02 / R03 / R21とAC-07 / 13 / 14 / 16の内部Prepare・Snapshot・要求保存・置換部分に対応する。業務受入全体、HTTP再送、承認時のversion失効、二重Execute防止の完成ではない。

今回の内部入口は予定値だけを扱い、assignment_replacementを拒否する。正式Tool契約の割当置換・予定値との同時変更を削除したものではない。割当変更にはUSESと依存関係を合わせた禁止循環検証が必要なため、正本取得・区間差分・循環検証を次の実装単位へ分けた。Prepare API / Tool公開、設備割当・依存関係Prepare、Approval / Execute、DB監査・Toolログ、Graph / Outboxは後続。要件・PO-B・migration・依存・Frontendは変更せず、LogiScopeコードも再利用していない。

## 禁止循環の共通検証チェックポイント

2026-10-09、PR #28 mergeを確認してローカルmainをfast-forwardし、POの指示で設備割当Prepareの前提となる純粋な禁止循環検証を追加した。domain-model §4 / 8 / 9 / 15.4に従い、DEPENDS_ONと割当由来USESは保存方向、PRECEDES / CONTROLSは逆方向に揃え、typed IDの共通論理依存グラフを検証する。activeな全期間の関係をrequiredの値にかかわらず対象とし、SUPPLIES / CAN_SUBSTITUTEは除外する。PRODUCESは既存endpoint検証によりProductで終端する。現在の許可endpointではEquipment側からProductionOperationへ戻る経路を作れず、USES自体は循環を閉じないが共通集合に含める。

既存のRelation / Assignment行schema検証を使い、重複行IDや不正入力を拒否する。並行edgeを同一論理edgeへ集約し、再帰を使わないトポロジカル除去で禁止循環を検出する。入力行は変更しない。呼出し側は全Target適用後の、完全かつ一貫したPostgreSQL業務行集合を渡す責務を持つ。今回の関数だけで集合完全性、endpointの存在・active、業務キー一意性、期間重複、権限、lock、Graph CURRENTを保証したことにはならない。

Docker内で926テスト成功（既存906 + 追加20）、ruff check / format、git diff --check成功。単一種別・自己・混在循環、保存方向と上流方向の差、inactiveによる循環解消、非重複期間・optional関係の循環拒否、許容循環除外、USES / PRECEDESの組合せ、typed UUID、並行edge、不正入力・重複ID、2,000段の非再帰処理と末尾閉路を検証した。AC-G12のtype / cycle検証部品に対応し、登録経路全体の受入完了ではない。

設備割当Prepareの全正本取得・区間差分への接続、DependencyRelation Prepare、Approval / Execute時のGraph mutation lock下での最終集合再検証、API / Tool公開は後続。業務要件・DB・migration・依存・Frontendは変更せず、LogiScopeコードの再利用はない。

## 生産作業・設備割当の内部Prepareチェックポイント

2026-10-09、PR #29 mergeを確認しローカルmainをfast-forwardした後、POの指示でProductionPrepareを追加した。従来のProductionSchedulePrepareは同じ共通処理の予定値専用入口とし、入力schema制限と保存済みretry hashを保持する。新入口は予定値のみ、割当置換のみ、同時変更、同カテゴリ複数親を受け付ける。認可・正規化・再送照合を正本読込より先に行い、指定設備不存在・不正期間・不正patch・no-opは要求全体を拒否する。

割当を含む場合、対象生産作業の全業務値・version、全Assignment（inactiveも含む）、全DependencyRelation、指定設備の存在を単一statement Snapshotで取得する。既存の区間差分・Snapshot構築を使い、明示[start,end)外を保持し、inactive業務キーはversion付きUPDATEで再利用する。親は変更前後の全active集合を固定し、予定値との同時変更でもversion増分は1。全対象の差分適用後にAssignment集合の一意性・期間重複と混在禁止循環を検証し、一Snapshotを保存する。新IDが対象外の既存Assignment IDと衝突する場合も拒否する。禁止循環と入力行不整合は型付き例外で区別する。

Docker内の実PostgreSQLで962テスト成功（既存926 + 追加36）、ruff check / format、git diff --check成功。期間外の両側保持、空集合・明示NULL、inactiveキー再利用、予定値との同時変更・親version、no-op、指定設備不存在・不正入力・全Target拒否、権限、正規化再送・旧入口互換・正本変更後のID保持、4並行同key、全差分が最終循環検証へ渡ること、対象外の既存循環拒否、単一statement・非lock、Assignment版数上限・読込後の直接SQL変更・不正source重複・生成ID衝突、複数親の置換保存途中失敗による全rollbackと同key再試行、timeout・接続障害を確認した。既存テストを保持した。

T-R02 / R03 / R08 / R21、AC-07 / 13 / 14 / 16 / 18 / G12の内部Prepare・Snapshot・要求保存・置換部分に対応する。Assignment業務行は更新せず、Graph USES ProjectionやExecute途中失敗は未実装。AC-18全体の完了ではない。正本観測後の競合はApproval / Executeで再検証し、Graph mutation lock下で最終集合検証する。

現状の利用者向けHTTPはhealth / readinessのままで、業務API公開は後続。次は依存関係Prepareと、その後のTool / API接続を進める。デモseedとLLM / embedding疎通は未実施。PO-B、業務要件、DB / migration、依存、Frontendは変更せず、LogiScopeコードの再利用はない。

## 依存関係の最終集合検証チェックポイント

2026-10-09、POから残りリソースで完了できる小タスクを求められ、依存関係Prepareの前提となるnormalize_relation_setを追加した。domain-model §14と既存DB UNIQUEに従い、全Target適用後の完全な行集合で、行IDと業務キーの重複をinactiveも含めて拒否する。同じtyped source / target / relation_typeのactive行について半開区間の期間重複を拒否する。境界だけ接する期間は許可し、NULL endは無期限とする。requiredの差は別の論理関係とは扱わない。

既存の行schema検証とUTC / UUID正規化を使い、監査時刻を除く正規化行をID順で返す。入力は変更しない。RelationSetConflictで集合の業務制約違反を不正行schemaと区別する。Prepare / Executeの呼出し側は、変更前の行と差分を並べるのではなく、全変更を適用した最終集合を一貫した正本から供給する責務を持つ。

Docker内で984テスト成功（既存962 + 追加22）、ruff check / format、git diff --check成功。半開境界・無期限・包含を含む重複、typed endpoint / 関係種別 / 保存方向の区別、required差、inactiveの期間重複と業務キー一意性、行ID重複、timezone同値キー、縮小／DISABLE後の最終集合、入力非変更・監査除外、不正配列・行・期間・boolを確認した。

AC-11 / G12とdomain-model §14の業務キー・型・期間検証部品に対応する。DB読込・保存、endpointの存在 / active、権限、禁止循環、Graph mutation lock、API / Tool接続はこの部品の責務外で、受入基準全体の完成ではない。次回はこの部品と禁止循環検証を依存関係Prepareへ接続する。要件・DB / migration・依存・Frontendは変更せず、LogiScopeコードの再利用はない。

## 依存関係CREATE・UPDATE・DISABLEの内部Prepareチェックポイント

2026-10-09、PR #31 mergeを確認してローカルmainをfast-forwardし、POの再開指示でDependencyPrepareを追加した。保全・生産管理・工場管理のtrusted contextだけを許可し、既存Tool契約のCREATE全業務入力、UPDATEの非空patch、DISABLEのIDだけを受け付ける。USES直接登録、ID・versionの自己申告変更、不正型・時刻を拒否する。正規化した明示入力・Tool名・置換IDをhashへ固定し、観測before / version・生成IDを含めない。対象集合をCREATE業務キーまたは既存IDで整列し、同一行への複数操作・CREATE同一キーを全体拒否する。

単一statement Snapshotで全DependencyRelation・全Assignment・5種類のtyped endpointの存在 / activeを取得する。全対象の変更後の型・required・期間、endpoint存在 / active、実変更・DISABLE対象active・version増分を検証してからCREATE IDを生成する。既存IDや他CREATE IDとの衝突を拒否し、全Targetを適用した最終集合で業務キー一意性・active期間重複・混在禁止循環を検証する。業務キー交換、期間縮小後のCREATE、DISABLEによる循環回避は途中集合で拒否しない。変更後のtyped参照の存在・active検証はDISABLEを含む全Targetへ適用する。要件の例外は推測追加していない。

保存済み再送を正本読込より先に返し、終端要求・正本変更後も生成済みIDと確定Snapshotを保持する。既存ProposalStoreで要求・全Target・承認を保存し、明示した旧要求の失効と新保存を原子的に行う。Prepareでは業務Relation行を変更せず、Graph mutation lockも取得しない。

Docker内の実PostgreSQLで1,034テスト成功（既存984 + 追加50）、ruff check / format、git diff --check成功。3操作混在と全業務項目・version保持、業務正本非変更、権限、不正schema / period / required / endpoint組合せ、重複・不存在・inactive・no-opの全Target拒否、業務キー交換、半開境界・期間縮小後CREATE、禁止循環とDISABLE回避、SUPPLIES許容循環を確認した。再送正規化・終端保存結果・ID非再生成・内容 / Agent / 置換ID不一致・owner scope / 権限喪失、4並行同key、旧要求置換中のApproval INSERT失敗による全rollbackと同key再試行、単一statement / 非lock、typed UUID取り違え、CREATE前の全対象検証、生成ID衝突、version上限、読込後のSQL変更、timeout・接続障害も検証した。

T-R02 / R03 / R07 / R21と、複数Graph Targetの最終集合検証に関するtest-plan補足、AC-05 / 07 / 11 / 13 / 14 / 16 / G12の内部Prepare部分に対応する。承認・Execute・Projectionや受入基準全体の完成ではない。Dependency自己承認不可と工場管理者だけの承認規則は後続Approval APIで適用する。

全カテゴリの内部Prepareが揃った。次は既存Tool契約に沿うdispatcher / API接続と、curlで試せる一連の流れへ進める。HTTPはまだhealth / readinessだけ。デモseed、LLM / embedding疎通、Approval / Execute、DB監査・Toolログ、Graph / Outboxは後続。PO-B、業務要件、DB / migration、依存、Frontendは変更せず、LogiScopeコードの再利用はない。

## 内部Tool dispatcherチェックポイント

2026-10-09、PR #32 merge後、POの指示でToolDispatcherを追加した。実装済みRead 13種とPrepare 6種だけをschema一覧と固定呼出し経路へ登録する。未実装Graph / RAG / 履歴Tool、Approval / Execute、任意SQL / Cypherを呼び出せる入口は追加しない。既存ReadResult / SavedProposalを返し、HTTP Response Envelopeへの変換やAgent実行を混ぜない。

Prepareは単一入力かtargets配列のどちらかだけを受け付ける。各要素はprepare_tool / inputのみ、先頭Tool名は呼出しTool名と一致、全要素は既知Toolかつ同一カテゴリを要求する。混在可能な保全3種は既存MaintenancePrepareへまとめ、他カテゴリは既存の対象入力配列へ変換して委譲する。認証主体・retry key・Agent input hash・置換IDは別のtrusted引数とし、Tool引数による注入を拒否する。service側の認可・業務制約・再送・保存を保持し、ProposalErrorを共通ToolError codeへ変換する。

Tool schemaは型・UUID / timezone時刻・許可状態・非空patch・明示NULL・単一 / 複数入力・未知field禁止を表す。型の組合せや期間・循環などの業務意味論はサーバ側既存検証を正とし、schemaだけで成立保証しない。一覧取得後のschema編集で後続一覧が変化しないよう独立コピーを返す。先頭Tool一致は実行時にも検証する。

Docker内の実PostgreSQLで1,071テスト成功（既存1,034 + 追加37）、ruff check / format、git diff --check成功。6種の実Prepare到達と業務正本非変更、Read結果と非保存、保全混在、単一と一要素配列の同key再送、未登録・確定操作Tool拒否、不正wrapper・先頭不一致・異種カテゴリの事前拒否、信頼済み情報注入拒否、認証前拒否・認可error保持、schema一覧とコピー分離を確認した。

api-tools §16、T-R02 / R07とAC-01 / 05 / 07 / 13の内部Tool境界部分に対応する。Agentによる実呼出し、HTTP、Approval / Execute、業務受入全体の完成ではない。Tool trace / operation log、LLM・Agent入力hash生成、context、デモseed、未実装Tool、RAG / Graph接続は後続。HTTPはhealth / readinessのまま。正式要件・API契約・DB / migration・依存・Frontendは変更せず、LogiScopeコードも再利用していない。

## 更新要求Snapshot閲覧APIチェックポイント

PR #33 merge後、`GET /update-requests/{id}`を追加した。Trusted Execution Contextから本人またはロール別履歴閲覧範囲を判定し、単一statement・read-only transactionで要求、承認、全Targetを取得する。既存canonical/hash・Target・状態組合せ検証を通した保存済みSnapshotだけを返し、現在の業務値で再生成しない。閲覧による期限失効や業務更新は行わない。未承認の承認時刻・期限はNULLとし、承認済みは保存値をUTCで返す。

認証401、不正ID400、不存在404、権限不足403、依存障害・timeout503、保存不整合500を共通Envelopeで返す。内部SQL・credential・例外messageを返さない。access-control §7 / 10、api-tools §3 / 14、AC-05 / 07 / 14の閲覧部分を検証する。追加28テストで4カテゴリ×4ロール、本人のロール変更後閲覧、保存Snapshotとcurrent valueの区別、承認時刻・期限、非更新、改変拒否、障害の秘匿を確認した。

HTTP Prepare / Agent、Approval / Execute、デモseed、Graph / Outbox / RAG、Toolログは後続。正式仕様、migration、依存、Frontendは変更しない。LogiScopeコードの再利用はない。Astraレビューは未実施。
