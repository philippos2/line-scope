---
name: test-design
description: >
  複数の入力軸、pytest parametrize、多重parametrize、組み合わせテスト、
  pairwise / all-pairs、境界値、状態遷移、Transaction、Concurrencyに関する
  テストを設計・追加・レビューするときに使用する。
---

# Test design

## 目的と正本

追加前に入力空間とリスクを整理し、必要な検証を維持しながら、無計画な直積、重複、CI負荷増大を防ぐ。

事前レビュー・了承条件は[root AGENTS.md](../../../AGENTS.md)を正とする。試験階層・AC・既存試験の扱いは[test-plan §1.1〜1.2](../../../docs/implementation-design/test-plan.md)、業務受入は[business-scenarios](../../../docs/implementation-design/business-scenarios.md)を参照する。実行と引渡しは対象領域のverification Skillに従う。

このSkillは作業手順であり、実測・失敗・運用経験を根拠に改善できる。ケース数だけを品質の代理指標にせず、業務仕様、重大Invariant、AGENTSの了承条件を手順の都合で変更しない。

## Workflow

### 1. 入力軸と重複を確認する

対象UC / AC、検証するInvariant、入力領域、Failure Modeを特定する。既存テストが同じリスクを実質的に検証していないか確認する。別のTest Layerで配線・認可・DB制約等の異なるFailure Modeを検証する場合は、単純な重複と扱わない。

Role、State、Operation、Input Type、Resource State、Version、Permission等の因子・水準と、有効な組合せの制約を整理する。複雑な場合は境界値と既知の重要な相互作用も明示する。

### 2. 展開件数と実行負荷を見積もる

全直積件数、採用予定件数、選定方針を実装前に示す。小規模なら一行でよい。

```text
Role(3) × State(4) × Operation(3) = 全直積36件 /
採用8件 / 境界値＋代表値＋必要な相互作用
```

`parametrize`は関数数ではなく展開後のケース数で数える。3×4×5なら1関数でも60件。同じ目的の変更全体で集計し、PRやコミットに分けて確認を回避しない。補助pytest subprocess、繰返し実行、重いDB / Graph準備がある場合は、その実行負荷も別途示す。

AGENTSの基準を超えそうな場合は実装前に停止し、想定件数、超える理由、全直積と採用予定件数、削減可能性、設計手法を報告する。開発者の了承を得るまで、その追加を実装しない。暫定基準の見直しは根拠と変更案を示し、Skillだけで条件を解除しない。

### 3. 必要十分なケースを選ぶ

既定は代表値・同値クラスと境界値。省略、NULL、空、0、UNKNOWN等は意味が異なるなら別クラスとする。無効入力は原則として他の入力を正常に固定し、どの拒否規則を検証するか明確にする。

複数の独立した入力軸で二因子間の組合せを広く確認する必要がある場合は、無条件の直積よりpairwise / all-pairsを優先する。PICT、allpairspy等は必要なら使用できるが、先に因子・水準・制約・リスクを定義する。生成ツールの利用自体を設計完了とせず、有効な二因子組の被覆を確認する。

### 4. 高リスクの相互作用を専用に検証する

Authorization×Operation、Approval State×Execute、Version Conflict×Update、Lock×Concurrent Update等の既知の重要条件は、pairwiseで偶然含まれることに依存しない。意図を明示した専用テストを用意する。

三因子以上の相互作用、状態遷移、Transaction境界、Concurrency、Retry、Idempotency、Rollback、時系列依存、Securityの重大Invariantは、単純なpairwiseだけで十分と扱わない。

小さな状態空間や重大Invariantで全組み合わせが合理的な場合は、必要な理由、全件数、削減できない理由を事前提示し、AGENTSに従って了承を得る。必要なケースを省くためにpairwiseを使わない。

### 5. 実装後に件数・保証範囲・時間を確認する

pytest collection等で実際の展開数を確認し、見積もりとの差、suiteへの影響、CI時間増加を報告する。大きく乖離したら理由と改善案を示す。

変更前後でAC・assertion・境界・Failure Modeの対応を確認する。setup / call / teardownを計測し、fixture共有や並列化は状態隔離と片付けを保証できる範囲で行う。テスト削除・skip・assertion弱体化でGreenにしない。

## 原則

テスト件数を増やすことも減らすことも目的にしない。必要なリスクを、必要十分なケースで検証する。実際に役立った手順と失敗からSkillを更新し、根拠なく規則やchecklistを増やさない。
