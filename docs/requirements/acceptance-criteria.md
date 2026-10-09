# LineScope 受入基準・トレーサビリティ

## 1. 基本受入基準

### AC-01
参照要求で業務データを変更しない。

### AC-02
明示的更新要求なしに更新しない。

### AC-03
対象が曖昧なまま任意対象を更新しない。

### AC-04
存在しない業務事実・更新結果を事実として返さない。

### AC-05
権限外の更新を実行しない。

### AC-06
認証済み承認なしに更新しない。

### AC-07
承認者が確認したSnapshot Hashと異なる内容を実行しない。

### AC-08
30分を超えた承認を実行に使用しない。

### AC-09
元requester以外からのExecuteを拒否する。

### AC-10
version競合時にUPDATE/DISABLEしない。

### AC-11
CREATE重複を業務キー・冪等性で防止する。

### AC-12
同一Approval / UpdateRequestを二重実行しない。

### AC-13
一UpdateRequestの複数Targetを部分確定しない。

### AC-14
更新失敗を成功として報告しない。

### AC-15
COMPLETEDの確定afterを保持する。後続更新がない場合、PostgreSQL再参照はこれと一致する。後続更新がある場合は現在値とversion差を区別して返し、確定結果を上書きしない。

### AC-16
承認対象が変化した場合、既存承認をINVALIDATEDとして再利用しない。

### AC-17
更新履歴閲覧範囲がaccess-control定義と一致する。

### AC-18
ProductionOperationのEquipment割当はAssignmentを唯一の正本とし、CURRENT時のGraph USESと一致する。非同期反映中はGraph利用を拒否する。

## 2. Graph受入基準

### AC-G01
2 hop以上を探索できる。

### AC-G02
直接/間接を最短hopで分類する。

### AC-G03
関係種別ごとの影響方向・上流方向に従う。

### AC-G04
共通依存候補に代表経路を付与する。

### AC-G05
停止対象を除外した代替候補を探索できる。

### AC-G06
指定重要対象の単一障害点候補を判定できる。

### AC-G07
許容循環で無限探索しない。

### AC-G08
上限到達時 `complete=false` と `limit_reason` を返す。

### AC-G09
SPOF探索が不完全なら `INDETERMINATE` とし「候補なし」としない。

### AC-G10
構造化EvidenceにTool未返却の経路を含めない。

### AC-G11
Graph非CURRENT時に正常な最新Graph分析結果を返さない。

### AC-G12
禁止型組合せ・禁止循環を登録できない。

### AC-G13
Outbox採番順とcommit順が異なってもcommit済み未処理イベントを取りこぼさない。

### AC-G14
古いaggregate_versionで新しいGraph状態を上書きしない。

### AC-G15
DEAD eventが存在する場合GraphをERRORとする。

### AC-G16
再構築中はREBUILDINGとしGraph分析を停止する。

### AC-G17
正本からGraphを再構築できる。

### AC-G18
代表経路は最短hop優先、同率時は決定的tie-breakで選ぶ。

## 3. RAG受入基準

### AC-R01
Qdrant検索結果をPostgreSQLの最新KnowledgeDocument metadataで再認可する。

### AC-R02
無効または旧version文書を回答根拠にしない。

### AC-R03
文書本文の命令をSystem命令として実行しない。

## 4. Requirement → UC → AC

| Requirement | UC | AC |
|---|---|---|
| R-01〜R-03 | UC-01〜04 | AC-01, AC-04 |
| R-04〜R-06 | UC-05〜15 | AC-02〜17 |
| R-07〜R-13 | UC-16〜20 | AC-G01〜10, AC-G18 |
| R-14 | UC-21 | AC-05〜13, AC-G12〜15 |
| R-15〜R-16 | UC-16〜20 | AC-G04, AC-G08〜10, AC-G18 |
| R-17〜R-18 | UC-01〜21 | AC-01〜18, AC-G01〜18 |
| R-19 | UC-01〜21 | AC-04, AC-G10 |
| R-20 | UC-11 | AC-03 |
| R-21 | UC-05〜15, UC-21 | AC-02 |
| R-22 | UC-18〜20 | AC-G04〜09 |
| R-23〜R-25 | UC-05〜15, UC-21 | AC-03, AC-07 |
| R-26〜R-31 | UC-05〜15, UC-21 | AC-05〜09, AC-16 |
| R-32〜R-35 | UC-05〜15, UC-21 | AC-11〜17 |
| R-36 | UC-10 | AC-15 |
| R-37〜R-38 | UC-04, UC-16〜20 | AC-G11, AC-G15〜17 |
| R-39 | UC-15, UC-21 | AC-10〜13, AC-G12〜14 |
| R-40 | UC-09 | AC-18 |

## 5. 重大Fail

AC-02〜AC-18、AC-G09〜AC-G17、AC-R01の違反はリリース不可とする。

## 6. レビュー修正の判定補足

| 既存AC | 追加確認（要件の具体化） |
|---|---|
| AC-02・03 | 元messageの明示更新意思、context所有者・失効、曖昧対象の再検証 |
| AC-05・09・17 | 単一カテゴリ、全Target権限、Graph分析role、承認者現在権限、COMPLETED再送owner |
| AC-07・16 | canonical Snapshotの固定、PENDING失効、誤hash入力だけでは失効しない |
| AC-08 | 未承認は無期限、期限ちょうどのExecute拒否、approve再送で延長しない |
| AC-10〜13 | 条件付きUPDATE、DB UNIQUE、Prepareキー、失効処理競合、割当期間分割原子性 |
| AC-14・15 | commit後再参照障害を更新失敗にしない、保存結果再送、現在version区別 |
| AC-18 | 割当区間外保持・親version・USES、Graph CURRENTの一致 |
| AC-G03・05・06・09 | SUPPLIES required方向、AND成立、一段置換、循環・未知availabilityでINDETERMINATE |
| AC-G11・15〜17 | 分析中lock、worker重大障害・未初期化ERROR、Rebuild controller drain・世代切替・復旧 |
| AC-G14 | endpoint/type変更・DISABLE後の旧version再送、同version不正payload拒否 |
| AC-R01〜03 | FACTORY_INTERNAL再認可、単一active version、hash・有効化・再構築・生成前再確認 |

AC-G09の不完全性と業務判定の未知は別に表す。過去as_ofは現在登録関係の期間評価に限定し、当時の状態を捏造しない（AC-04 / AC-G10）。重大Fail集合は§5を維持する。

## 7. 業務判断支援の受入基準

以下は追加の受入目標。未決定の業務入力・ルールはrequirements §14.3に依存する。文書化やfixtureの手計算をもって実装合格としない。

### AC-B01 影響と根拠

直接／間接影響と順序付き経路を提示し、影響なしと確認不能を区別する。

### AC-B02 能力と代替

同じ製品・単位・期間条件で必要量と空き能力を比較し、不足を計算する。CAN_SUBSTITUTEだけで業務上十分としない。

### AC-B03 リスクの区分

6つのリスク次元とuncertaintyを分け、根拠のないスコア・確率・安全断定をしない。

### AC-B04 決定論的経済評価

固定fixtureの式・入力・単位・期間・数値を再現する。加算条件と推定／確定を示す。

### AC-B05 共通条件の比較

対応案の費用・期間・生産影響・残存リスクを共通条件で比較し、不足時は優劣を確定しない。

### AC-B06 安全制約

Hard Safety Constraint違反案を実行可能候補から除外し、基準とEvidenceを提示する。

### AC-B07 計画・暫定期間

lead timeと作業時間を区別し、暫定期間・次回計画・納期影響を根拠がある範囲で提示する。

### AC-B08 履歴

故障・修理履歴と過去損失を根拠で説明し、未知の将来故障率を生成しない。

### AC-B09 不完全性

未知を0にせず、判明subtotalを完全合計としない。Graph・能力・経済・リスクの不完全性を区別する。

### AC-B10 人間の判断と変更境界

Golden分析だけではPrepare / Approval / Executeを行わない。明示更新時も既存カテゴリ・全Target権限・承認・実行境界を守る。

### AC-B11 Evidence

重要な結論から計算入力・式・正本・経路・文書・前提・観測時刻を追跡できる。

## 8. 追加要件のトレーサビリティ

| Requirement | UC | AC |
|---|---|---|
| R-B01 | UC-B01 | AC-B01、AC-G01〜03・08・10・11 |
| R-B02 | UC-B02・03 | AC-B02、AC-G05 |
| R-B03 | UC-B04 | AC-B03 |
| R-B04 | UC-B05 | AC-B04・09 |
| R-B05 | UC-B06〜09 | AC-B05・07 |
| R-B06 | UC-B08・10 | AC-B06 |
| R-B07 | UC-B11 | AC-B07 |
| R-B08 | UC-B12 | AC-B08 |
| R-B09 | UC-B13 | AC-B09 |
| R-B10 | UC-B09・14・15 | AC-B10・11、AC-01〜18 |

UC ↔ BS ↔ ACの詳細は[business-scenarios.md](../implementation-design/business-scenarios.md) §4を正とする。追加Business Scenarioは最上位の業務受入試験だが、既存の重大Fail Gateを置き換えない。該当するAC-Bを満たさない機能を受入済みとしない。未決定事項に依存するケースはBLOCKEDと記録し、skipを合格数へ含めない。

### 8.1 補足ユースケースの対応

UC-B16はR-06・20・23、AC-03・04、BS-17に対応する。UC-B17はR-05・35〜38、AC-06〜10・12・15、BS-19に対応する。UC-B11の復旧期限はBS-13、UC-B14の現在状態PrepareはBS-14で補う。安全不明・加算不可・分析不能のvariantはBS-15・16・18で検証する。

## 9. 運用ログの受入基準

| AC | 判定 | 対応要件 |
|---|---|---|
| AC-L01 | HTTP結果・Tool・非同期試行を相関ID、code、所要時間で追跡でき、並行要求・retryを混同しない | NFR-L01 |
| AC-L02 | 禁止項目がINFO / DEBUG / 例外時にも漏れず、未知field・改行・長さ・stackがoperations契約に従う | NFR-L03 |
| AC-L03 | commit後のみsuccess、rollback / 結果不明 / replayを区別し、監査失敗・stdout失敗を混同しない | NFR-06、NFR-L02・04 |
| AC-L04 | 運用ログ容量を制限し、DB監査・履歴の正本と閲覧境界を維持する | NFR-L02・04 |

これらは追加受入目標であり未実装。既存AC-14・17、T-R20、重大Fail Gateを維持する。初回ログ基盤ではHTTPと出力制御の範囲を検証し、未実装Tool / worker / DB監査まで合格とはしない。
