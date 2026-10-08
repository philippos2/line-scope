# LineScope ドキュメント成果物一覧

## 1. 目的

本書はLineScopeの設計・実装に使用する19文書の体系と責務を定義する。

文書群は `requirements`（要件定義）、`design`（設計）、`implementation-design`（実装設計）の3群に分ける。

## 2. requirements — 要件定義

1. `requirements/requirements.md` — 機能要件・業務要件
2. `requirements/domain-model.md` — 業務概念・関係意味論
3. `requirements/access-control.md` — 権限・承認要件
4. `requirements/use-cases.md` — UC-01〜UC-21
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

本書自身を含めて合計19文書とする。

## 5. 責務の正本

| 事項 | 正本文書 |
|---|---|
| 業務要件 | `requirements.md` |
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
| 決定論的テスト | `test-plan.md` |
| 運用 | `operations.md` |
| 実装支援Agent作業規則 | `AGENTS.md` |

同じ事項を複数文書が説明する場合、上表の正本文書に従う。下位文書が上位要件を暗黙変更してはならない。

## 6. v1デモ実装スコープ

- 単一工場
- UIなし、HTTP API / curl中心
- 固定デモユーザーによる認証を許容
- PostgreSQLを業務正本とする
- Neo4jを依存関係探索用派生Read Modelとする
- QdrantをRAG用派生Vector Indexとする
- PostgreSQL Transactional Outboxを用いてNeo4jへ反映する
- Graph分析は同期状態 `CURRENT` の場合のみ正常利用する
- 1つのProductionOperationは複数Equipmentを使用可能
- 承認有効期限は30分

## 7. レビュー記録

docs/history配下のレビュー・変更履歴は19文書外の記録であり仕様正本ではない。履歴一覧は[history/README.md](history/README.md)を参照する。PO判断待ちは各正本文書に記載し、推測で操作を有効化しない。確定後API / DB / AC / Testも更新する。
