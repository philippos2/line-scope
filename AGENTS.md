# LineScope 開発ガイダンス

## 入口と正本

最初に[文書入口](docs/deliverables.md)と[実装支援規則](docs/implementation-design/AGENTS.md)を読む。対象事項の正本をdeliverablesの責務表で選び、関連箇所を確認する。履歴・README・Skillsを業務仕様の正本として扱わない。

このファイルはRepository全体に適用する開発原則とSkillの入口。詳細な作業規則の正本は既存の実装支援規則、システム仕様は各正本文書に維持する。不一致は黙って統一せず、根拠と変更案を示す。

開発ガイダンスで「開発者」はこのRepositoryの開発依頼者を指す。「PO」は業務仕様を判断するプロダクトオーナーを指す。現在は同じ人物だが、役割を区別する。「エンドユーザー」はLineScopeを業務で操作する人、「呼出元のモジュール」はインターフェースを呼び出すコードを指す。指示・仕様判断・PR mergeの主体と、システム内の業務権限を混同しない。

## 維持する原則

- 責務と境界を分離し、依存方向を予測可能にする。Infrastructure固有の詳細を局所化し、HTTP handlerへSQL/Core/Sessionや業務判断を追加しない。依存組立とreadiness診断は業務handlerと区別する。
- SOLID、凝集度・結合度、明示性を設計判断に使う。具体的な変更負担・リスクを減らす抽象化とrefactoringを選び、形式だけのInterfaceや先回りの基盤を増やさない。
- Security、データ整合性、transactionの正しさを利便性より優先する。認証・認可・確定操作をLLMへ委ねず、決定論的な規則はコードで検証する。
- 通常DB操作はSQLAlchemy Coreを第一選択とし、動的値をbindする。Raw SQLは合理的な例外として扱い、識別子のallow-list、transaction所有権、副作用を追跡可能にする。
- 外部契約、認可、lock順、version、Snapshot、Audit/Outbox原子性をrefactoringで意図せず変更しない。Testの削除・弱体化で成功扱いにしない。
- 未定義業務ルールとPO判断事項を推測で確定しない。未実装・未検証・既存例外を明示し、重要な決定は現在のRepositoryから再開できる場所へ記録する。

## 作業に応じて使うSkills

変更の意味で選び、該当するSkillを読んで適用する。複数該当する場合は必要なものを組み合わせる。軽微な文言修正で全Skillを読む必要はない。

| 対象 | Skill |
|---|---|
| router / service / repository / adapterの責務、依存方向、新component、構造変更、refactoring | [backend-architecture](.agents/skills/backend-architecture/SKILL.md) |
| 認証・認可、Trusted Execution Context、Tool入力、SQL/Cypher、LLM/RAG、secret、DB role、外部エラー | [backend-secure-coding](.agents/skills/backend-secure-coding/SKILL.md) |
| UpdateRequest / Approval / Execute、Snapshot / version、retry / lock、Outbox / Projection / Rebuild / Restore | [backend-transaction-review](.agents/skills/backend-transaction-review/SKILL.md) |
| 変更の検証、pytest / ruff / migration、checkpoint commit、PR / CI引渡し | [backend-verification](.agents/skills/backend-verification/SKILL.md) |

Skill名は対象領域の接頭辞で区別する。現在は`backend-`を使い、Frontend着手時に必要な`frontend-architecture`、`ui-component-design`、`frontend-data-access`、`accessibility-review`、`frontend-verification`等を追加する。未使用の空Skillは先に作らない。

## 作業と引渡し

PRタイトルとコミットメッセージは必ず日本語で作成する。Conventional Commitの接頭辞とAPI名等の正式表記は維持し、説明・本文は日本語にする。Squash commitにも適用する。

GitHubへpush済みの既存履歴を書き換えず、main・作業ブランチともforce-pushしない。2026-10-12の日本語化・PR復旧に対する例外許可は終了しており、今後の操作へ適用しない。

backendのテスト・lintはDocker内で行う。機能ごとに小さく実装→検証→commitし、PRのmergeは開発者が行う。mainの履歴はSquash mergeを標準とし、rewrite / force-pushしない。必須CI、実測結果の追記、使い捨てtest環境の片付けまで確認してからmerge可能と伝える。詳細とコマンドは検証Skillを使う。
