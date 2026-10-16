# LineScope Business Scenario受入試験仕様

## 1. 位置付けと共通前提

Use Caseの正本は[use-cases.md](../requirements/use-cases.md)、本書は業務受入試験の正本である。Business Scenario / Acceptance → Agent / Application E2E → Integration → Contract → Unitの階層で検証する。Outbox、lock、Projection retry、Recoveryは既存下位試験に残す。Gherkin形式の採用は実装ライブラリの選定を意味しない。

各ケースは受入仕様であり、実装・実行状況は§7で保証範囲を区別する。PO判断待ちを含むケースはBLOCKEDとして追跡し、合格扱いしない。BS-G01の固定数値・登録仮定・仕様上の不明は末尾の正式入力fixtureで定義する。下位テストの総件数を本書全体の合格根拠にしない。

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
  And インフラ資源がM-204へSUPPLIESする場合、その資源を上流依存として経路・Evidenceとともに提示する
  And その資源をM-204停止の下流被影響対象とは表示しない
  And 上流探索が不完全なら依存インフラなしと断定しない
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
  And 確認済みの継続許容条件とEvidenceを示し最終判断はエンドユーザーに残す
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
  And 判断不能な事項を断定せず最終意思決定をエンドユーザーへ残す
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

### BS-19 承認・実行後の確認

```gherkin
Feature: 承認・実行後の確認

Scenario: 確定結果と後続の現在値を区別する
  Given 保全担当者がUC-B14でEquipmentState変更をPrepareした
  And 別の認証済み有権限承認者が同じcanonical Snapshot hashをApproval APIで承認した
  And 元requesterが有効期限内にExecute APIでRUNNING version 10からUNDER_MAINTENANCE version 11へ確定した
  And 後続の別の正当な更新で現在状態がRUNNING version 12になった
  When 元requesterが最初のUpdateRequestの結果と現在状態を確認する
  Then 保存された確定afterはUNDER_MAINTENANCE version 11のままである
  And 現在値RUNNING version 12とversion差を区別して返す
  And 同じExecuteの再送で業務更新を重複実行しない
  And Agentは承認者・requesterに代わってApprovalまたはExecuteしない
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

BS-03で継続案が費用上有利という受入意図は保持する。PO-B01は確定済み。選択された共通期間・費用範囲で総額が既知な二案の登録費用差を比較するが、交換費・交換停止損失が不明なら全体の優劣を確定しない。正式入力の任意cost_recoveryへ日次稼働・一定稼働・損失解消の仮定と出典を保持し、条件がそろった場合に150日を算出する。省略・未知・不成立では算出しない。150日を厳密な両案の損益分岐と断定しない。BS-02 / 07の14 daysは調達lead timeであり、14×24時間の完全停止損失を自動計算しない。BS-03の16 hours/dayを他ケースへ流用しない。

BS-05は能力面の吸収可否を検証する。業務上の完全代替には一段置換の全AND依存、稼働状態、製品互換性、安全・品質条件、評価期間等の充足も必要。未知の残存リスクはunknownsへ記載する。BS-G01の数値・各案の実行可能性・リスク根拠はPO-B01〜07後に専用fixtureで固定し、BS-02 / 03を無条件に混ぜない。

## 4. UC ↔ Scenario ↔ ACと必要な業務契約

この表は各BSに必要な契約の対応であり、実装状況ではない。PO確定範囲はrequirements §14.3、検証範囲は§7以降の受入対応表を参照する。既存ACだけで追加のAC-Bを代替しない。

| BS | UC | AC | 必要な契約 / 対応するPO項目 |
|---|---|---|---|
| BS-01 | UC-B01・15、UC-04・16 | AC-B01・11、AC-G01〜03・10・11 | 影響候補と経路、完全性、実停止との区別 |
| BS-02 | UC-B01・05〜07・09・13・15 | AC-B01・04・05・09・11 | 構造影響・費用・時間・共通条件での比較。PO-B01・02・05・07 |
| BS-03 | UC-B05・07〜09・15 | AC-B03〜07・11 | 劣化・交換計画・安全・比較・条件付き単純費用回収。PO-B01・02・04・05・07 |
| BS-04 | UC-B04・09・10・15 | AC-B03・05・06・11 | 安全基準・出典付き判定入力と停止必須の優先。PO-B04・07 |
| BS-05 | UC-B02・03・09・15、UC-19 | AC-B02・03・11、AC-G05 | 構造候補・能力・互換性・残存リスクの分離。PO-B03・04・07 |
| BS-06 | UC-B02・03・13・15、UC-19 | AC-B02・09・11、AC-G05 | 構造候補・能力不足・製品影響。PO-B03・07 |
| BS-07 | UC-B07・09・13・15 | AC-B05・07・09・11 | 調達・作業・停止時間・暫定期間・比較。PO-B01・05・07 |
| BS-08 | UC-B01・04・15、UC-16 | AC-B01・03・09・11、AC-G01〜03・08・10 | 経路・探索不完全性とリスク次元の分離。PO-B04・07 |
| BS-09 | UC-B05・13・15 | AC-B04・09・11、AC-04 | 未知を0とせず、独立加算可能な既知小計を分離。PO-B02・07 |
| BS-10 | UC-B06・07・09・13 | AC-B05・09、AC-04 | 未知費用と比較不能の保持。PO-B01・05・07 |
| BS-11 | UC-B04・08・13・15 | AC-B03・06・09・11、AC-04 | 劣化・安全・経済の出典、推定／確定、未知の保持。PO-B02・04・07 |
| BS-12 | UC-B06・07・12・13・15、UC-02・03 | AC-B05・08・09・11、AC-04 | 故障原因・費用・過去損失の正式入力と将来予測との分離。PO-B01・05〜07 |
| BS-G01 | UC-B01〜10・12・13・15 | AC-B01〜11、AC-01・02・04・06、AC-G01〜03・05・08・10・11 | 正式入力・比較・根拠・未知を専用fixtureで統合。PO-B01〜07 |
| BS-13 | UC-B11・13・15 | AC-B07・09・11 | buffer・需要と条件付き復旧期限。PO-B03・07 |
| BS-14 | UC-B14、UC-05 | AC-B10・11、AC-02〜09・13・16 | 現在状態Prepareは既存仕様で成立。次回保全の停止は保全予定として扱い、自動状態変更しない |
| BS-15 | UC-B04・08・10・13・15 | AC-B03・06・09・11 | 出典付き安全入力。PO-B04・07。未確認を許容済みとしない |
| BS-16 | UC-B05・13・15 | AC-B04・09・11 | 独立性・適用時間・既知小計／総額不明の分離。PO-B02・07 |
| BS-17 | UC-B16、UC-01・11 | AC-03・04、AC-B01・11 | 対象確認・context再検証は既存仕様で成立 |
| BS-18 | UC-B01・13・15 | AC-B01・09・11、AC-G08〜11 | 探索完全性・非CURRENT拒否は既存仕様で成立 |
| BS-19 | UC-B14・17、UC-05・10・15 | AC-B10・11、AC-06〜10・12・15 | Approval / Execute・確定後確認は既存仕様で成立 |

### 4.1 元案を補うケースと残る不足

元案の13ケースを保持し、BS-13〜19を追加した。納期・復旧期限、明示的Prepare、安全不明、損失加算不可、曖昧対象、影響なしと分析不能、承認・実行後の確認を補う。BS-13の計算fixtureは単純モデルの前提を固定した試験入力であり、一般業務ルールの確定ではない。UC-B14の「次回保全で停止」は保全予定として登録し、自動状態変更を伴わない。非CURRENT、打切り、過去as_of、権限拒否は既存下位試験と連携して検証する。

## 5. 実装時の検証原則

LLMに数値計算を任せず、固定正本fixtureと決定論的計算処理を使う。主要assertionはaffected objects、pathsとhop、numeric resultsと単位・期間、feasible / excluded / 判定不能なoptions、risk dimensions、Evidence、unknowns、各評価のcompletenessとする。LLM自然言語の完全一致を主判定にしない。

計算のUnit / Contract、正本取得と認可のIntegration、AgentのTool選択と説明のE2E / Evals、最上位の業務受入を分ける。mockの成功だけで実LLMの説明品質や実DBの整合性を合格にしない。既存Integration / T-R / Unit / Recoveryは削除しない。

## 6. デモとの関係

LogiScopeの業務シナリオ等は「業務の問いから調査・根拠・判断へつながる」雰囲気だけを参考にした。本書の追加ケースと期待結果はLineScopeの要件・不足レビューから導いたものであり、物流モデル、Tool、更新経路、データ、コードを継承していない。

## 7. API受入チェックポイント

| 対象 | 試験 | 確認済み範囲 | 未確認・残作業 |
|---|---|---|---|
| BS-18、UC-B01・13・15、AC-G08・10・11 | `test_graph_business_scenarios.py::test_bs18_analysis_unavailable_is_distinct_from_no_impact`（5条件） | 実PostgreSQL / Neo4jとPOST /agentで、完全探索の空結果、打切りpartial、LAGGING / ERROR / REBUILDINGの拒否、経路・世代Evidenceを検証 | ScriptedLLMでTool呼出しを固定。実LLMの選択・日本語説明品質は未検証 |
| UC-16・19・20の構造参照フロー、AC-G01・02・05・06・10 | `test_graph_business_scenarios.py::test_equipment_investigation_connects_impact_alternatives_and_spof_without_mutation` | 影響製品、直接・間接分類、代替成立、対象別SPOF結果、各ToolのEvidence、業務更新なし | BS-05 / 06の能力評価、BS-G01の統合業務判断は保証しない |
| BS-14、UC-B14、AC-B10・11 | `test_controlled_action_scenarios.py::test_bs14_analysis_then_explicit_prepare_keeps_current_state_unchanged`（2表現） | 分析後の通常の変更命令と、元の「M-204の現在状態をUNDER_MAINTENANCEに変更する準備を作って」の両方で、RUNNING v10→UNDER_MAINTENANCE v11のSnapshotとPENDING Approvalを作成。Prepareは現在値を変えず、未承認Executeも拒否 | 実LLMの分析説明品質・将来停止予約は未検証／PO判断待ち |
| BS-19、UC-B14・17、AC-B10・11、AC-06〜10・12・15 | `test_controlled_action_scenarios.py::test_bs19_confirmed_after_is_preserved_after_later_authorized_update_and_replay` | 二回ともPrepare→別承認者のApproval→requesterのExecuteを経由。最初の確定after v11と現在RUNNING v12・version差を分離し、再送でも履歴・Outboxが増えない | 要求GETは保存結果、Execute再送は保存結果と現在観測を返す。LLMを承認・実行主体にしない |

上記のAPI構造化結果は対象試験でPASS。実LLM品質は未検証であり、自然言語E2Eを含むBusiness Scenario全体の合格とは区別する。表にないケースは、このチェックポイントでは未評価。PO-B01〜08の不足仕様・BLOCKED状態を解消したと扱わない。

## 正式能力入力の接続範囲

PO-B03と能力情報のPO-B07は確定済み。CapacityInputに同一製品・単位・期間の率と負荷、互換性、出典を登録し、サーバ計算からBS-05 / 06の能力評価とBS-13の条件付き期限を検証する。API接続の試験をシナリオ全体のPASSとは扱わない。Agent / 画面は同じPRで代表経路を確認する。Graph・状態・安全条件を統合したBS-G01は引き続き未受入。安全入力のPO-B04・安全B07は確定済み。対応計画・故障履歴のPO-B05・B06・対象B07も確定済み。統合受入は残る。

## 正式安全入力の接続範囲

- PO-B04と安全情報B07は確定済み。SafetyInputの登録済み判断を用いてBS-04の継続候補除外、BS-11 / 15の不明の維持、BS-03の条件付き判断を検証する。
- 単一登録記録の評価であり、設備全体の安全認定・実運転許可ではない。既存稼働状態の事実登録を拒否しない。
- 他の正式入力と統合したDecision Package / BS-G01、一般LLM品質は引き続き別の受入工程。

## 正式対応計画・履歴の代表fixture

- 交換案：調達待ち336時間、作業4時間、停止2時間。評価期間を明示し、交換費を除く直接費10,000 JPY、算入交換費20,000 JPY、算入trueなら既知直接費小計30,000 JPY。停止損失・劣化損失を含む総額は不明。
- 交換費算入条件や停止時間の訂正をnullで確定した場合、versionを進め、未知を0へ変換しない。
- 故障・修理：過去事象期間、出典、故障／修理分類、過去停止損失120,000 JPYを登録可能。将来故障率は不明、将来案の費用には加算しない。
- 同じ設備に同じ最早開始時刻のPLANNED保全予定が2件あれば両方を次回候補とし、利用者が選択する。関連付けの確定だけでEquipmentStateは変化しない。

これらは登録／参照の代表fixtureであり、全案の統合比較・BS-G01の包括受入は別に確認する。


## 統合比較の受入範囲

| 対象 | 正式入力・実Graphから検証する内容 | 残る範囲 |
|---|---|---|
| BS-02・09・16 | 修理案の停止損失率200000 JPY/hour、未知損失と独立加算不可の小計分離 | 全BSの自然言語説明・一般品質 |
| BS-03・10 | 共通期間で総額が既知な二案の費用差、未算出案・除外案の保持 | 日次稼働・損失解消仮定の登録と150 daysを別途検証。全BSの自然言語品質は区別 |
| BS-04・11・15 | 選択安全入力の停止必須・条件付き・未知の区別。未知混在で許容へ昇格しない | 設備全体の安全や実運転許可を認定する機能ではない |
| BS-05・06・13 | 実Graphの一段候補・世代と、正式能力・不足率・条件付き期限・選択安全を並列表示 | 品質や実運転許可の不足はUNKNOWNを維持 |
| BS-07・12 | 調達待ち・作業・停止時間、選択した故障／修理履歴と過去損失を分離 | 将来故障確率は推測しない |
| BS-G01・08 | 六次元の確認事実・不足、Graph経路と選択入力、登録費用差、更新しない境界 | Golden専用fixture全体、一般LLM／検索品質、全UI経路の総合受入 |

決定論的な計算・接続のPASSと、各BS全体の受入は区別する。新規試験はdomain 14＋実PG / Neo4j API 2＋Agent Tool提示3の計19ケース。既存の認可・未知・拒否・承認更新の試験を維持する。実行結果はdocs/historyとPRに記録する。


## BS-03とGoldenの正式入力fixture

- BS-03：30日間、稼働480時間、16 hours/day、劣化1000 JPY/hourを全稼働時間へ適用、直接交換費2400000 JPY、交換効果と一定稼働の仮定を出典付き登録。継続損失480000 JPYと単純費用回収150 daysを分けて検証する。v6のPrepare→別管理者承認→requester確定→取得→条件削除→訂正→再送と、既存v2の承認待ち・hash互換も確認する。
- Golden：RUNNING設備、複数工程／作業／製品へ到達する実Graph、一段候補M-208、能力90−60＝30、buffer 120から条件付き4時間、共通30日、修理1900000 JPY（直接費300000＋停止損失1600000）、交換2400000 JPY、継続480000 JPY、単純費用回収150日を固定する。
- 修理計画は作業8・停止8時間、交換計画は調達336・作業4・停止2時間を正式入力で与える。選択安全宣言はCONDITIONAL。品質・設備全体の安全・実運転許可・将来故障率は不明を保持し、実行可能性を自動認定しない。これは仕様上の不明であり、架空の許可機能を追加して埋めない。
- 代表fixtureのAPI受入はtest_golden_registered_acceptance.py。画面では正式入力の選択、費用回収条件の読込み・訂正・v6承認・確定・version再取得、150日の表示、実モデルの比較Tool参照を確認する。数値fixtureの成功と一般LLM／検索品質の合格は分けて記録する。


## 全BSの受入根拠と未検証範囲

以下は既存の実装・試験が保証する意味の対応。試験実行結果・実モデルの文章レビューは履歴へ記録する。列挙だけでBS全体のPASSにしない。

| BS | 決定論的な受入根拠（backend/tests配下） | 主な保証・残る境界 |
|---|---|---|
| 01・08 | interfaces/test_graph_business_scenarios.py、interfaces/test_registered_decisions.py | 実Graph到達・世代・不完全性。実停止やCascade確率は認定しない |
| 02 | interfaces/test_decision_business_scenarios.py（STOPPED）、domain/test_decision_assessments.py | 200000 JPY/hour、修理1900000 JPY、共通期間・未知の区別 |
| 03 | domain/test_cost_recovery.py、interfaces/test_cost_recovery.py、interfaces/test_golden_registered_acceptance.py | 480000 JPYと150日、仮定・未知・v2互換・v6承認／確定 |
| 04・15 | interfaces/test_safety_inputs_api.py、domain/test_safety.py、interfaces/test_decision_business_scenarios.py（SAFETY_STOP） | 正式入力・停止必須・未知・期限外。設備全体の許可ではない |
| 05・06 | interfaces/test_registered_decisions.py、domain/test_capacity.py | 一段構造・90−60・安全条件を別々に提示。品質と実運転可否はUNKNOWN |
| 07 | interfaces/test_maintenance_inputs_api.py、interfaces/test_golden_registered_acceptance.py | lead time 336・作業4・停止2時間の分離。納期保証へ一般化しない |
| 09・10・16 | interfaces/test_decision_business_scenarios.py、domain/test_decision_assessments.py | 欠損損失・修理費不明・非独立損失・異なる適用時間を合算しない |
| 11 | domain/test_safety.py、domain/test_decision_assessments.py | 推定・期限・条件付き宣言を確定許可へ昇格しない |
| 12 | interfaces/test_maintenance_inputs_api.py、application/test_decision_maintenance.py、domain/test_decision_assessments.py | 正式故障履歴・過去損失・出典。将来故障率は作らない |
| 13 | domain/test_capacity.py、interfaces/test_capacity_inputs_api.py、interfaces/test_golden_registered_acceptance.py | buffer 120から条件付き4時間。製品／単位／期間不一致・未知を保持 |
| 14 | interfaces/test_controlled_action_scenarios.py | 分析だけではPrepareしない。明示準備・別承認者・requester確定。予定を自動実行しない |
| 17 | interfaces/test_agent_api.py、agent/test_agent_input.py | 曖昧対象・context owner・再検証。実モデルの名前解決品質は別判定 |
| 18 | interfaces/test_graph_business_scenarios.py | 空結果・partial・LAGGING／ERROR／REBUILDINGを区別 |
| 19 | interfaces/test_controlled_action_scenarios.py | 保存afterと最新current、再送、履歴／Outboxの非増殖 |
| G01 | interfaces/test_golden_registered_acceptance.py、frontend/scripts/verify-comparison.mjs | 正式入力から比較・根拠・未知・承認更新の代表経路。一般LLM／検索品質と全UI variantの受入は別判定 |

実LLMはread-demo-v2のTool選択・構造化結果と文章を別判定する。検索はretrieval-demo-v1の6文書・6質問でhit@1、recall@3、MRR、正本引用の一致を測る。小規模合成datasetの成功を実運用全体の品質保証へ拡大しない。一般品質閾値はevals §6に従いbaseline確認後のPO承認を必要とする。
