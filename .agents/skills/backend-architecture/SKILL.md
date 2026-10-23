---
name: backend-architecture
description: LineScopeバックエンドのrouter、application service、repository、adapter、PostgreSQL/Neo4j/Qdrantの責務境界や依存方向を変える設計・新component・refactoringをレビューする。配置だけの変更と契約変更を区別する。
---

# LineScope Backend Architecture Review

一般的なPattern名を先に当てはめない。

[文書入口](../../../docs/deliverables.md)、[開発原則](../../../AGENTS.md)、[architecture](../../../docs/design/architecture.md)から変更対象の正本を選ぶ。API/Toolならapi-tools、業務意味ならrequirements/domain-model、原子性ならtransaction-designを読む。

## 実施方法

1. 変更の目的と外部から観測できる差を定める。behavior維持のrefactoringと、契約/状態/権限/DB schemaの変更を区別する。
2. 実コードで入口→Application→Persistence/外部adapterのcall pathを追い、接続・transaction・認可・Evidenceの所有者を示す。設計図を実装の証拠にしない。
3. HTTP handlerにSQL/Core/Sessionや業務ルールが入り込んでいないか確認する。bootstrapの依存組立、readiness診断、既存の意図的例外は個別に説明し、通常handlerへ拡散させない。
4. 純粋な業務検証へHTTP/DB driverを持ち込まない。middleware固有詳細を局所化する。Applicationがtransactionを所有する既存設計を、形式的な依存反転のために隠さない。
5. 正本と実装の差は、仕様不一致・未実装・古い進捗記述を分ける。上位業務意図を下位の都合で縮めず、未定義業務ルールを補完しない。

## 管理されないアドホック実装・テストの禁止

目的は業務機能の完成であり、アドホックの撤廃や全面的な一般解の実現を目的へ置き換えない。例示された入力だけを通す実装や、限界を隠した一般化を禁止する。目的達成に必要な限定規則・暫定対応は、根拠と適用範囲を明示して選ぶ。

- 着手時に目的・制約・完了判定を分け、修正前に元の目的への寄与と未達を確認する。明文化した業務規則・型・文法・標準に基づく有限の規則を、一般解ではないという理由だけで撤去しない。
- 暫定対応には、理由、対象範囲、維持するInvariant、担当、置換・終了条件をコードと作業中の計画／台帳へ記録する。個別の実施経緯はdocs/historyへ置く。恒久的な対応範囲の限定と暫定的な例外を区別する。
- PRごとに暫定対応の採用数と必要性を明示し、台帳を見直す。合意された予算・承認範囲を守る。一律の件数上限を独断で追加せず、範囲や安全性への影響に応じて判断する。
- 別名のような業務知識は確認されたデータとして扱う。設定化は変更頻度・保守責務に応じて選び、外部設定や共通関数へ移しただけで一般化したと判断しない。
- 質問文・設備名への直接分岐、検証例だけを通す特例、事実の生成・認可・書込みの安全を損なう近道は、暫定の名目でも認めない。曖昧・衝突・未取得を一意確定へ変えない。
- 不十分な方式を置き換える際も、元の業務要件と有用な回帰を維持する。同じ意図の別表現・既存正常系・失敗系を元の完了判定で確認し、未解決の失敗を合格へ付け替えない。試験は[test-design](../test-design/SKILL.md)に従う。

## SOLIDを判断に使う

- SRP: HTTP、業務検証、認可、永続化、外部I/Oなど、異なる変更理由を不用意に集約していないか。
- OCP: 新規機能で既存の安全制御を広範に変更しない構造か。未要求のPlugin基盤は作らない。
- LSP: Fake/Stubが本番adapterのerror、timeout、limit、状態と結果の確定性まで契約を守るか。mock成功を実DBの整合性保証にしない。
- ISP: 呼出元のモジュールが不要なwrite/管理能力へ依存せず、目的に合う小さい窓口か。
- DIP: 業務判断がDB/LLM具象詳細へ不必要に依存しないか。差し替え理由のないInterfaceを増やさない。

## 構造変更の扱い

本体と対応Unit Testを責務単位で整理する。Integration/Contract/Business Scenarioは試験目的に配置し、機械的に一対一へ押し込まない。移動だけでClean Architecture完成としない。

先に関連試験のbaselineを確認し、必要なcharacterizationを追加して小さく変更する。SQL表記や内部関数名だけをassertする試験ではなく、外部動作・意味のある境界を確認する。Testを弱めない。Security/責務境界の問題は「3回重複していない」を放置理由にしない。

目的、正本、実経路、依存の差、契約への影響、重要度、検証、残る例外を報告する。重要判断は現在のrepositoryから再開できる場所へ記録し、会話だけに残さない。
