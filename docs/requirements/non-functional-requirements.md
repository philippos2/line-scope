# LineScope 非機能要件定義書

## 1. 基本

安全性・整合性・認可を性能より優先する。

## 2. NFR

### NFR-01 Fail Closed
安全性を確認できない更新は実行しない。

### NFR-02 決定性
同一確定データ・同一条件では、Graphの到達集合・最短距離・代表経路選択が決定的である。

### NFR-03 Trusted Identity
認可・承認・実行主体は認証済みContextに基づく。

### NFR-04 最小権限
LLMを権限主体にしない。

### NFR-05 原子性
一UpdateRequestの複数変更を部分確定しない。

### NFR-06 監査性
要求、承認、実行、変更前後、結果、Outbox反映を追跡可能とする。

### NFR-07 回復可能性
Neo4jとQdrantは正本から再構築可能とする。

### NFR-08 Prompt非依存
認証、認可、承認、Transaction、Graph同期をPromptだけに依存しない。

### NFR-G01 可変長探索
多段探索可能。

### NFR-G02 資源上限
深度、到達ノード数、返却経路数、処理時間にhard limitを持つ。

### NFR-G03 循環耐性
許容循環でも無限探索しない。

### NFR-G04 Grounding
存在しないGraph根拠を構造化Evidenceへ追加しない。

### NFR-G05 代表経路
到達対象ごとに決定的な代表経路を取得できる。

### NFR-G06 不完全性
探索打切り理由を機械可読に返す。

### NFR-G07 同期判定
GraphのCURRENT / LAGGING / ERROR / REBUILDINGを決定論的に判定できる。

### NFR-G08 順不同耐性
Outboxの採番順とcommit順が一致しなくてもイベントを取りこぼさない。

### NFR-G09 Projection冪等性
同一イベント再適用で結果が壊れない。

## 3. 性能方針

具体閾値は設定値とする。Graph Toolはhard limitなしで実行しない。

## 4. セキュリティ

- Prompt Injectionでroleを変更しない
- 任意SQL/CypherをLLMへ許可しない
- 秘密情報を出力しない
- v1は単一工場でGraphノード単位秘匿は対象外

## 5. 整合性・監査の具体化

Graph最新性はEvidenceの観測時点・generationで保証し、構造と状態値の観測時刻を区別する。同期情報の読込失敗もfail closed。

監査は成功履歴に加え承認拒否・失効・実行失敗・Outbox試行を追跡する。技術閾値はoperationsの設定契約に従い、無限待機・無限retryを禁止する。今後未決定の業務事項が生じても技術的defaultで補完しない。
