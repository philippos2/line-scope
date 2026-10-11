# 開発Skill草案

Phase 1Aの成果物。正式採用・自動発動の対象ではない。根拠と不足は[調査報告](../2026-10-11-engineering-guidance-phase-1a.md)を参照する。

- [linescope-architecture-review](skills/linescope-architecture-review/SKILL.md): 責務、依存、実call path、設計変更とrefactoring。
- [linescope-secure-coding](skills/linescope-secure-coding/SKILL.md): identity、認可、DBアクセス、LLM/RAG入力、秘匿。
- [linescope-transaction-review](skills/linescope-transaction-review/SKILL.md): 更新原子性、lock/version、再試行、Outbox/Projection/Rebuild。
- [linescope-code-change-verification](skills/linescope-code-change-verification/SKILL.md): 検証選択、結果と不足、commit/PR/CI引渡し。

仕様・状態一覧・数値を複製せず、正本の参照と照合方法を記述する。Phase 1B/C後に採用範囲とAGENTSの短い発動条件を確定する。

正式配置候補は`.agents/skills/<name>/SKILL.md`。現在の相対リンクは草案配置用であり、正式配置時に変更・再検証する。草案のstatus表示も正式採用時に更新する。Root AGENTS入口は未変更。
