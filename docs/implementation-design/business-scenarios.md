# LineScope Business Scenario受入試験仕様

## 1. 位置付けと共通前提

Use Caseの正本は[use-cases.md](../requirements/use-cases.md)、本書は業務受入試験の正本である。Business Scenario / Acceptance → Agent / Application E2E → Integration → Contract → Unitの階層で検証する。Outbox、lock、Projection retry、Recoveryは既存下位試験に残す。Gherkin形式の採用は実装ライブラリの選定を意味しない。

全ケースは仕様であり未実装・未実行。PO判断待ちを含むケースはBLOCKEDとして追跡し、合格扱いしない。BS-G01の完全な数値fixtureもまだ確定していない。既存の660テスト成功は本書の合格を意味しない。

正常Graph分析はCURRENT、初期化済みgeneration、有効なactive関係、認可済みActorを前提とする。分析観測時刻と評価対象期間は区別する。Graph非CURRENTの拒否、探索上限・未知availability・権限拒否の試験を下位試験で維持し、部分結果の業務上の表示も確認する。

全ケースの重要な結論は、typed object ID、正本値とversion・観測時刻、Tool返却経路、文書citation、計算入力と式、仮定・不確実性へ追跡可能とする。ユーザー報告・仮定と登録済み事実を区別し、分析要求だけでは業務更新を行わない。未知のリスクは未確認と示し、根拠がないことをリスクなしとしない。

OP-30 / OP-40は本書ではProcessの表示コードとして固定する。ProductionOperationを用いるfixtureは別variantとしてEquipment割当を正本とするUSESで検証し、同じ割当をDependencyRelationへ二重登録しない。PRECEDES / PRODUCESのrequiredはfalse（未使用）であり、関係自体が必須である。

## 2. Business Scenario

### BS-01 故障影響範囲

```gherkin
Feature: 故障影響範囲

Scenario: 設備故障の下流影響
  Given Equipment "M-204" と Process "OP-30" / "OP-40" と Product "P-100" / "P-200" がactiveである
  And OP-30 DEPENDS_ON M-204 がrequired=trueである
  And OP-30 PRECEDES OP-40 が有効である
  And OP-40 PRODUCES P-100 および P-200 が有効である
  When 生産管理担当者が「M-204が故障した。どこまで影響する？」と問い合わせる
  Then 直接影響はOP-30であり最短hopは1である
  And 間接影響はOP-40、P-100、P-200であり最短hopは2、3、3である
  And M-204を起点とする順序付き経路とEvidenceを提示する
```

### BS-02 高損失故障への対応比較

```gherkin
Feature: 高損失故障への対応比較

Scenario: 完全停止設備の修理と交換
  Given M-204の正本状態がSTOPPEDである
  And 影響製品P-100の損失は120000 JPY/hour、P-200は80000 JPY/hourである
  And 両損失は独立で加算可能であり修理停止8時間の全期間に適用できる
  And 修理費は300000 JPYであり修理時間は8 hoursである
  And 交換費は3000000 JPYであり調達lead timeは14 daysである
  And 利用可能な代替設備は存在しない
  When 工場管理者が「影響と損失を調べて修理と交換を比較して」と問い合わせる
  Then 損失率は200000 JPY/hourである
  And 修理停止損失は1600000 JPYである
  And 修理費と停止損失の合計は1900000 JPYである
  And 交換のlead time 14 daysを提示する
  And 継続と代替を実行可能案として提示しない
  And 修理と交換を比較可能な形で示し交換の未確定項目を明示する
```

### BS-03 軽微な設備劣化への対応

```gherkin
Feature: 軽微な設備劣化への対応

Scenario: 即時交換と次回更新までの継続
  Given M-204は稼働中で軽微な精度劣化が観測されている
  And 劣化損失は1000 JPY/operating hourである
  And 1日の稼働時間は16 hoursであり次回計画交換まで30 daysである
  And 即時交換の直接費は2400000 JPYである
  And 継続運転は適用される安全基準内であることが確認済みである
  When 工場管理者が「今交換するのと次の更新まで使うのではどう違う？」と問い合わせる
  Then 30日間の劣化損失は480000 JPYである
  And 劣化損失が交換で解消する仮定の単純費用回収期間は150 daysである
  And 480000 JPYと直接交換費2400000 JPYを区別して提示する
  And 定義済みの共通比較条件では継続案の費用が有利であることを示す
  And 確認済みの継続許容条件とEvidenceを示し最終判断は人間に残す
```

### BS-04 安全制約

```gherkin
Feature: 安全制約

Scenario: 低コストでも継続できない
  Given 定義済みの比較条件では継続が最も低コストである
  And M-204は適用されるHard Safety Constraintの停止基準を超えている
  When 工場管理者が「損失が大きいのでこのまま使えない？」と問い合わせる
  Then 継続案を実行可能候補から除外する
  And 除外理由、適用安全基準、Evidenceを提示する
  And 経済利益で安全条件を上書きせず残る候補と判定不能な案を区別する
```

### BS-05 代替設備評価

```gherkin
Feature: 代替設備評価

Scenario: 十分な空き能力
  Given M-204がSTOPPEDであり M-208 CAN_SUBSTITUTE M-204 が有効である
  And 同じ製品・評価期間で必要能力は60 units/hour、M-208の空き能力は80 units/hourである
  And 能力比較の単位と製品互換条件が定義済みである
  When 生産管理担当者が「M-208で吸収できる？」と問い合わせる
  Then 代替候補M-208、必要能力60、空き能力80を提示する
  And 能力面で必要生産量を満たすと評価する
  And 他の成立条件と残存リスクを示し不明な条件を充足済みとしない
```

### BS-06 代替設備評価

```gherkin
Feature: 代替設備評価

Scenario: 候補はあるが能力不足
  Given M-208 CAN_SUBSTITUTE M-204 が有効である
  And 同じ製品・単位・評価期間で必要能力は90 units/hour、空き能力は60 units/hourである
  When 生産管理担当者が「M-208に切り替えれば問題ない？」と問い合わせる
  Then 能力不足30 units/hourを算出する
  And 代替関係だけを理由に問題なしと判断しない
  And 能力不足の影響対象と残存Production riskを根拠とともに提示する
```

### BS-07 長納期設備の交換

```gherkin
Feature: 長納期設備の交換

Scenario: 交換までの暫定対応
  Given M-204は交換候補であり交換部品のlead timeは14 daysである
  And 14日間は交換を開始できない
  And 修理または代替が暫定対応候補として登録されている
  When 工場管理者が「交換したい。部品が来るまでどうなる？」と問い合わせる
  Then 即時交換不能とlead time 14 daysを示す
  And 暫定期間の影響とリスクと候補案を比較可能に示す
  And lead timeを交換作業時間または全期間の完全停止時間と同一視しない
```

### BS-08 連鎖影響評価

```gherkin
Feature: 連鎖影響評価

Scenario: 二次影響とリスク
  Given BS-01と同じ有効な依存構造が存在する
  When 工場管理者が「M-204故障の二次影響まで含めたリスクは？」と問い合わせる
  Then 直接・間接影響と順序付き経路を提示する
  And Production riskとCascade riskを示す
  And QualityまたはDeliveryの根拠があればそのリスクを示す
  And 探索不完全なら完全分析と扱わず未確認のリスクを捏造しない
```

### BS-09 不完全な経済データ

```gherkin
Feature: 不完全な経済データ

Scenario: 一部製品の損失不明
  Given M-204の停止でP-100とP-200が影響を受ける
  And P-100の損失は既知でありP-200の損失は不明である
  When 工場管理者が「1時間あたりの損失はいくら？」と問い合わせる
  Then P-100の判明損失をsubtotalとして示す
  And P-200の損失を捏造または0補完しない
  And subtotalを完全な総損失として提示しない
  And P-200の不足情報と経済評価のincompleteを示す
```

### BS-10 意思決定情報不足

```gherkin
Feature: 意思決定情報不足

Scenario: 修理費不明
  Given 停止損失と交換費は既知であり修理費は不明である
  When 工場管理者が「修理と交換ではどちらが安い？」と問い合わせる
  Then 既知の情報と不足する修理費を提示する
  And 修理費を推測せず経済的な優劣を確定しない
```

### BS-11 不確実性管理

```gherkin
Feature: 不確実性管理

Scenario: 悪化リスクの情報不足
  Given M-204は軽微な劣化状態であり現時点の損失は算出可能である
  And 悪化確率および継続安全性を確定する正本情報が不足している
  When 保全担当者が「次の保全まで使って大丈夫？」と問い合わせる
  Then 現時点の経済影響を提示する
  And 悪化確率を根拠なく数値化せず安全と断定しない
  And リスク情報不足と追加判断に必要なデータを提示する
```

### BS-12 頻発故障設備の対応判断

```gherkin
Feature: 頻発故障設備の対応判断

Scenario: 履歴を含む修理と交換
  Given M-204の複数故障履歴、修理履歴、過去停止損失が正本で確認できる
  And 今回の修理費・修理時間と交換費・交換作業時間が既知である
  When 工場管理者が「また修理するべきか交換を検討するべきか？」と問い合わせる
  Then 故障と修理の履歴、各案の費用と停止影響を提示する
  And 根拠がある範囲の将来リスクと判断不能な予測を区別する
  And 不明な将来故障率を捏造しない
```

### BS-G01 設備異常時の意思決定支援

```gherkin
Feature: 設備異常時の意思決定支援

Scenario: Golden Scenario
  Given 稼働中のM-204に異常が観測され複数工程と製品に影響する
  And 一段代替候補M-208、修理案、交換案、条件付き継続案が存在する
  And 評価期間に必要な生産・費用・保全・安全情報が正本に登録されている
  And 共通の比較期間、単位、費用範囲と各案の入力が確定している
  When 工場管理者が次のように問い合わせる
    """
    M-204に異常が出ている。どこまで影響する？このまま使うリスクは？
    止めたらどれくらい損失する？M-208で代替できる？
    今修理するとどうなる？交換するとどうなる？次の保全まで使った場合は？
    判断材料を比較して示して。
    """
  Then 直接・間接影響、順序付き経路、影響工程と製品を提示する
  And Safety / Production / Quality / Delivery / Cascade / Economic riskを区別して示す
  And 時間当たり損失と評価期間の累積損失を計算する
  And 修理・交換・継続・代替案を評価しHard Safety Constraint違反案を除外する
  And 実行可能案の費用、時間、生産影響、残存リスクを共通条件で比較する
  And Decision PackageにEvidence、入力と式、前提、推定／確定、不足情報を含める
  And 判断不能な事項を断定せず最終意思決定を人間へ残す
  And 分析だけではUpdateRequestを作らずApprovalとExecuteを行わない
```

### BS-13 納期と復旧期限

```gherkin
Feature: 納期と復旧期限

Scenario: 生産bufferから許容停止時間を評価する
  Given 単一製品P-100の利用可能bufferは120 unitsである
  And 評価期間中にbufferから供給する必要量は30 units/hourで一定である
  And このfixtureでは他の供給・引当はなく復旧後は必要量を満たせる
  And 停止開始時刻は2026-10-09T00:00:00Zである
  When 生産管理担当者が「何時間以内に復旧すれば納期への影響を回避できる？」と問い合わせる
  Then 条件付き許容停止時間は4 hoursである
  And 条件付き復旧期限は2026-10-09T04:00:00Zである
  And buffer、必要量、計算式と前提をEvidenceとして提示する
  And このfixtureの単純モデルを全ての生産計画へ一般化しない
```

### BS-14 分析から変更準備

```gherkin
Feature: 分析から変更準備

Scenario: 明示的要求で現在の設備状態変更を準備する
  Given 保全担当者がM-204の分析を確認済みである
  And 現在状態はRUNNINGでversionは10である
  And EquipmentState変更の必要情報と要求権限を満たす
  When 「M-204の現在状態をUNDER_MAINTENANCEに変更する準備を作って」と明示的に要求する
  Then 単一EQUIPMENT_STATEカテゴリのUpdateRequestとPENDING Approvalを作成する
  And canonical SnapshotのbeforeはRUNNING version 10、afterはUNDER_MAINTENANCE version 11である
  And 要求ID、承認ID、hash、変更前後とHuman Approval待ちを提示する
  And Prepareだけでは業務状態を変更せずAgentはApproveもExecuteもしない
```

### BS-15 安全情報不足

```gherkin
Feature: 安全情報不足

Scenario: 低費用でも継続許容を断定しない
  Given 継続案の経済評価が既知であり他案より低費用である
  And 適用安全基準または判定に必要な入力が不足している
  When 工場管理者が「安いなら次回保全まで続けられる？」と問い合わせる
  Then 安全上の許容を確認済みとせず実行可能性の判定不足を示す
  And 安全、不適合、未確認を混同しない
  And 必要な安全入力とEvidence不足を示す
  And 低費用を安全許容の代わりに使わない
```

### BS-16 損失の重複防止

```gherkin
Feature: 損失の重複防止

Scenario: 加算条件が成立しない場合に完全合計を作らない
  Given P-100とP-200が同じ停止により影響を受ける
  And 個別に表示する損失率は120000と80000 JPY/hourである
  And 両損失に共有費用が含まれ独立加算可能とは確認されていない
  When 工場管理者が「合計で1時間いくら失う？」と問い合わせる
  Then 200000 JPY/hourを確定した完全合計として提示しない
  And 個別の既知値と加算できない理由を提示する
  And 重複費用の内訳と加算ルールを不足情報として示す
```

### BS-17 曖昧対象の調査

```gherkin
Feature: 曖昧対象の調査

Scenario: 識別後に分析を続ける
  Given 同じequipment_nameを持つactive Equipmentが2件存在しequipment_codeは異なる
  When 保全担当者が名称だけで故障影響を問い合わせる
  Then 候補を提示して識別情報を求め任意の設備で確定分析しない
  When 同じ所有者の有効なcontext_idで一方のequipment_codeを指定する
  Then 指定設備の存在と権限を正本で再検証して分析する
  And 他方の経路とEvidenceを混ぜずPrepareしない
```

### BS-18 分析不能と影響なしの区別

```gherkin
Feature: 分析不能と影響なしの区別

Scenario Outline: 確認状態に応じて結論を分ける
  Given 対象M-204は特定済みでありGraph状態は<graph_state>である
  And 探索条件は<search_condition>である
  When 認可された利用者が影響分析を要求する
  Then 結論は<expected_result>である
  And 探索不完全またはGraph非CURRENTなら影響なしと断定しない
  And 利用可能な通常Read情報を最新Graph結論と混同しない

  Examples:
    | graph_state | search_condition | expected_result |
    | CURRENT | 定義済み範囲を完全探索し下流対象なし | 条件付き影響対象なしとEvidence |
    | CURRENT | 探索上限到達で未探索範囲あり | complete=falseとlimit_reason |
    | LAGGING | 探索を開始しない | 最新Graph分析不能 |
    | ERROR | 探索を開始しない | 最新Graph分析不能 |
    | REBUILDING | 探索を開始しない | 最新Graph分析不能 |
```

### BS-19 人間の変更後確認

```gherkin
Feature: 人間の変更後確認

Scenario: 確定結果と後続の現在値を区別する
  Given 保全担当者がUC-B14でEquipmentState変更をPrepareした
  And 別の認証済み有権限承認者が同じcanonical Snapshot hashをApproval APIで承認した
  And 元requesterが有効期限内にExecute APIでRUNNING version 10からUNDER_MAINTENANCE version 11へ確定した
  And 後続の別の正当な更新で現在状態がRUNNING version 12になった
  When 元requesterが最初のUpdateRequestの結果と現在状態を確認する
  Then 保存された確定afterはUNDER_MAINTENANCE version 11のままである
  And 現在値RUNNING version 12とversion差を区別して返す
  And 同じExecuteの再送で業務更新を重複実行しない
  And Agentは人間に代わってApprovalまたはExecuteしない
```

## 3. 固定数値・比較条件

| Scenario | 式 | 期待値 | 解釈・未確定条件 |
|---|---|---|---|
| BS-02 | 120000 + 80000 | 200000 JPY/hour | 独立加算可能な損失率 |
| BS-02 | 200000 × 8 | 1600000 JPY | 同じ損失率が修理停止8時間全体へ適用可能 |
| BS-02 | 1600000 + 300000 | 1900000 JPY | 修理の直接費と停止損失の合計。全費用を含むTCOとは断定しない |
| BS-03 | 1000 × 16 × 30 | 480000 JPY | 日別の劣化損失が一定というfixture |
| BS-03 | 2400000 ÷ (1000 × 16) | 150 days | 交換が劣化損失を解消する仮定の単純費用回収期間。元案の「損益分岐」の数値を保持する |
| BS-06 | 90 − 60 | 30 units/hour | 同一製品・単位・期間の能力不足 |
| BS-13 | 120 ÷ 30 | 4 hours | fixture限定のbuffer消費モデル。PO-B03で業務適用条件を確定 |
| BS-13 | 2026-10-09T00:00:00Z + 4 hours | 2026-10-09T04:00:00Z | 上記の条件付き復旧期限 |

BS-03で継続案が費用上有利という受入意図は保持する。共通比較期間、30日後の交換費の扱い、交換停止損失等が未確定なので、その優劣assertionはPO-B01確定までBLOCKED。150日を厳密な両案の損益分岐と断定しない。BS-02 / 07の14 daysは調達lead timeであり、14×24時間の完全停止損失を自動計算しない。BS-03の16 hours/dayを他ケースへ流用しない。

BS-05は能力面の吸収可否を検証する。業務上の完全代替には一段置換の全AND依存、稼働状態、製品互換性、安全・品質条件、評価期間等の充足も必要。未知の残存リスクはunknownsへ記載する。BS-G01の数値・各案の実行可能性・リスク根拠はPO-B01〜07後に専用fixtureで固定し、BS-02 / 03を無条件に混ぜない。

## 4. UC ↔ Scenario ↔ ACと成立状況

「現仕様で成立」は仕様上の範囲を指し、実装合格ではない。既存ACは既存の部分のみを保証し、追加のAC-Bを代替しない。

| BS | UC | AC | 現仕様で成立する部分 / 必要な拡張・PO |
|---|---|---|---|
| BS-01 | UC-B01・15、UC-04・16 | AC-B01・11、AC-G01〜03・10・11 | 影響・経路は成立。正常fixtureの明示で検証可能 |
| BS-02 | UC-B01・05〜07・09・13・15 | AC-B01・04・05・09・11 | 構造影響以外は費用・時間・比較の追加が必要。PO-B01・02・05・07 |
| BS-03 | UC-B05・07〜09・15 | AC-B03〜07・11 | 劣化・交換計画・安全・比較の追加。PO-B01・02・04・05・07 |
| BS-04 | UC-B04・09・10・15 | AC-B03・05・06・11 | 安全基準・判定入力の追加。PO-B04・07 |
| BS-05 | UC-B02・03・09・15、UC-19 | AC-B02・03・11、AC-G05 | 構造候補は成立。能力・互換性・残存リスクの追加。PO-B03・04・07 |
| BS-06 | UC-B02・03・13・15、UC-19 | AC-B02・09・11、AC-G05 | 構造候補は成立。能力不足と製品影響の追加。PO-B03・07 |
| BS-07 | UC-B07・09・13・15 | AC-B05・07・09・11 | 調達・暫定期間・比較の追加。PO-B01・05・07 |
| BS-08 | UC-B01・04・15、UC-16 | AC-B01・03・09・11、AC-G01〜03・08・10 | 経路と探索不完全性は成立。リスク判定の追加。PO-B04・07 |
| BS-09 | UC-B05・13・15 | AC-B04・09・11、AC-04 | 不捏造は既存方針と整合。損失入力・subtotal契約の追加。PO-B02・07 |
| BS-10 | UC-B06・07・09・13 | AC-B05・09、AC-04 | 不捏造は整合。費用と比較契約の追加。PO-B01・05・07 |
| BS-11 | UC-B04・08・13・15 | AC-B03・06・09・11、AC-04 | 不捏造は整合。劣化・安全・経済入力の追加。PO-B02・04・07 |
| BS-12 | UC-B06・07・12・13・15、UC-02・03 | AC-B05・08・09・11、AC-04 | 保全履歴は存在。故障原因・費用・過去損失等の追加。PO-B01・05〜07 |
| BS-G01 | UC-B01〜10・12・13・15 | AC-B01〜11、AC-01・02・04・06、AC-G01〜03・05・08・10・11 | 新機能統合と専用fixtureが必要。PO-B01〜07 |
| BS-13 | UC-B11・13・15 | AC-B07・09・11 | buffer・需要・納期規則の追加。PO-B03・07 |
| BS-14 | UC-B14、UC-05 | AC-B10・11、AC-02〜09・13・16 | 現在状態Prepareは既存仕様で成立。将来停止を予約するvariantはPO-B05待ち |
| BS-15 | UC-B04・08・10・13・15 | AC-B03・06・09・11 | 安全入力の追加。PO-B04・07。未確認を許容済みとしない |
| BS-16 | UC-B05・13・15 | AC-B04・09・11 | 加算条件と損失入力の追加。PO-B02・07 |
| BS-17 | UC-B16、UC-01・11 | AC-03・04、AC-B01・11 | 対象確認・context再検証は既存仕様で成立 |
| BS-18 | UC-B01・13・15 | AC-B01・09・11、AC-G08〜11 | 探索完全性・非CURRENT拒否は既存仕様で成立 |
| BS-19 | UC-B14・17、UC-05・10・15 | AC-B10・11、AC-06〜10・12・15 | Approval / Execute・確定後確認は既存仕様で成立 |

### 4.1 元案を補うケースと残る不足

元案の13ケースを保持し、BS-13〜19を追加した。納期・復旧期限、明示的Prepare、安全不明、損失加算不可、曖昧対象、影響なしと分析不能、人間の更新後確認を補う。BS-13の計算fixtureは単純モデルの前提を固定した試験入力であり、一般業務ルールの確定ではない。UC-B14の将来停止予約variantはPO-B05確定後に追加する。非CURRENT、打切り、過去as_of、権限拒否は既存下位試験と連携して検証する。

## 5. 実装時の検証原則

LLMに数値計算を任せず、固定正本fixtureと決定論的計算処理を使う。主要assertionはaffected objects、pathsとhop、numeric resultsと単位・期間、feasible / excluded / 判定不能なoptions、risk dimensions、Evidence、unknowns、各評価のcompletenessとする。LLM自然言語の完全一致を主判定にしない。

計算のUnit / Contract、正本取得と認可のIntegration、AgentのTool選択と説明のE2E / Evals、最上位の業務受入を分ける。mockの成功だけで実LLMの説明品質や実DBの整合性を合格にしない。既存Integration / T-R / Unit / Recoveryは削除しない。

## 6. デモとの関係

LogiScopeの動画シナリオ等は「業務の問いから調査・根拠・判断へつながる」雰囲気だけを参考にした。本書の追加ケースと期待結果はLineScopeの要件・不足レビューから導いたものであり、物流モデル、Tool、更新経路、データ、コードを継承していない。動画台本は後続で実装済み・検証済みケースを選んで構成し、本書の受入仕様と区別する。
