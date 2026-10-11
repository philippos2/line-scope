# 開発ガイダンス採用 — Phase 1C

## 採用範囲

基準main `40f3abb`。POから「次の工程へ進む」と指示され、[Phase 1A](2026-10-11-engineering-guidance-phase-1a.md)・[Phase 1B](2026-10-11-engineering-guidance-phase-1b.md)を踏まえ、開発ガイダンスの配置と手順を正式化した。業務仕様の変更、本体refactoring、未決のPO-B01〜08の確定は含まない。

| 層 | 配置・責務 |
|---|---|
| Canonical Documents | deliverablesの責務表を維持。業務意味・契約・状態・技術選定は各正本 |
| AGENTS | rootはRepository全体の入口・共通原則・Skill発動条件。既存docs内AGENTSは実装支援規則の正本 |
| Skills | `.agents/skills/`の四つのSKILL.mdをGit管理。作業・レビュー・検証の方法 |
| Tests / CI | 既存の必須CIと自動試験を維持。今回、新しいarchitecture guardrailは未導入 |

## Skill候補の判断

四つの草案を移動し、draft表示を除去、正本参照の相対パスを修正した。既定の自動選択を無効化する設定は追加していない。現在のセッションに動的登録されたことや、他のAgent環境での自動発見までは確認していない。root AGENTSからも該当作業で読む経路を用意した。

- architecture-review: 採用。責務境界・依存方向・実call path・SOLIDの適用判断。refactoringと文書整合レビューを当面統合する。
- secure-coding: 採用。identity/authority、入力、parameter / identifier、least privilege、秘匿。database-accessは当面ここへ統合する。
- transaction-review: 採用。更新原子性、lock/version、失敗記録、retry、Graph Projection/Rebuild。graph-projectionは当面ここへ統合する。
- code-change-verification: 採用。Dockerでの検証選択、意味論的assert、commit/PR/CI/cleanupとPOへの引渡し。
- agent-tool-contract / scenario-testing: 独立化を保留。対象契約は関連Skillと正本で確認し、繰り返し作業で独立した手順の価値が出た時点で分ける。

草案を正式Skillと二重に保守しない。草案の旧本文はGit履歴に残し、旧indexは正式配置へのリンクにした。汎用SOLID解説・仕様の数値・進捗一覧・未要求の補助scriptはSkillへ追加しない。

## Phase 1Bを反映した補足

transaction Skillへ、定義と実装の区別、例外継承とcatch順、deadlock / lock timeout / 通信途絶 / commit不明の区別を追加した。verification Skillへ、Dockerイメージの再buildまたは変更コードmountを確認し、古いCOPY済みコードを試験しない手順を追加した。

FAILED遷移、ApplicationのPersistence依存、Graph Read / Qdrant接続等の残件を、このガイダンス整備によって実装済みとは扱わない。

## Guardrailの次候補

追加するなら、次の実装変更と一緒に狭い検査から始める。

1. domainのHTTP / DB driver import禁止、業務HTTP handlerのSQL / Core / Session操作禁止。composition rootとreadinessは意図した例外として確認する。
2. 純粋PolicyからDB-awareモジュールへの依存は、既存型・定数の分離後に検査する。現在の違反を隠すための広いallow-listを先に作らない。
3. FAILEDの別transaction失効、deadlock分類の変更時には終端保護・rollback・error contractの実DB回帰を追加する。

既存の注入・権限・rollback・並行更新・Projection試験とruffを削除・弱化しない。Skillを読めば守られるという前提で、機械的検査の代替にしない。

## 検証と限界

四つのSkillのquick_validate、変更Markdownの相対リンク、Git ignore状態、diff整合を確認する。代表作業（通常Read、重要更新、移動refactoring、文書のみ、PR引渡し）への発動条件と手順を照合する。独立Agentによる行動評価は未実施。Production code・DB・migration・CI定義の変更はなく、ローカル全pytestは再実行しない。必須CIの実測結果はPR本文へ記録する。

ガイダンスは履歴より現在の正本・コードを優先して使い、実作業で判明した不足へ限定修正する。新しいAgentが過去の会話を知らなくても、入口→対象正本→Skill→実経路→必要試験を辿れる状態を維持する。

## 採用後の名称・主体の明確化

開発者の指摘により、正式Skillの名前を`backend-architecture`、`backend-secure-coding`、`backend-transaction-review`、`backend-verification`へ変更し、folderとfrontmatter nameを一致させた。上記の採用時名称・旧草案は時点の記録。rootと旧indexの現在のリンクは新名称へ更新する。開発の指示・PR mergeは「開発者」、業務仕様の判断は「PO」、システム利用は「エンドユーザー」、コードの呼出側は「利用側component」と表記する。Frontend用Skillは着手時に必要なものを追加する。
