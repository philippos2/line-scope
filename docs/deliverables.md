# LineScope ドキュメント成果物一覧

## 1. 目的

本書はLineScopeの設計・実装に使用する20文書の体系と責務を定義する。

文書群は `requirements`（要件定義）、`design`（設計）、`implementation-design`（実装設計）の3群に分ける。

## 2. requirements — 要件定義

1. `requirements/requirements.md` — 機能要件・業務要件
2. `requirements/domain-model.md` — 業務概念・関係意味論
3. `requirements/access-control.md` — 権限・承認要件
4. `requirements/use-cases.md` — 既存処理UC-01〜UC-21、業務目的UC-B01〜UC-B17
5. `requirements/non-functional-requirements.md` — 非機能要件
6. `requirements/acceptance-criteria.md` — 受入基準・要件トレーサビリティ

## 3. design — 設計

7. `design/architecture.md` — システム構成・責務境界
8. `design/agent-design.md` — Agent実行設計
9. `design/data-model.md` — PostgreSQL / Neo4jデータ設計

## 4. implementation-design — 実装設計

10. `implementation-design/api-tools.md` — HTTP API / Tool契約
11. `implementation-design/transaction-design.md` — 更新・承認・競合・Outbox・状態遷移
12. `implementation-design/interaction-flow.md` — 処理シーケンス
13. `implementation-design/prompt-design.md` — LLM指示設計
14. `implementation-design/rag-design.md` — RAG / Qdrant
15. `implementation-design/evals.md` — AI品質評価
16. `implementation-design/test-plan.md` — 決定論的テスト
17. `implementation-design/operations.md` — 運用・監視・復旧
18. `implementation-design/AGENTS.md` — Codex等の実装支援Agent向け規則

19. `implementation-design/business-scenarios.md` — BS-01〜19、BS-G01、固定fixture期待値・UC ↔ BS ↔ AC対応

本書自身を含めて合計20文書とする。従来19文書を保持し、Use Caseと業務受入試験を分離するため本書改訂で1文書を追加した。

## 5. 責務の正本

| 事項 | 正本文書 |
|---|---|
| 業務目的・プロダクト範囲・業務要件 | `requirements.md` |
| 業務概念・Graph意味論 | `domain-model.md` |
| ロール・承認・履歴閲覧範囲 | `access-control.md` |
| 業務フロー | `use-cases.md` |
| 非機能要件 | `non-functional-requirements.md` |
| 受入判定・トレーサビリティ | `acceptance-criteria.md` |
| システム境界 | `architecture.md` |
| Agent責務 | `agent-design.md` |
| DB・Graph物理モデル | `data-model.md` |
| HTTP / Tool契約 | `api-tools.md` |
| Transaction / Lock / Outbox / 状態遷移 | `transaction-design.md` |
| シーケンス | `interaction-flow.md` |
| LLM指示 | `prompt-design.md` |
| RAG | `rag-design.md` |
| AI評価 | `evals.md` |
| 決定論的テスト・試験階層 | `test-plan.md` |
| Business Scenario・fixture期待値・UC ↔ BS ↔ AC | `business-scenarios.md` |
| 運用・構造化ログ契約・保存／閲覧方針 | `operations.md` |
| 実装支援Agent作業規則 | `AGENTS.md` |

同じ事項を複数文書が説明する場合、上表の正本文書に従う。下位文書が上位要件を暗黙変更してはならない。

要件と実現方式の順序はrequirements §2.1を正とする。業務目的 → Use Case → Business Scenario受入仕様 → Ontology / DB / API設計 → Outbox / Projection / lock等の方式とする。Safety / SecurityのHard Constraintを除き上位意図を優先し、矛盾する下位設計を明示改訂する。各事項の正本責務と、この意図優先の順序を混同しない。

## 6. v1デモ実装スコープ

- 単一工場
- 現サーバサイド実装フェーズはHTTP API / curl中心。Frontendはサーバサイド完成後に構築する
- 固定デモユーザーによる認証を許容
- PostgreSQLを業務正本とする
- Neo4jを依存関係探索用派生Read Modelとする
- QdrantをRAG用派生Vector Indexとする
- PostgreSQL Transactional Outboxを用いてNeo4jへ反映する
- Graph分析は同期状態 `CURRENT` の場合のみ正常利用する
- 1つのProductionOperationは複数Equipmentを使用可能
- 承認有効期限は30分

## 7. レビュー記録

docs/history配下のレビュー・変更履歴は正本文書外の記録であり仕様正本ではない。履歴一覧は[history/README.md](history/README.md)を参照する。PO判断待ちは各正本文書に記載し、推測で操作を有効化しない。確定後API / DB / AC / Testも更新する。

## 8. 業務判断支援追加の適用方針

POはUC-B01〜15とBusiness Scenarioの意図を既存仕様との不整合時に優先する方針を確定した。能力・リスク・経済評価・対応案比較をプロダクト要件に含める。確定済みの要件、PO未決定事項、設計契約、実装・試験状況を区別する。

未決定業務ルールの正本はrequirements §14.3（PO-B01〜08）。新機能の物理スキーマ、Tool契約、更新カテゴリを未決定のまま既存v1へ追加しない。基本の正本／派生モデル、人間のApproval / Execute、Outbox、Graph同期境界は維持する。
