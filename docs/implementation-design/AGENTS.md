# AGENTS.md

## 1. 目的

Codex等の実装支援AgentがLineScope文書を推測で変更せず実装するための規則。

## 2. 最初に読む文書

`deliverables.md` を読み、各事項の正本文書を確認する。

「上位/下位」の一般順位で勝手に上書きせず、deliverablesの責務表に従う。

## 3. 不整合

正本文書同士の矛盾、未定義、実装不能を発見した場合は、推測実装せず明示する。

## 4. Security

Trusted Execution ContextはAPI層から注入する。
LLM出力・利用者自己申告をrole/user_idの根拠にしない。

## 5. Approval / Execute

AgentがApprovalまたはExecuteを確定操作として行ってはならない。

- Approval: Approval API
- Execute: requester専用Execute API

詳細は `api-tools.md` と `transaction-design.md` を正とする。

## 6. Data Stores

製品・責務の正本は `architecture.md` と `data-model.md`。
DB構造をAGENTS.mdの記述から推測しない。

## 7. Graph

意味論は `domain-model.md`。
物理Projectionは `data-model.md`。
同期・Outbox・lockは `transaction-design.md`。
Tool契約は `api-tools.md`。

## 8. RAG

`rag-design.md` を正とする。
Qdrant metadataのみで最終認可しない。

## 9. Testing

変更に対応するACとtest-planを確認する。
重大Failに対応する自動テストなしで完了扱いしない。

## 10. LogiScope

LogiScopeは一般化可能な実装パターンの参考として参照してよい。
LineScopeの要件、ドメインモデル、データモデル、API、Tool一覧、権限、承認、トランザクション、Graph設計、技術選定はdeliverables.mdが定義する文書群を正とし、相違があればLineScope文書を優先する。
LogiScopeのコード・構成をそのままコピー・継承しない。再利用する場合は、対象部分と一般化可能と判断した理由を利用者へ説明してから適用する。参照許可だけを実装再開の指示として扱わない。

## 11. 禁止事項

- 要件にない機能追加
- 任意SQL/CypherのLLM公開
- Neo4j/Qdrantの正本化
- Graph非CURRENTの正常利用
- LLMによるApproval/Execute
- 曖昧対象の任意更新
- 文書矛盾の黙認

## 12. 文書レビュー後の実装条件

今回のPO方針は2026-10-09に利用者が推奨案を採用し確定した。将来追加のPO判断待ちが生じた場合はdefaultで有効化せず、業務仕様確定とAPI / DB / AC / Test反映を確認する。レビュー・変更履歴はdocs/history配下へ保存し、仕様正本として扱わない。履歴一覧は[../history/README.md](../history/README.md)を参照する。

## 13. 業務判断支援の追加仕様

PO指示によりUC-BとBusiness Scenarioの意図を既存文書との不整合時に優先する。能力・経済・安全・比較を旧v1に項目がないことだけで対象外にしない。requirements §14.3 PO-B01〜08を推測実装しない。Gherkin・fixture期待値はbusiness-scenarios、試験階層はtest-planを正とする。既存Integration / T-R / Unitを削除しない。未決定・未実装・未実行を合格としない。
