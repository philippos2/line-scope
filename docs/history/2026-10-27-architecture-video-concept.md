# 説明動画第2弾：アーキテクチャ・設計思想編の企画案

## 目的・制約・完了判定

仮タイトルは「なぜLineScopeは、このアーキテクチャなのか」。開発者はPR #281のmerge後、第1弾の制作に入る前に、第2弾のコンセプトと大まかな構成をレビューする順序へ変更した。今回は最新コード・正本・検証記録を読んだ企画案と予定の同期まで。詳細ナレーション・秒単位の絵コンテ・音声生成・録画・動画編集を行わない。第1弾の承認済み絵コンテは変更しない。

照合した最新mainは`7a4274a4c8d01e8839b45aaa5145dacb29543756`（PR #281 merge）。正式デモの製品ソース固定版は#278 mergeの`55965a3`であり、文書更新をデモ製品の再配備と混同しない。製品・DB・seed・認証・環境は変更していない。

完了判定は、以下の6項目の企画案を提示し、開発者のレビューを待つこと。新しい仕様や追加実装の提案へ広げない。

## 1. 中心コンセプトと想定視聴者

**LLMにすべてを任せない。意味・事実・判断を分離するシステム設計。**

「どの技術を使ったか」より、「どの責任を誰に持たせ、検証によってどこを見直したか」を説明する。ここでの意味は業務概念・関係の定義、事実は認可済みの登録情報、判断は明示規則による条件付き評価を指す。実世界の正しさや最終的な運転可否を自動決定する意味ではない。

想定視聴者はソフトウェアエンジニア、アーキテクト、技術検証を評価する人。オントロジー専攻やNeo4jの実装経験を前提にしない。視聴後の理解目標は、①正本と派生を分けた理由、②構造・状態・評価の分離、③生成LLMの採用と不採用を決めた具体的な検証、④質問と更新の権限を分ける理由、の4点。

## 2. 第1弾との役割分担

| 動画 | 主な問い | 主な素材 |
|---|---|---|
| 第1弾・約4分30秒 | 一台の停止から、何を調べてどんな判断材料を得られるか | 実画面の検索・下流・能力・共通電源・質問・根拠 |
| 第2弾・6〜8分程度 | なぜその結果を、この責務分担・データ構成・規則で作るのか | 短い実画面の引用、責務図・データフロー・三値表・検証結果の要約 |

第2弾は第1弾を知らなくても理解できるよう冒頭でM-204/M-208/R-02の状況を短く示すが、操作手順は繰り返さない。PR #276の経緯は反省の長話やモデルの優劣比較ではなく、「根拠は正しくても質問と違えば失敗」という設計判断の事例として扱う。

## 3. 章立てと大まかな時間配分（約7分20秒）

以下は章単位の配分案。読み上げや画面収録の実測値ではなく、詳細台本・絵コンテではない。6〜8分内で調整する。

| 章 | 目安 | 伝える問い・要点 | 主な見せ方 |
|---|---|---|---|
| 導入：判断材料をどう作るか | 約35秒 | 代替候補があるだけで利用可能と決められるか。第1弾の結果を作る裏側の責務へ入る | 共通電源の画面引用→問いの提示 |
| なぜライトウェイトオントロジーか | 約50秒 | 型と意味のある関係、依存方向、一段代替。重厚な汎用推論ではなく、限定モデルと明示規則で扱う | 設備・工程・作業・製品・電源の小さな概念図 |
| なぜ正本と派生を分けるか | 約75秒 | PostgreSQL・Neo4j・Qdrantの異なる責任。Outbox・再構築・CURRENTと同期コスト | 正本→Outbox→派生Graph、文書→Embedding→検索Indexの図 |
| なぜ明示的な評価規則か | 約50秒 | 必須依存・三値・探索完全性・Evidence。不明を利用可能へ変換しない | R-02の三値と、構造候補／登録条件の評価の対比 |
| LLMをどこで使い、どこで使わないか | 約110秒 | 現行の経路と旧試行を分ける。#276の誤受理・取りこぼし、#277の限定9観点への設計変更 | 現行処理の役割表→旧方式の失敗例1つ→観測結果→現在の境界 |
| なぜ業務更新を別に統制するか | 約65秒 | ReadとWrite、Prepare／Approve／Execute、カテゴリ別の権限、Snapshot・version・監査 | 保存案→別の承認操作→元requesterの実行の図。新しい実書込みを必須にしない |
| 成果と限界 | 約55秒 | 固定データで実証できた構造分析・三値評価・拒否。実工場・一般理解・比較優位は未実証 | 確認したこと／言えないことの対応表と根拠文書への案内 |

計約440秒。LLMの事例に最も時間を割く一方、製品名や内部クラス名を読み上げる章にはしない。詳細なlock順やSQL/Cypherは本編に詰め込まず文書へ案内する。

## 4. 採用理由と説明の根拠

### 技術と解決する問題

「採用理由」は記録された設計意図と実装上の役割に限る。後から便利そうな理由を創作したり、比較計測のない性能優位を付け加えたりしない。

| 技術・方式 | 解決する問題／記録された設計意図 | コスト・限界 | 正本と現在のコードの根拠 |
|---|---|---|---|
| ライトウェイトオントロジー | 異なる業務実体を型と関係意味論でつなぎ、到達と必須条件の成立を区別する。対象をv1の有限モデルに限定 | 概念・関係・規則の明示と保守が必要。OWL/RDFの汎用推論や任意業種へ自動適用する仕組みではない | [domain-model](../requirements/domain-model.md)、[relations.py](../../backend/src/linescope/domain/relations.py)、[graph_requirement_rules.py](../../backend/src/linescope/domain/graph_requirement_rules.py) |
| PostgreSQL | 業務値・状態・承認・version・監査・OutboxをTransactionと制約で扱う正本 | 派生との同期は別途必要。実世界の観測精度をDBで保証するものではない | [data-model](../design/data-model.md)、[transaction-design](../implementation-design/transaction-design.md)、[proposals.py](../../backend/src/linescope/application/proposals.py)、[execute.py](../../backend/src/linescope/application/execute.py) |
| Neo4jとOutbox／Projection | 型付き関係探索を再構築可能な派生Read Modelに分離する。正本更新と反映イベントを同じPG Transactionで保存し二重書込みの境界を明示 | 同期遅延・世代・復旧・lock等の管理が増える。PGとNeo4j全体の分散同時Snapshotを保証しない。CURRENTの確認が必要 | [architecture](../design/architecture.md)、[analysis_reader.py](../../backend/src/linescope/graph/analysis_reader.py)、[projection_application.py](../../backend/src/linescope/graph/projection_application.py)、[analysis_gate.py](../../backend/src/linescope/graph/analysis_gate.py) |
| QdrantとEmbedding | 関係探索とは別に文書の意味検索を担う。正本metadata・本文は再照合しIndexを再構築できる | ストアとモデルが増える。検索順位は正しさ・認可の証明ではない。小規模でも3ストアが必須／pgvectorより優位とは主張しない | [rag-design](../implementation-design/rag-design.md)、[knowledge_factory.py](../../backend/src/linescope/integrations/knowledge_factory.py)、[knowledge_vector.py](../../backend/src/linescope/integrations/knowledge_vector.py)、[knowledge_content.py](../../backend/src/linescope/application/knowledge_content.py) |
| FastAPI・Application・外部adapterの分離 | HTTP入力・認証済みContextと業務処理、DB／モデル接続の責務を区別する | 役割・契約の維持が必要。他HTTP frameworkとの比較優位を測定した採用理由は記録にない | [architecture](../design/architecture.md)、[interfaces/api.py](../../backend/src/linescope/interfaces/api.py)、[bootstrap.py](../../backend/src/linescope/bootstrap.py)、[agent_service.py](../../backend/src/linescope/application/agent_service.py) |
| React／React Flow | 関係・経路を表示し、比較・根拠と同じ文脈で確認する。探索・能力計算・認可はサーバに置く | 描画・選択と業務判断を混同しない。他UI frameworkより速いという採用理由は主張しない | [frontend-console](../design/frontend-console.md)、[Frontend](../../frontend/src)、[設計FAQ](../design-faq.md) |
| SQLAlchemy Coreと明示的Transaction | 動的値のbindと固定query構築を標準にし、更新のTransaction・監査・lockの境界を隠さない | PostgreSQL固有機能や安全なRaw SQL例外は残す。完全なDB非依存を目標にしない | [architecture §15](../design/architecture.md#15-sql--database-access-policy)、[core_execute.py](../../backend/src/linescope/persistence/core_execute.py) |
| 三値評価とEvidence | 登録状態、未登録、探索不完全、取得失敗を区別し、構造と条件付き利用可能性を追跡可能にする | Evidenceは参照・計算の根拠で、実通電・実運転・安全の独立した証明ではない | [graph_requirement_rules.py](../../backend/src/linescope/domain/graph_requirement_rules.py)、[graph_availability.py](../../backend/src/linescope/application/graph_availability.py)、[alternative_evidence.py](../../backend/src/linescope/application/alternative_evidence.py)、[F2検証](2026-10-26-alternative-power-investigation.md) |

### 現行のLLM・Embedding利用を区別する

静的に追った標準組立は`bootstrap.build_api_services`からのAPI構成。コードの存在、設定値の存在、実際に呼ばれる経路を区別する。今回runtime・私有設定やログを使った再検証はしていない。

| 処理 | 現在の標準経路 | 動画での説明 |
|---|---|---|
| 通常質問欄 | `/agent`→`AgentApplication.run`→`DemoQuestions.answer`→共通検索／固定9観点→`RegisteredQuestionReads`。生成LLMへfallbackしない | 対象照合・範囲判定・値・回答はコード。LLMによる自由文理解を現行機能として説明しない |
| 明示Graph | `関係分析 `形式→`ReadAgent.run`の明示分岐→固定Tool呼出し。モデル呼出しループより前にreturn | `ReadAgent`というクラス名だけでLLMが探索していると判断しない |
| 正式入力比較・変更準備・承認・実行 | `RegisteredDecisions`や明示command、Approval／Executeの認可済み処理 | 生成モデルに算術・業務権限・確定を委ねない |
| 独立した文書検索 | `KnowledgeRetrieval`→Index検索→`OllamaEmbedding.encode`の`/api/embed`→Qdrant→正本再照合。応答は定型文と抜粋 | Embeddingモデルは使うが、検索を生成LLMの文章作成と呼ばない。Ollamaという接続先が同じでも役割は別 |
| 生成LLMの接続コード | `OllamaClient`と`ReadAgent`の通常loopは残る。しかし標準の通常質問はその前に`DemoQuestions`で処理し、明示Graphはloop前に返す | 過去のRead Agent検証と、現行コードに保持された処理として説明する。現行質問欄で利用中とはしない |
| 旧比較のLLM補助 | `DemoDecisionFlow`→`decision_summary`には任意のLLMによる表示順選択が残るが、現行bootstrapは`RegisteredDecisions`を組み立てる | 標準デモでLLMが比較の説明順を選んでいるとは紹介しない |

経路の根拠：[AgentApplication](../../backend/src/linescope/application/agent_service.py)、[bootstrap](../../backend/src/linescope/bootstrap.py)、[ReadAgentの明示分岐](../../backend/src/linescope/agent/read_agent.py)、[登録比較](../../backend/src/linescope/application/registered_decision.py)、[文書検索](../../backend/src/linescope/application/knowledge_flow.py)、[旧表示順処理](../../backend/src/linescope/application/decision_summary.py)。

### PR #276 → #277を技術的判断として説明する

1. 当初の期待：LLMが自由文を解釈して取得へ進み、根拠のある回答を作る。
2. 直面した問題：保証書の保管場所を関連文書へ読み替えるなど、質問と違う観点の確認へ進む。根拠IDが正しくても意味の対応は保証されなかった。
3. 固定した評価：旧H6の原文21問×3は58/63、補助6問×3は15/18。誤受理5、口語取りこぼし3。誤受理5と不適切確認5は同じ応答なので二重計上しない。これは架空の値を5回断定したという意味ではない。技術的UNVERIFIABLE 0でも業務上の受入は未達だった。
4. 採用しなかった方向：自由文の意味理解・多段の意味確認をデモ完成の必須条件にし続けること。H7の明示選択等も試したが、質問欄のみという開発者の方針で別案へ移行した。
5. #277の決定：固定9観点の語彙・例文で照会範囲を限定し、対象検索・型付きRead・Evidence・コード回答を採用。対応外の問いを近い情報へ置き換えず案内する。取りこぼしを含む限界を残し、一般の口語理解を完成条件から外した。
6. 結論：LLM一般の能力を断定せず、この業務要求と観測結果から責任の境界を変えた。現方式の成功で旧H6の未達を修正済みとは扱わない。

根拠は[保存した旧実測](https://github.com/philippos2/line-scope/blob/archive/pr276-20261026/docs/history/2026-10-23-agent-question-round2.md)、[仕切り直し記録](2026-10-26-demo-question-restart.md)、[現方式の検証と試行内訳](2026-10-26-demo-question-results.md)。現方式の固定46問の最終138応答一致は、一般理解の正解率ではない。保留R03を失敗後の修正に使用したため未見の一般化評価とも呼ばない。動画は主要指標を要約し、全原文・再試行・個別判定はリンク先に委ねる。

承認付き更新では、自己承認の扱いを全カテゴリ一律としない。入力4カテゴリは別manager承認・元requester実行、他カテゴリは[access-control](../requirements/access-control.md)の規則に従う。供給状態は今回読取専用としたB案の判断を紹介し、未実装の承認付き状態変更を実演しない。

## 5. 第1弾と共用する収録素材

以下は今後収録する第1弾素材の共用計画。素材が収録済みという意味ではない。第1弾の絵コンテに追加場面を要求せず、同じ実画面の別の切り出し／編集上の図解で対応する。

| 第1弾の承認済み場面 | 第2弾での使い方 |
|---|---|
| M-204の下流・代表経路 | Objectの型と関係意味論、到達と成立の違いを説明する短い引用 |
| M-208候補とP-100能力評価 | 構造と数値・対象製品の限定を分ける説明 |
| M-204/M-208共通電源R-02と三値説明図 | 必須依存と三値評価の共通例。実画面AVAILABLEと説明図を区別 |
| `m204`照会と未対応質問の案内 | #277の現在の境界の例。旧失敗の再現や汎用理解の証拠にしない |
| Evidence／登録状態の表示 | 参照元・version・観測範囲と、現実の真偽保証の違い |

第2弾固有の素材は、承認後に作る責務・データフロー・更新手順・旧新方式の説明図を中心とする。#276の現行環境への再配備・実モデル再評価や、新しい業務書込みを収録の前提にしない。過去の応答・図解を使う場合は旧版の記録であると表示する。

## 6. 説明しないこと・未検証事項

- 全API・全テーブル・全タブ、lock順／SQL／Cypherの網羅、セットアップのチュートリアル、モデル内部の推論は扱わない。
- 実工場の実停止・実通電・安全・品質・経済効果、Graph DBだけの方式との定量比較、3ストアの性能必然性を主張しない。
- 現行の限定照会を生成LLMによる汎用自然言語理解と呼ばない。未知の質問全体に対する誤受理0の保証をしない。
- 各技術・Frameworkの選定に記録のない動機を付け足さない。性能比較・代替案の優劣は未計測。SQLAlchemy採用を完全DB非依存やRaw SQL全廃と呼ばない。
- 元の中断原因、正式起動直後partial、他3カテゴリの実書込み、UNAVAILABLE／UNKNOWNの実ブラウザ、正式移行後のEmbedding再実行は未確認を保持する。文書でまとめた結果を今回の再実行と呼ばない。
- 現行コードの静的接続確認と、正式環境で実際にモデルが呼ばれたかのruntime確認は別。今回はモデル・API・ブラウザ・試験を実行していない。制作時には対象版と説明の根拠を再確認する。

## 次の区切り

第2弾のこの企画案を開発者がレビューするまで、第1弾の制作を始めない。レビュー後は既存資産を再利用して第1弾を制作する。第2弾の詳細台本・絵コンテ・収録は、その後の別指示まで進めない。今回の調査許可を詳細制作の承認へ広げない。第1弾の承認済み絵コンテ本文は不変。現時点の変更は本書・ロードマップ・ガントだけ。

## 確認方法と今回の差分

今回実施したのは正本・コードの呼出経路・既存の検証記録の静的照合。新規の自動試験・直接API・実ブラウザ・実モデル検証は未実施。変更Markdownのローカルリンク先51件の存在、SVG XMLと日本語描画、`git diff --check`を確認した。差分は本書・roadmap・ガントの3文書だけで、第1弾の承認済み絵コンテは変更していない。文書PRの既存CI結果はPR本文へ記録し、製品検証と区別する。
