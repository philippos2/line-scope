# 開発Skill草案

Phase 1Aで作成した草案の履歴入口。Phase 1Cで正式配置へ移した。過去の草案本文はGit履歴に残り、以下は現在の正式Skillへの参照。根拠と不足は[調査報告](../2026-10-11-engineering-guidance-phase-1a.md)を参照する。

- [backend-architecture](../../../.agents/skills/backend-architecture/SKILL.md): 責務、依存、実call path、設計変更とrefactoring。
- [backend-secure-coding](../../../.agents/skills/backend-secure-coding/SKILL.md): identity、認可、DBアクセス、LLM/RAG入力、秘匿。
- [backend-transaction-review](../../../.agents/skills/backend-transaction-review/SKILL.md): 更新原子性、lock/version、再試行、Outbox/Projection/Rebuild。
- [backend-verification](../../../.agents/skills/backend-verification/SKILL.md): 検証選択、結果と不足、commit/PR/CI引渡し。

仕様・状態一覧・数値を複製せず、正本の参照と照合方法を記述する。

採用判断・検証とguardrailの残件は[Phase 1C記録](../2026-10-11-engineering-guidance-phase-1c.md)を参照する。
