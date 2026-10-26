# F2：代替設備の必須電源依存 — 影響調査と実装案

状態：調査完了・実装未承認。起点mainは#277のmerge commit `334434c2793999c6d2e05ecc71e9417255f4948d`。

## 目的・制約・完了判定

目的は、M-208にも実態に沿う必須電源依存を表示し、登録された電源の供給状態を根拠として代替利用可能性を判定すること。図に辺を描くだけ、または常に利用可能と仮定して完了としない。

- R-02をM-204/M-208の共通電源とする案を採る。これはデモ構成の提案で、PO確定前にデータを変えない。
- activeは登録上の有効性であり、通電・供給の状態に転用しない。
- 未登録・UNKNOWN・取得障害・探索不完全を利用可能へ変換しない。M-208のRUNNINGから電源の健全性を推定しない。
- 構造成立・登録状態による利用可能性と、実際の代替運転・能力・安全・品質・経済影響を分離する。
- 一般のインフラ状態として実装し、R-02やM-208を条件にした判定分岐を作らない。Processを一緒にAVAILABLEへ変えない。
- 質問欄の9観点・語彙・質問UI・LLM不使用は維持。新しい質問解析やモデルを追加しない。
- F2を1 PRとして進める案。F3のstashは適用しない。実装・DB変更・seed再投入・既存環境変更は今回未実施。

受入は、M-208の上流に必須SUPPLIESと供給元の名称が見えること、供給状態が利用可能/不可/不明の場合に既存の必須依存AND評価へ正しく入ること、根拠と更新版が追跡できること。供給が利用可能でも、他の必須依存やM-208自身の状態が満たされなければ代替可能とはしない。

## コードで確認した原因

| 層・根拠 | 現状 | 影響 |
|---|---|---|
| `docs/demo/data/scenario1.json` | R-02→M-204のrequired=true SUPPLIESだけ。M-208への供給は未登録 | M-208の上流に電源が描かれない |
| `docs/demo/scenario1.md` | A案として必須供給を外し、M-208のavailability=AVAILABLEを維持した経緯を記載 | 今回はこの不自然な構成を正す。図だけの不具合ではない |
| `domain-model.md` §15.1、`graph_requirement_rules.py`、`graph_substitute_candidate.py` | statefulはEquipment/ProductionOperationだけ。InfrastructureResourceは必ずUNKNOWN | 辺だけ追加すると構造成立し得るが、代替利用可能性はUNKNOWNになる |
| `graph/analysis_states.py`、`application/graph_availability.py`、`persistence/core_reads.py` | 設備と生産作業の状態を一括観測。インフラの状態は観測しない | 電源の状態を取得する経路が必要 |
| `data-model.md` infrastructure_resource | id/code/name/type/version/active。供給状態の列・別表はない | 保存元の追加が必要 |
| `domain/snapshot.py`、`proposals.py`、`approval_policy.py`、`execute_policy.py` | インフラ状態のTarget/カテゴリ/権限がない | 設備状態の権限を暗黙適用できない |
| `alternative_analysis.py`、`graph_exclusion_fulfillment.py` | 構造・候補・必須依存の三値評価を分離済み | この仕組みを再利用できる。新しい評価器は不要 |
| `core_graph_snapshot.py`、`application/execute.py` | Graphは関係とマスター、状態はPostgreSQLで観測。EquipmentState更新自体はGraphへの状態複製をしない | インフラ状態もGraphへ二重保存しない。供給辺は既存DEPENDENCYのOutbox/Projectionを使う |

以上は静的照合。今回、試験・実API・DB照会・実モデルを実行した結果ではない。

## 提案する最小実装

### 1. 供給状態の業務規則（PO承認が必要）

登録された供給状態を`AVAILABLE / UNAVAILABLE / UNKNOWN`の三値とする案。表示は『登録上：供給可能／供給不可／不明』。電源専用の稼働コードにせず、インフラの供給可能性として定義する。これは通電センサーによる実測や運転許可ではない。

- 現在のインフラマスターと別に現在状態・version・更新時刻を持つ。マスターversionと状態versionを混同しない。
- 既存資源に状態がなければUNKNOWN。migrationでAVAILABLEを補わない。
- 新しいデモのR-02には、架空工場の明示的な初期条件としてAVAILABLEを登録する案。共有電源を停止した別シナリオは追加しない。
- 現在状態を過去へ推定せず、既存の過去as_ofではUNKNOWNを維持する。

### 2. 状態変更の統制（PO承認が必要）

提案は新しい`InfrastructureResourceState` Target / `INFRASTRUCTURE_STATE`カテゴリを、既存Prepare→別操作でApprove→元の依頼者がExecuteする機構へ追加すること。保存済みSnapshot v1〜v5は書き換えず、新Targetの形式を別のschema versionとして追加する案。例外SQLや管理用の直接書換えをUIへ露出しない。Snapshot、expected_version、retry、期限30分、履歴・Auditの原子性、現在権限の再検証を維持する。

権限の推奨案は、参照は認証済み全職務、要求・実行は保全または工場管理者、承認は要求者とは別の工場管理者、自己承認不可。共通電源が複数設備に及ぶため、生産管理・現場の更新要求と自己承認を推測で許可しない。既存EquipmentStateの権限と同一ではなく、POの決定を要する提案である。

新しい自然文の変更構文は作らず、既存の構造化変更と変更要求IDによる承認・実行を使う。書込み用HTTP経路を無制限に増やさない。

### 3. 取得・判定・表示

- 同じ観測時刻の一括SELECTへインフラ状態を加え、設備/作業/資源を型付きIDで照合する。欠落はUNKNOWN、取得失敗はエラーとして区別する。
- InfrastructureResourceだけをstatefulへ加え、既存の候補の必須依存評価へ渡す。ProcessのUNKNOWNは維持する。
- 代替/SPOFのEvidenceへ資源の現在状態・状態version・観測時刻・欠落情報を追加する。上流/下流にも取得可能な状態の根拠を揃える。Graph同期CURRENTの入口/出口と既存のlock境界を維持する。
- `get_infrastructure_resource`の既存マスター項目は維持し、登録供給状態を追加項目として取得する案。Graph本体へ供給状態を複製しない。新しい観点選択UIは作らない。
- 既存のGraph・選択した項目・代替の提案で供給状態と限定を示す。型付きノードIDで設備と資源の状態を区別する。
- 実行後は既存の更新前表示を付け、明示的な再取得で更新する。質問の対象や取得済み結果を勝手に切り替えない。

## 変更対象の見込み

具体名が未作成のものは『案』。製品変更前に契約と業務規則を承認する。

| 範囲 | 主なファイル・作業 |
|---|---|
| DB/Read権限 | 新migration `014_infrastructure_state.sql`（案）、`persistence/db_roles.py`、`core_reads.py`。現在状態と必要な履歴の保存、runtime/queryの最小権限 |
| 状態変更 | `domain/snapshot.py`、新しい状態入力検証/Prepare（案）、`application/tools.py`、`proposals.py`、`approval_policy.py`、`execute_policy.py`、`execute.py`、対応Core。既存状態更新と同じ承認基盤を再利用 |
| 組立/構造化入口 | `bootstrap.py`、`agent/update_intent.py`の構造化カテゴリallow-list、`application/structured_command.py`との接続。自然文構文は追加しない |
| Graph観測 | `graph/analysis_states.py`、`application/graph_availability.py`、`domain/graph_requirement_rules.py`、`graph_substitute_candidate.py` |
| Evidence | `application/graph_evidence.py`、`alternative_evidence.py`、`spof_evidence.py`。既存Tool出力への追加で、対象・状態version・時刻を検証 |
| デモ初期条件 | `docs/demo/data/scenario1.json`、`demo_file_seed.py`、`persistence/core_demo_seed.py`、`docs/demo/scenario1.md`。既存JSONとの互換を維持し、新状態の宣言を明示する。既存登録値をseed再実行で無断上書きしない |
| Frontend | investigationのモデル/表示、Graphの登録状態表示、既存の構造化変更フォームとActionPanelの権限・段階案内。質問欄は維持 |
| 正本 | requirements/domain-model/access-control/data-model/API/transaction/受入の該当節。承認前は本計画だけに提案として置く |

製品は約25〜35ファイル、設計/操作文書6〜8ファイルを見込む。単純なJSON一行修正の規模ではない。実装確定時に具体的な差分リストを再確認し、不要な共通化・全面改修は含めない。

## 試験・工数・段取り

実装案の見込みは5〜7作業日（レビュー・承認待ちを除く）。範囲/権限の確定とDB/Read 1〜1.5日、変更統制 1.5〜2日、Graph/Evidence 1〜1.5日、表示・デモ・API/ブラウザ・CI/記録 1.5〜2日。合計5〜7日。F3はF2 merge後に開始し、この見積もりへ混ぜない。

新規自動試験は32〜48ケースの見込み。三値・欠落・取得失敗・過去時点・不完全、認可・自己承認・owner・期限・version競合・再送・rollback/Audit、Graph/Evidence、JSON・UIの境界を含む。既存の共通承認/実行・Graph/質問欄回帰も維持する。全直積にせず同値分割・境界と重大Invariantを選び、権限/transactionの必要条件を件数合わせで削らない。

20件を超えるため、業務規則の決定後に、展開後の正確な件数と防ぐ失敗の対応表を提出し、了承前に追加・実行しない。今回の調査では試験を追加・実行していない。実モデルは不要。

同じF2のDraft PRに、調査→規則/試験/負荷承認→実装→実DB/API/ブラウザ/CI→開発者確認を収める。調査文書用に別PRを増やさず、既定の残りはF2・F3の2 PRを維持する。実装で想定を超える変更が必要なら停止して影響を報告する。

既存5173/5174のDB・seed・認証は今回変更しない。実装後のAPI/書込み確認は使い捨ての専用環境で計画し、操作・認証・負荷を提示する。5174へのデータ変更/状態操作は別途具体的な手順を示して承認を得る。

## 開発者・POへ求める決定

1. R-02を両設備の共通電源とし、登録供給状態を三値で管理する構成・F2の実装範囲（5〜7日）を採るか。
2. 参照は全職務、要求/実行は保全・工場管理者、承認は別の工場管理者、自己承認不可、という権限案を採るか。

承認がなければ、辺だけ追加して利用可能性をUNKNOWNへ変えたり、activeを通電扱いしたりしない。JSONだけでは当初受入を満たさないことを踏まえ、ここで実装を停止する。
