# LineScope 文書修正・セルフレビュー報告

日付: 2026-10-09

## 1. 範囲・判断の経緯

`deliverables.md` が定義する19文書を対象に、`review.md` のF-01〜F-05、U-01〜U-20を確認した。業務判断が必要な8項目を変更前に利用者へ列挙し、推奨方針を提示した後、利用者の「推奨案で進めて欲しい」という指示に基づき反映した。

19文書すべてを修正し、本報告を追加した。元レビューは初回の指摘記録として保持する。実装コード・設定、GitHubリポジトリは変更・作成していない。外部モデルへの相談は行っていない。

PostgreSQL正本、Neo4j / Qdrant派生、AgentとApproval / Executeの分離、元requester限定Execute、承認成立後30分、全Target原子性、Transactional Outbox、CURRENTのみGraph正常利用という既存方針を維持した。修正は不足契約・整合制御・利用者が採用した業務方針の明文化に限定した。

## 2. 採用した業務方針

| 項目 | 確定方針 | 正本 |
|---|---|---|
| 未承認期限 | 設けない。approve時に再検証。承認成立後30分は維持 | access-control §6・9 |
| 必須成立・代替 | SUPPLIESはtargetにsource供給が必須。必須依存はAND、一段CAN_SUBSTITUTE置換。確定できない循環・利用可能性はINDETERMINATE | domain-model §7・15.1 |
| 複数カテゴリ | 一要求は単一カテゴリ。同カテゴリ複数Target可。予定値と割当は生産運用に属する | access-control §9 |
| 割当置換 | 明示[start, end)だけを集合置換し、期間外を保持。差分・ID・versionを承認Snapshotに含める | domain-model §15.2 |
| 過去分析 | 現在登録されたactive関係の期間評価。当時の登録内容・状態の完全再現は対象外 | domain-model §15.3 |
| Execute再認可 | requesterとapproverの現在権限を確認。喪失は失効。確定済み再送はowner・閲覧確認 | access-control §9 |
| Graph権限 | 保全・生産管理・工場管理。現場担当者は通常依存Readまで | access-control §9 |
| 業務入力・RAG | 小さな状態値集合、必須業務項目と時刻整合、保全実績の非連動、FACTORY_INTERNALのみ | requirements §12、access-control §9 |

## 3. F-01〜F-05対応

| ID | 対応 | 主な反映先 |
|---|---|---|
| F-01 | PENDING / WAITING_APPROVALのEXPIRED遷移を除去。承認済みだけ同期期限判定。approve再送で延長しない | access-control §6、transaction-design §12・13、api-tools §4、T-R04 |
| F-02 | 停止workerに代わりRebuild controllerがleaderを引き継いでdrainする手順 | transaction-design §11、interaction-flow §10、operations §10、T-R12 |
| F-03 | graph_projection_controlにfatal_error / generationを保存。未初期化・重大障害をERRORに統一 | architecture §7、data-model §6・9、transaction-design §10、operations §3・10、T-R11 |
| F-04 | required方向を種別ごとに定義。供給先targetがsourceを必須とする | domain-model §7・15.1、AC補足、T-R14・15 |
| F-05 | 保存Snapshot不変、PENDINGもINVALIDATED可。旧要求置換と新Prepare保存は原子的。FAILED時のApprovalもINVALIDATED | domain-model §15.4、transaction-design §12・19、api-tools §18、T-R03・05・19 |

## 4. U-01〜U-20対応

| ID | 対応 | 主な正本・検証 |
|---|---|---|
| U-01 | lock順固定、業務行FOR UPDATEとversion条件付きUPDATE、CREATE UNIQUE、最終集合検証 | transaction-design §5・15・19、T-R01 |
| U-02 | 別Transactionの失効で状態・hash・原因再検証しCOMPLETEDを保護 | transaction-design §15、T-R01 |
| U-03 | 内部サーバUUIDを維持し、別prepare_retry_keyで受付再送・同時Prepareを識別 | transaction-design §15、data-model §2、api-tools §14、T-R02 |
| U-04 | canonical規則・hash範囲・CREATE ID固定・Target照合を定義 | transaction-design §15・19、T-R03 |
| U-05 | 単一カテゴリ、全Target権限、履歴category導出、既存閲覧境界 | access-control §9・10、data-model §12、T-R07 |
| U-06 | 明示期間置換、区間外保持、既存業務キー再利用、親version更新 | domain-model §15.2、transaction-design §15、T-R08 |
| U-07 | AND成立、一段置換、重要対象別SPOF、必須循環・未知availabilityのINDETERMINATE | domain-model §15.1、api-tools §17、T-R14・15 |
| U-08 | shared分析 / exclusive更新・Projectionの共通lock。観測時刻・generationをEvidence化 | transaction-design §16、T-R10 |
| U-09 | 現在登録情報の期間評価に限定。過去利用可能性は推測しない | domain-model §15.3、api-tools §18、T-R15 |
| U-10 | generation別marker、atomic edge置換、DISABLE保持、version/hash比較、初期seed | data-model §10・12、T-R13 |
| U-11 | controller drain、単一statement Snapshot、検証後切替、flag・generation欠損の復旧 | transaction-design §11・17・19、operations §10、T-R12 |
| U-12 | requester / approverの現在権限をサーバ設定で再検証、参照障害と喪失を区別 | access-control §9、transaction-design §18・19、T-R06 |
| U-13 | Read / Graph / Prepare入出力、必須業務値、HTTP code、Reject・ID・置換契約 | api-tools §14〜18、requirements §12、T-R19・21 |
| U-14 | 個別Graph Toolを含め分析roleを統一 | access-control §9、use-cases §23、T-R17 |
| U-15 | FACTORY_INTERNAL、単一active version、正本本文hash照合、Index有効化・再構築 | rag-design §8、data-model §11、T-R18 |
| U-16 | update_audit_event、Outbox FK、確定execution_result、失敗監査と成功履歴の区別 | data-model §2・9、T-R09・20 |
| U-17 | 保存済み確定afterとcurrent再参照を分離し、後続version差・再参照障害を明示 | transaction-design §15、AC-15、T-R09 |
| U-18 | context所有者・TTL、保守的サーバ更新意思判定、trusted retry key、Tool上限 | agent-design §12、operations §10、T-R17、evals §6 |
| U-19 | 技術閾値とデモロール構成、AI安全ケース違反0件を明記。一般品質閾値・具体製品選定は後述の持越し | operations §10、evals §6 |
| U-20 | IDを人が渡すv1運用を明示。通知・一覧APIを追加せず、Snapshot閲覧権限を統一 | access-control §10、api-tools §14、interaction-flow §10 |

## 5. 19文書の変更概要

| 文書 | 主な変更 |
|---|---|
| deliverables.md | レビュー記録と仕様正本の区別 |
| requirements/requirements.md | 業務入力・状態値・必須性・非連動 |
| requirements/domain-model.md | required、AND・置換・SPOF、期間置換、過去分析 |
| requirements/access-control.md | 未承認無期限、カテゴリ、再認可、Graph / RAG権限、承認運用 |
| requirements/use-cases.md | 確定方針への参照、Snapshot失効、更新後確認 |
| requirements/non-functional-requirements.md | 観測時点・監査・有限制限の具体化 |
| requirements/acceptance-criteria.md | AC-15 / 18の並行・非同期時の解釈、既存ACの判定補足 |
| design/architecture.md | 同期判定と分析・更新・Rebuild整合境界 |
| design/agent-design.md | サーバ更新意思制御・Context・retry・上限 |
| design/data-model.md | 冪等性・Snapshot・保存結果、監査・同期管理、Projection marker・制約 |
| implementation-design/api-tools.md | 入出力・HTTP code・業務schema・Evidence・要求置換 |
| implementation-design/transaction-design.md | lock・競合・状態組・canonical・Outbox・Rebuild・再送 |
| implementation-design/interaction-flow.md | lockとcontroller drainを含むシーケンス |
| implementation-design/prompt-design.md | サーバ制御との対応、時刻・現在値・確定値の説明 |
| implementation-design/rag-design.md | 有効化・正本hash照合・再構築・citation |
| implementation-design/evals.md | 安全ケース合格基準・一般品質の持越し |
| implementation-design/test-plan.md | T-R01〜T-R21と既存ACの対応、境界ケース |
| implementation-design/operations.md | 同期障害・復旧・技術既定値・デモ構成・初期化 |
| implementation-design/AGENTS.md | 確定済み方針とレビュー記録の位置付け |

## 6. セルフレビュー

19文書を再読し、以下を横断確認した。

| 観点 | 確認内容・結果 |
|---|---|
| 文書間整合性 | 事項ごとの正本を維持し、業務判断はrequirements側、技術方式はdesign / implementation-design側に反映 |
| 状態遷移 | Request / Approval許容組、PENDING失効、未承認無期限、終端保護、FAILED / INVALIDATED、期限境界を統一 |
| API / Tool | LLMにApproval / Executeを公開しない。ID・hash・retry・空Body・置換入力・エラー・partial・Evidence契約を対応 |
| DB | 承認一件、成功履歴一件、FK / UNIQUE、業務行version、保存Snapshot、監査・確定結果の物理保存を確認 |
| Graph | 意味論と保存方向、AND成立・一段置換、generation固定、active・期間、未知判定と探索完全性を区別 |
| Outbox | commit集合判定、完全payload、version/hash冪等、lease・DEAD、Neo4j commit後再送、controller drain・Restoreを確認 |
| 権限 | role根拠、owner限定、自己承認、全Target・単一カテゴリ、Graph分析、RAG再認可・履歴閲覧を統一 |
| AC→Test | 既存AC39件の主テスト対応を維持し、レビュー追加ケースをT-R01〜T-R21に対応。重大Fail集合は変更なし |

セルフレビュー中に、割当分割で同じ業務キーをCREATEする衝突、初期NOT_INITIALIZEDからのRebuild拒否、generation欠損Restore、権限不足と承認失効の混同、現在値で確定結果を上書きする問題を修正した。

文書の機械的確認は、19文書の存在・UTF-8、Markdown code fence・JSON例、ローカルリンク、AC主テスト対応、追加Test ID重複、基本方針の記載を対象とする。確認結果: 対象19件、JSON例4件、ローカルリンク・code fence正常、AC主テスト対応39/39、追加Test ID21件で重複なし、基本方針10項目の記載確認。これは実装の安全性を証明するものではない。Transaction / Concurrency / Projection / Recoveryの自動テストは未実装・未実行であり、合格したとは扱わない。

## 7. 未解決・実装段階への持越し

1. **一般AI品質の数値合格閾値（U-19）**: 代表datasetとbaseline結果がないため確定していない。安全ケース違反0件は確定済み。一般品質の合格閾値は評価結果を確認して固定する必要があり、未設定のままリリース合格とはしない。
2. **具体技術製品・モデル・version（U-19）**: 言語・Framework・LLM・embedding modelは実装着手時に選定する。今回の責務・Transaction・API契約はこれらに依存しない。
3. **実環境による検証**: 技術既定値はデモ用の初期値であり性能実測ではない。DB制約、Neo4j marker排他、lease、Rebuild timeout、restore、自然言語判定は実装テスト・Evalsで確認が必要。

F-01〜F-05とU-01〜U-20について、上記U-19の持越しを除き今回必要な仕様を反映した。採用した8業務方針に新たなPO判断待ちはない。今回のセルフレビュー範囲では新たな重大文書矛盾は検出していない。
