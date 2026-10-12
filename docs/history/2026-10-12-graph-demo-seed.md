# 通常依存Graphのデモ初期投入

seed-demo-graphに9 node / 10 aggregateの固定fixtureを用意した。M-204 → OP-30 → OP-40 → P-100 / P-200、Process経路、R-02上流、M-208代替候補を含める。能力・経済・安全等の未定義業務データは追加しない。operations §18が初期投入手順の正本。

新規追加は初回Rebuild前に限定する。公開済みgenerationへ新nodeをseed追加すると、旧世代でのOutbox drainに影響し得るため、全rollbackする。再実行で追加が不要ならCURRENTを保持する。既存値を戻さず、他の関係・編集済み関係へfixtureを混ぜない。

既存seedのtransaction内処理を分離し、新しいGraph seedと設備投入を同じtransactionで処理する。通常SQLは固定Core queryとbindへ統一した。mutation排他・control lock・要Rebuild保存を同じtransactionで確定し、更新要求・監査・Outboxを捏造しない。

実PostgreSQL / Neo4jと決定論的LLMで、初期投入 → Rebuild → HTTP下流・上流分析、経路・Evidence・state version、代替除外、seed再実行・競合rollback・公開後追加拒否を確認する。追加試験のimport不足を修正した。実LLMのGraph選択品質、能力・費用・安全・代替判定は後続。LogiScopeコードは再利用していない。

USESの実経路を含む試験でrequired=NULLを検出した。domain-model §7の有効割当による必須利用を読取Evidenceへtrueとして派生し、保存済みProjection属性・payload / hash・同version再適用を変更しない。PRECEDES等のrequired未使用種別をoptionalと解釈しない。
