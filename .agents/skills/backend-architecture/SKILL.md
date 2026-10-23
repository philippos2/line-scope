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

## アドホック実装・テストの禁止

ユーザーが挙げた例は、要件や失敗を説明する例として扱う。その入力だけを通すことを目的にしない。**共通の要件・仕様から導けない、特定の質問文・設備・コード・語句・値に依存した例外分岐や置換の追加を禁止する。** 同じ特例を共通関数へ移しただけでは一般化にならない。

- 実装前に、解決する問題の種類、適用範囲、維持するInvariant、曖昧・衝突・未取得の場合の扱いを明示する。例の文字列を替えても同じ原理で動くか、近い別概念を誤って取り込まないかを確認する。
- 明文化された業務規則・型・文法・標準に基づく有限の規則は、その根拠と範囲で判断する。正規表現や辞書の使用自体をアドホックと断定せず、観測した例を通すためだけに規則を増やしていないかをレビューする。
- 不十分な特例を置き換える際も、元の業務要件と既存の有用な回帰ケースを維持する。削除だけで完了とせず、一般的な方式への置換と退行の確認まで扱う。
- 試験は[test-design](../test-design/SKILL.md)に従い、仕様から期待結果を決め、失敗の種類・同値クラス・境界を検査する。例題の成功だけを受入根拠にしない。

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
