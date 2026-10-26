# 技術検証デモのドキュメント最終整理（F3）

## 目的・制約・完了判定

開発者は、実装追加ではなく、LineScopeで何を検証し、何が確認され、何が未確認かを第三者へ説明する文書整理を指示した。棚卸し計画の既存18更新・新規2作成、計20ファイルを承認した。範囲は文書のみ。製品コード・DB・seed・API・UI・認証・試験・稼働環境を変更しない。過去の実測・失敗・旧H6/H7を改変しない。

完了判定は、範囲と検証結果の相互参照、6項目での検証結果整理、旧説明の適用範囲の明示、根拠とリンク整合、既存CI、開発者の最終レビュー。mergeは開発者が行う。

## 着手状態とstashの扱い

PR #279はmerge済み（`1b8c5953a9a15e97c90e4821754a724fa9ae17bd`）。mainをfast-forwardし、`docs/demo-verification-summary`で文書のみを変更した。旧branch・タグ・コミット履歴は削除・書換えしていない。

「やること／やらないこと」のstash `c48d3e3345d1ea1600cc2e98a0a309a379e336c8`はapply/popせず、diffを読んで有効な定義だけをrequirements §9.1・§11.2へ選択的に取り込んだ。stash自体と他の退避物は保持する。

| 退避案の扱い | 内容 |
|---|---|
| 採用 | 単一工場・登録関係・損害額／能力の条件付き表示・正式入力・0件の区別・承認と実行の分離・運転許可を出さない境界 |
| 現行仕様へ更新 | 質問は#277の固定9観点・コード回答・LLM不使用。R-02は#278のM-204/M-208共通必須電源・三値読取専用 |
| 不採用 | 実LLMを通常質問へ使う旧説明、M-208の電源未追加・供給状態未モデル化の旧説明、未採用機能を確定した後続予定にする扱い |

## 棚卸しと文書構成

文書入口の19文書の正本責務を維持した。着手時のGit管理済みdocs配下Markdown241文書のうち履歴208文書は一覧・見出しを棚卸しし、今回の主張に必要な原記録を詳しく照合した。全履歴本文を精読したという意味ではない。

現行の範囲はrequirementsに集約し、新しい範囲正本は作らない。新しい検証結果文書は仕様・受入基準を追加せず、目的・方法・観測結果・結論・限界・根拠の6項目でA〜Hを整理した。READMEは入口とし、仕様や操作の詳細を重複保持しない。

| 変更ファイル（20） | 変更の理由 |
|---|---|
| `README.md` | 技術検証の目的・範囲・知見・正式環境への入口。通常質問をLLM Tool選択と説明する旧記述を修正 |
| `docs/deliverables.md` | 正本責務を維持し、検証結果・現行質問・計画／履歴の適用範囲を案内 |
| `docs/requirements/requirements.md` | stashから§9.1・§11.2を選択的に取り込み、実装範囲と非保証・未検証を区別 |
| `docs/design-faq.md` | 旧LLM説明・一括検証済みとの読め方を修正し、意味論の効果と未実証を区別 |
| `docs/design/architecture.md` | Frontend・Graph・RAGが後続という古い状態を更新。概念→データ→状態→規則→Evidence→表示を整理 |
| `docs/design/agent-design.md` | 現行質問と旧LLM設計を区別。Q2/Q4の旧構想を現在の必須未着手計画とは扱わない |
| `docs/design/frontend-console.md` | 現行6タブ、左検索、質問の対象省略、最新順履歴と適用済み改修の説明へ整合 |
| `docs/design/post265-ui-correction-plan.md` | 計画時点の状態と現行の§11.2共通規約を区別。旧数値や検証本文は保存 |
| `docs/getting-started.md` | 正式5173/API8002と新規構築既定値を分離。旧project起動手順を除き、通常質問にLLM不要と明示 |
| `docs/implementation-design/interaction-flow.md` | 通常質問の決定論的経路、登録供給状態・コード表示との接続を明示 |
| `docs/implementation-design/prompt-design.md` | 旧LLM指示の適用範囲を明示し、現行質問への適用を否定 |
| `docs/implementation-design/evals.md` | 現行照会と旧モデル評価を分離し、保留R03と試行の扱いを明示 |
| `docs/implementation-design/test-plan.md` | 試験設計と実施実績を分離。試験ケース・期待値は不変 |
| `docs/requirements/acceptance-criteria.md` | 受入基準を合格実績と混同しない入口を追加。ACの意味は変更しない |
| `docs/implementation-design/operations.md` | 正式運用先、旧基盤段階の説明、worker内部とCompose再起動の違いを整理 |
| `docs/roadmap.md` | #279完了、F3承認・着手、確定残1 PRへ更新 |
| `docs/roadmap-gantt.svg` | 暦日軸の実施日バーと凡例。将来の工数・完了日は捏造しない |
| `docs/history/README.md` | #277〜#279・F3と旧方式へ辿る索引を追加 |
| `docs/demo/verified-findings.md`（新規） | 検証の知見と方法・根拠・限界を6項目で整理 |
| 本書（新規） | 承認範囲、変更理由、静的確認・CIと未確認の引渡し記録 |

## 結論と根拠の対応

| 検証結果の節 | 照合した根拠 | 今回加えていない主張 |
|---|---|---|
| A・B 意味論と責務分離 | domain-model、architecture、data-model、Graph業務シナリオ、#277下流結果、#278三値記録 | 実工場効果・Graph単独との比較優位・分散同時Snapshot |
| C 三値評価 | #278調査履歴の追加22・API9・AVAILABLE画面 | UNAVAILABLE/UNKNOWNの実ブラウザ成功や実通電 |
| D・E 質問と不明の扱い | #277原文比較、全応答ZIP、候補名修正記録 | 任意質問の成功・旧H6の改善・保留R03の未見評価 |
| F 方式の割り切り | PR #276アーカイブの原実測、#277仕切り直し | 旧未達の帳消しや、LLM/H7全般の否定 |
| G 更新と結果不明 | #272実通信切断・経済入力実書込記録 | 他3カテゴリの実書込確認・元の中断原因特定 |
| H 検索と正式移行 | 合成検索baseline、#279の保持・再起動記録 | 移行時の新規Embedding実行・初回partial原因特定 |

旧H6の58/63・15/18、誤受理5、口語取りこぼし3、不適切確認5、技術的UNVERIFIABLE 0はアーカイブと照合した。誤受理5と不適切確認5を別の10応答として合算しない。#277の試行416と後続174、各最終試行を別記し、成功率・独立標本を水増ししない。

## 確認した範囲

- 原記録を読んだ静的照合。今回は製品の自動試験、直接API、ブラウザ、実モデルを再実行していない。
- 承認20ファイルの範囲、旧記録・fixtures・製品差分なし、stash保持を差分で確認する。
- 変更20ファイルのローカル文書リンク431件を検査し、ファイル・見出しアンカーの欠落0件。READMEとdocs全体から変更文書へ向かう流入リンクにも、新たなアンカー切れ0件。
- `git diff --check`成功。SVGのXMLを解析し、日本語フォントをプロセス内だけに追加した一時レンダリングで、暦日軸・バー・凡例・文字の収まりを確認した。フォントと画像は/tmpのみで、実行環境の設定やRepositoryへの追加はない。製品のブラウザ検証ではない。
- PR [#280](https://github.com/philippos2/line-scope/pull/280)をDraftで作成。最初の文書head `79ecdf4cc0a0ec1aca3370b6f6280d6414cfdc8d`の[CI run 40354851968](https://github.com/philippos2/line-scope/actions/runs/40354851968)は成功。対象判定7秒、Frontend lint・型・整形・build 39秒、集約check 6秒、別workflowのPR title 2秒。Backend・runtimeは文書のみの差分判定により予定どおりskipで、Backend全件を今回成功したとは書かない。Vitestも未実行。
- 本結果追記と原実測の意味の補足は文書だけの後続commitにする。最新headのCIは追記後に再確認し、PR本文に対象headと結果を記録する。過去headの成功を最新headへ代用せず、Draftのまま最終レビューを待つ。

## 未確認・残す制約

起動直後partialの原因、元の通信中断原因、他3カテゴリの実書込み、UNAVAILABLE/UNKNOWNの実ブラウザ、正式移行後のEmbedding実行、実工場での効果と比較実験は未確認のまま。今回の文書整理で追加実装・実行・合格へ変更しない。最終レビュー・merge判断は開発者に委ねる。
