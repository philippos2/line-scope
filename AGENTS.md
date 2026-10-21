# LineScope 開発ガイダンス

## 入口と正本

最初に[文書入口](docs/deliverables.md)を読む。対象事項の正本をdeliverablesの責務表で選び、関連箇所を確認する。履歴・README・Skillsを業務仕様の正本として扱わない。

このファイルはRepository全体に適用する開発原則とSkillの入口。分野ごとの作業・レビュー・検証手順は対応するSKILL.md、業務仕様・設計契約は各正本文書に維持する。不一致は黙って統一せず、根拠と変更案を示す。

開発ガイダンスで「開発者」はこのRepositoryの開発依頼者を指す。「PO」は業務仕様を判断するプロダクトオーナーを指す。現在は同じ人物だが、役割を区別する。「エンドユーザー」はLineScopeを業務で操作する人、「呼出元のモジュール」はインターフェースを呼び出すコードを指す。指示・仕様判断・PR mergeの主体と、システム内の業務権限を混同しない。

## 維持する原則

- 履歴はdocs/historyの履歴ドキュメントへ記録する。AGENTS.md、SKILL.md、CONTRIBUTING.mdには、継続して適用する原則・手順・規則だけを書く。個別案件の作業経緯、日付付きの実施記録、一時的な許可・例外とその終了を記載しない。
- 開発者の指示は、言葉の表面だけでなく、それまでの文脈・実現したい目的・実行時期・制約を合わせて理解する。後の指示で、先の条件が暗黙に解除されたと判断しない。意図を確定できない場合は、行動前に質問し、回答を待つ。
- 行動前に、影響範囲・可逆性・失敗時に残る状態を把握する。特に取り返しのつかない操作は、影響が不明なまま実行しない。
- 承認は、その目的・対象・操作・範囲に限って適用する。失敗や拒否が起きても、独断で別の操作へ切り替えたり、承認範囲を広げたりしない。追加の行動が必要なら、現在の状態と影響を示して承認を得る。
- 責務と境界を分離し、依存方向を予測可能にする。Infrastructure固有の詳細を局所化し、HTTP handlerへSQL/Core/Sessionや業務判断を追加しない。依存組立とreadiness診断は業務handlerと区別する。
- SOLID、凝集度・結合度、明示性を設計判断に使う。具体的な変更負担・リスクを減らす抽象化とrefactoringを選び、形式だけのInterfaceや先回りの基盤を増やさない。
- Security、データ整合性、transactionの正しさを利便性より優先する。認証・認可・確定操作をLLMへ委ねず、決定論的な規則はコードで検証する。AgentにApproval / Executeや任意SQL / Cypherを公開しない。
- 通常DB操作はSQLAlchemy Coreを第一選択とし、動的値をbindする。Raw SQLは合理的な例外として扱い、識別子のallow-list、transaction所有権、副作用を追跡可能にする。
- 外部契約、認可、lock順、version、Snapshot、Audit/Outbox原子性をrefactoringで意図せず変更しない。Testの削除・弱体化で成功扱いにしない。
- 未定義業務ルールとPO判断事項を推測で確定しない。未実装・未検証・既存例外を明示し、重要な決定は現在のRepositoryから再開できる場所へ記録する。

## 完走と段階的改善の開発原則

- 着手時に「目的（利用者が達成したいこと）」「制約・留意事項」「完了判定」を分け、作業中の正本文書または計画へ固定する。追加の指摘は原則として制約・受入条件への追加として扱い、明示指示なく目的を置き換えない。
- 修正前に、その変更が元の目的へどう寄与し、何をまだ満たさないかを確認する。局所的な条件・内部部品・試験件数の成功を、業務目的の達成へ読み替えない。
- 完了報告前に、変更した例だけでなく、同じ意図の別表現・既存の正常系・失敗系を元の完了判定で見直す。例への一致や制約順守だけで全体を完了扱いしない。試験対象の絞り込みと、受入条件の縮小を区別する。
- 同種の指摘が再発したら局所修正の追加を先にせず、目的・現在の実装・検証基準のずれを整理する。改善手順を記録するだけで再発防止済みとはせず、その案件への適用と結果まで確認する。
- 可能な限り最後まで完走させることを優先し、リファクタリングは必要性と効果を見極めて段階的に行う。全面的な設計整理を機能完成の前提にしない。
- アジャイルを意識し、利用可能な業務機能を実装・検証し、得られた結果と開発者のフィードバックから次の優先順位を更新する。
- 業務シナリオに沿って利用できる機能の完成を優先する。小さなPRや内部部品の完成を進捗の基準にしない。
- 完了は正本文書で定義された業務受入基準に照らして判断する。未決定・未実装・未検証を明示し、必要な機能を黙って対象外にしたり、安全性や必要な検証を犠牲にしたりして完了扱いにしない。

## 他Repositoryの参照

LogiScopeは一般化可能な実装パターンの参考として参照してよい。LineScopeの要件・仕様・設計は文書入口が示す正本を優先し、コード・構成をそのまま継承しない。再利用する場合は対象部分と理由を開発者へ説明し、参照許可を実装着手の指示に転用しない。

## 作業に応じて使うSkills

### Test design

- 複数の入力軸を持つテストを追加する場合は、実装前に展開後のケース数と選定方針を見積もる。全組み合わせの直積を無条件に生成しない。
- 同じ目的の変更で追加・展開されるケースが20件を超えそうな場合は、実装前に想定件数、必要な理由、削減可能性を報告し、開発者の了承を得る。関数数ではなく`parametrize`等の展開後のケース数で数え、PRやコミットの分割でこの確認を回避しない。
- 20件は暫定の事前レビュー基準であり、品質上の上限ではない。実測負荷と運用経験から必要なら見直し、根拠と更新後の基準を明記する。件数合わせのために必要な検証を削らない。
- Security、Authorization、Transaction等の重大Invariantについて全組み合わせ検証が必要な場合も、実装前に理由と想定件数を提示し、開発者の了承を得る。
- 複数入力軸、`parametrize`の多重化、組み合わせテストでは[test-design](.agents/skills/test-design/SKILL.md)を使用する。Skillは入力空間・重複・リスク・実行負荷に応じて手順を改善する場所であり、上記原則や了承条件を暗黙に変更しない。

変更の意味で選び、該当するSkillを読んで適用する。複数該当する場合は必要なものを組み合わせる。軽微な文言修正で全Skillを読む必要はない。

| 対象 | Skill |
|---|---|
| 複数入力軸、parametrize、組み合わせ、境界値、状態遷移、Transaction / Concurrencyのテスト設計 | [test-design](.agents/skills/test-design/SKILL.md) |
| router / service / repository / adapterの責務、依存方向、新component、構造変更、refactoring | [backend-architecture](.agents/skills/backend-architecture/SKILL.md) |
| 認証・認可、Trusted Execution Context、Tool入力、SQL/Cypher、LLM/RAG、secret、DB role、外部エラー | [backend-secure-coding](.agents/skills/backend-secure-coding/SKILL.md) |
| UpdateRequest / Approval / Execute、Snapshot / version、retry / lock、Outbox / Projection / Rebuild / Restore | [backend-transaction-review](.agents/skills/backend-transaction-review/SKILL.md) |
| React component、表示モデル、HTTP client、Graph / Evidence / Actionの境界 | [frontend-architecture](.agents/skills/frontend-architecture/SKILL.md) |
| Frontendの必要最小限の検証、実ブラウザ、CI引渡し | [frontend-verification](.agents/skills/frontend-verification/SKILL.md) |
| 変更の検証、pytest / ruff / migration、checkpoint commit、PR / CI引渡し | [backend-verification](.agents/skills/backend-verification/SKILL.md) |

領域固有のSkill名は`backend-` / `frontend-`等の接頭辞で対象を区別する。領域共通のテスト設計は`test-design`を使う。未使用の空Skillは先に作らない。

## 作業と引渡し

GitHubへpush済みの既存履歴を書き換えず、main・作業ブランチともforce-pushしない。

backendのテスト・lintはDocker内で行う。作業の区切りとPR運用は[CONTRIBUTING.md](CONTRIBUTING.md)、検証・引渡しの手順は[backend-verification](.agents/skills/backend-verification/SKILL.md)に従う。
