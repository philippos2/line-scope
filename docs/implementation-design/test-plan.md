# LineScope テスト計画・テスト仕様書

## 1. テストレベル

Unit / Integration / API Contract / Transaction / Concurrency / Projection / Graph / RAG / Security / E2E / Recovery

### 1.1 リスクと相互作用に基づくケース選択

ケース数ではなく、要件・不変条件・失敗の検出能力を設計する。新規追加・既存最適化では、次の順で選択理由を残す。

1. 対応UC / AC / T-R、検証する規則、誤動作した場合の影響を特定する。
2. 入力因子と水準、有効な組合せの制約、既知の相互作用を列挙する。無効入力は通常、他の入力を正常に固定して一つずつ検証し、どの拒否規則が働いたかをassertする。
3. 同値クラス、境界値、状態遷移、必須の相互作用からケースを選ぶ。空・省略・NULL・0・UNKNOWN等は契約が異なるなら別クラスとする。
4. 規則単体はUnit、DB constraint / lock / rollbackは実DB Integration、公開schema / 認可 / EnvelopeはContract、業務の一連の操作はBusiness Scenarioで検証する。上位試験へ下位の全ケースを掛け合わせない。
5. 選択したケース、保証範囲、省略する組合せとその根拠、実行時間をレビューする。未確認の網羅性を主張しない。

| 対象 | 選択方法 | 省略してはならない検証 |
|---|---|---|
| 認可・閲覧境界 | §3の全role×operationを維持。owner / requester / approver、全Target拒否を追加 | 許可と拒否、偽identity、権限喪失、fail closed |
| 状態遷移・更新 | 許可遷移と禁止遷移、境界値、各重要障害点 | 同値更新、期限直前・一致・超過、stale version、Audit / Outbox原子性 |
| 並行・復旧 | 制御したinterleavingと障害注入 | lock順、二重消費、commit順逆転、rollback、世代切替中断 |
| Graph成立判定 | AND / OR / 除外 / 一段置換の規則と既知の複合条件 | cycle、UNKNOWN、探索不完全、各上限の境界、複数上限の優先 |
| 独立した非安全系の入力条件 | 同値クラスを整理した上で、必要時に制約付きペアワイズ | 既知の3因子以上の相互作用と過去の回帰ケースは別途追加 |
| 業務API / 実LLM | 固定fixtureの代表フローと意味論的assertion。実LLM品質はevalsへ分離 | Business Scenarioの受入結果、Evidence、unknowns、未実装の明示 |

ペアワイズは任意の二因子の各水準組を、有効な制約の範囲で少なくとも一回含めるケース選択であり、全組合せの保証ではない。直交表も因子・水準・制約が適合する場合に限る。`pytest.mark.parametrize`の使用だけでペアワイズを実施したとは扱わない。適用時は因子表、制約、選択ケース、二因子被覆の確認を残す。Security / SafetyのHard Constraint、既知の多因子相互作用、重大Failをペアワイズだけで代替しない。

### 1.2 既存テストの効率改善と計測

全suiteの`--durations=30`と対象suiteの前後計測で、callだけでなくsetup / teardownを確認する。DB準備の累積負担、外部待機、重複フローを区別し、実測した原因から改善する。CI runnerとローカルの秒数は直接比較せず、同じ環境・条件の測定を優先する。

- まず不要な待機や共通準備を見直す。テストサーバーの終了poll短縮を、本体のtimeout・競合待機・期限境界短縮と混同しない。
- fixture共有は、変更状態の隔離と終了時の復元が保証できる場合だけ行う。function scopeのDBを無条件にsession scopeへ変えない。同じDBを共有するsuiteは並行投入しない。
- 同じ規則を複数階層で検証すること自体は重複とは限らない。API配線・認可・DB保証等の別の欠陥を検出するなら維持する。
- ケース統合・置換は、旧assertionと新assertionの対応、失われないAC / 境界 / 障害点を示して行う。時間短縮だけを理由にケースを削除・skipしたりassertionを弱めたりしない。

現在の全suiteをペアワイズ設計済みとは扱わない。既存ケースの全面削減は行わず、変更対象ごとにこの選択手順を適用する。CI jobの分離は待ち時間対策であり、ケース設計の代替ではない。

## 2. AC対応表

| AC | 主テスト |
|---|---|
| AC-01 | Read non-mutation |
| AC-02 | No explicit update |
| AC-03 | Ambiguous target |
| AC-04 | Hallucinated fact guard / grounding |
| AC-05 | Role×operation |
| AC-06 | Unapproved execute |
| AC-07 | Snapshot hash mismatch |
| AC-08 | 30-minute expiry |
| AC-09 | Non-owner execute |
| AC-10 | Version conflict |
| AC-11 | CREATE business-key duplicate |
| AC-12 | Double execute / double approval consume |
| AC-13 | Multi-target rollback |
| AC-14 | Failure reporting |
| AC-15 | Post-commit reread |
| AC-16 | Approval invalidation |
| AC-17 | History visibility matrix |
| AC-18 | Assignment ↔ USES projection |
| AC-G01〜G07 | Graph traversal semantic tests |
| AC-G08 | All four hard limits |
| AC-G09 | SPOF incomplete=INDETERMINATE |
| AC-G10 | Evidence grounding |
| AC-G11 | LAGGING/ERROR/REBUILDING rejection |
| AC-G12 | type/cycle validation |
| AC-G13 | outbox commit-order inversion |
| AC-G14 | old aggregate_version replay |
| AC-G15 | DEAD -> ERROR |
| AC-G16〜G17 | rebuild |
| AC-G18 | deterministic path tie-break |
| AC-R01〜R03 | RAG authorization/version/injection |

## 3. Authorization / Approval

- 全role×operation
- user_id/role spoofing
- self-approval rules
- DependencyRelation self-approval拒否
- GET update request visibility
- snapshot_hash mismatch
- unapproved request has no expiry; approve replay does not extend expiry
- execute exactly at/after expiry boundary
- execute by non-requester
- approval invalidation
- same approval concurrent execute

## 4. Transaction

- CREATE expected_version NULL
- UPDATE/DISABLE version
- multi-target atomicity
- technical pre-commit failure preserves APPROVED
- version/business conflict INVALIDATED
- COMPLETED execute replay returns existing result

## 5. Concurrency

- two UPDATE same row
- duplicate CREATE
- two DependencyRelation CREATE forming combined cycle
- graph mutation advisory lock timeout
- assignment change concurrent with dependency change

Isolation levelはREAD COMMITTEDで検証する。

## 6. Outbox

- business update + Outbox same transaction
- transaction rollback leaves neither
- BIGSERIAL/UUID order independent of commit order
- later-committed event with lower sortable identifier is still processed
- retry
- worker restart
- leader advisory lock
- DEAD
- DEAD stops later projection
- source_version stale replay
- same-version idempotent replay

## 7. Graph

- each relation type direction
- allowed source/target matrix
- mixed-direction traversal
- shortest-hop direct/indirect
- deterministic representative path
- permitted SUPPLIES cycle
- prohibited dependency cycle
- effective_from/to as_of
- required=true/false semantics
- depth/node/path/time limits
- SPOF incomplete

## 8. Rebuild

- REBUILDING blocks Graph analysis
- graph-affecting mutation waits/fails by timeout
- pending drained before rebuild
- DEAD aborts rebuild
- rebuilt graph equals PostgreSQL source
- CURRENT after completion

## 9. RAG

- KnowledgeDocument metadata
- inactive version
- access_class re-check
- stale Qdrant metadata
- injection text

## 10. API Envelope

- request_id always
- context_id propagation
- evidence not dependent on LLM text
- partial Graph fields
- errors[] machine-readable

## 11. Major Fail Gate

`acceptance-criteria.md` §5の全項目に少なくとも1件の自動テストがあり、全件成功しなければリリース不可。

## 12. レビュー修正の追加テストとAC対応

| Test ID | シナリオ・期待結果 | AC |
|---|---|---|
| T-R01 | 二UPDATEをversion確認直後に競合させ、片方だけ確定。失効処理と成功再Execute競合でもCOMPLETEDを保持 | AC-10・12・16 |
| T-R02 | 同retry keyの並行Prepare / HTTP再送で1要求。異入力はDUPLICATE_REQUEST、rollback後は同キー再試行 | AC-11・12 |
| T-R03 | JSON key・集合順・timezone差で同hash、業務値変更で別hash。保存Target改変検出 | AC-07・16 |
| T-R04 | 長期間PENDINGからapprove可、approve再送で期限不変。lock待ち後・承認消費前の期限到達で更新なし | AC-06・08 |
| T-R05 | PENDINGのversion変化はINVALIDATED、新規Prepare。送信hash誤りだけでは状態不変 | AC-07・16 |
| T-R06 | requester / approver権限喪失で新規Execute拒否・失効。COMPLETED再送はowner限定 | AC-05・09・12・17 |
| T-R07 | 異種カテゴリ拒否、同カテゴリ複数Targetの全権限と閲覧境界 | AC-05・13・17 |
| T-R08 | 割当期間分割・期間外保持・明示NULL無期限・空集合・親version。差分途中失敗は全ROLLBACK | AC-03・07・10・13・18 |
| T-R09 | COMMIT直後別更新で確定after維持・現在値差分。再参照障害でもCOMPLETED、再送結果不変 | AC-14・15 |
| T-R10 | shared Graph探索中にExecute / Projectionを待機させ、Evidenceのgeneration固定。終了時ERRORなら正常Graph結果なし | AC-G11 |
| T-R11 | 初期未構築・fatal_errorでERROR。通常worker停止と重大障害を区別し、未処理ならLAGGING | AC-G11・15 |
| T-R12 | pending / retry / lease切れをRebuild controllerがdrain。DEAD中止・世代検証・切替前後crash・flag復旧 | AC-G13・15〜17 |
| T-R13 | Relation endpoint/type変更・DISABLE後に旧event再送しても復活しない。同version異payloadはDEAD | AC-G14・15 |
| T-R14 | 2必須依存の片方だけの別経路で成立しない。一段置換の全必須依存・availabilityを評価 | AC-G03・05・06 |
| T-R15 | SUPPLIES必須方向・循環は到達可能だが成立判定INDETERMINATE。未知availability・過去時点も確定しない | AC-G07・09、AC-04 |
| T-R16 | 上限ちょうどで未探索なしならcomplete=true。4上限・同時制限優先・決定的BFS / representative path | AC-G08・18 |
| T-R17 | 現場Graph拒否・通常依存Read許可。context別user / TTL拒否、Tool上限・明示意思不足でPrepareなし | AC-02・03・05 |
| T-R18 | RAG単一active・旧hash・未知class拒否、upsert失敗で旧版維持、生成前失効除外、正本から再構築 | AC-R01〜03 |
| T-R19 | API schema・HTTP code・ID/hash/時刻・空Body・Target配列・warningsを契約どおり検証 | AC-03・07・14、AC-G10 |
| T-R20 | 成功・拒否・失効・失敗・Projection監査をrequest / approval / outboxで追跡し権限外閲覧拒否 | AC-14・17 |
| T-R21 | 許可状態値・必須業務項目・時刻範囲、保全実績と設備/予定の非連動 | AC-03・05・07・13 |

上記は実装時の自動テスト仕様であり、文書修正時点で実行・合格したものではない。AI誤分類・説明の正確性はevalsも併用し、決定論的制御は本書で検証する。

### セルフレビューで追加した境界ケース

- T-R03 / R05: replace_update_request_idのowner・終端拒否、新Prepare失敗で旧要求維持、失効と新保存の原子性（AC-07・09・13・16）。
- T-R08: 同じoperation/equipment/effective_fromの区間分割で既存行UPDATEを使い、inactive業務キー再利用時もversion競合を検出（AC-10・11・18）。親equipment_assignmentsのbefore / afterと差分Targetを照合し、親欠落・差分欠落・集合改変・他親への割当ID重複を拒否する。予定値と割当の同時変更でも親version増分は1。
- T-R11 / R12: NOT_INITIALIZEDから初期Rebuild成功、既存fatal_errorの復旧、検証後のみerror解除（AC-G11・16・17）。
- T-R19 / R20: 全許容Request/Approval組、FAILED/INVALIDATEDと終端状態保護、context確認応答を成功更新と混同しない（AC-06・12・14・16）。

- T-R01 / R08 / R13: 複数Graph Targetの業務キー移動・交換を最終集合で検証し、中間UNIQUE衝突による部分更新なし（AC-11・13、AC-G12）。
- T-R12: generation欠損かつpending残存のRestoreから、作業用Graph検証 → drain → 最終Rebuildで復旧。DEADは中止（AC-G13・15〜17）。

- T-R02 / R03: retry scopeをuserごとに分離、終端再送・context TTL後再送で同要求、異内容409。decimal / 重複JSON key / surrogate / timezoneなし拒否、C0文字のcanonical byte一致。
- T-R10 / R12: leader → mutation順、PROCESSING claimと分析競合、generation validated markerとcontrol pointerの切替前後crash復旧。
- T-R14 / R15: OR候補のAVAILABLE優先、UNKNOWNのみ未確定、置換候補の依存を推移置換しない、除外前不成立をSPOFと断言しない。

## 13. Business Scenarioを最上位受入試験に追加

Business Scenario / Acceptance → Agent / Application E2E → Integration → Contract → Unitを業務受入の階層とする。Transaction / Concurrency / Projection / Graph / RAG / Security / Recoveryは引き続き下位で検証する。

[Business Scenario仕様](business-scenarios.md)のBS-01〜19 / BS-G01、固定数値、UC ↔ BS ↔ AC対応を使用する。AC-B01〜11の主試験は同書§4。BS-13〜19の補足と将来停止variantの未確定事項は§4.1で追跡する。数値は決定論的に検証し、意味論的結果をassertする。

試験記録はPASS / FAIL / BLOCKED / NOT_IMPLEMENTEDを区別し、PO未決定・未実装をPASSへ含めない。既存§11のMajor Fail GateとT-R01〜21を維持する。業務判断支援全体の受入にはGoldenを含む対象ケースの合格を必要とし、段階的PRの部分テスト合格を全体完成と扱わない。

## 14. ログ設計の検証

| Test ID | 検証内容 | AC |
|---|---|---|
| T-L01 | 認証成功／拒否・HTTP例外・readiness障害のJSON完了イベント、code / level / duration / Envelopeと同一request_id、正常healthのDEBUG | AC-L01 |
| T-L02 | 並行async・threadpool処理、例外終了のContext解除、複数app設定でhandler二重追加なし、retryは別request_id・同業務ID | AC-L01 |
| T-L03 | token / DSN / body / prompt / Snapshot / SQL / 例外messageを含むfixtureで秘密が出ない。未知field・不正型・改行・長さ・stack上限、DEBUGでも同じ秘匿 | AC-L02 |
| T-L04 | commit前失敗・commit後成功・結果不明・COMPLETED replay・置換rollbackの意味を区別。監査INSERT失敗で全rollback、失敗監査fallbackは別処理 | AC-L03、AC-14 |
| T-L05 | stdout handler障害が業務結果を変更せず再帰しない、固定stderr診断にも秘密なし | AC-L02・03 |
| T-L06 | Uvicorn raw access log無効、依存logger設定、LOG_LEVEL validation、Compose各サービスの容量制限、監査DBはrotation対象外 | AC-L02・04 |
| T-L07 | Tool呼出し・Outbox retry / DEAD・Rebuildと業務監査をIDで追跡し、認可外の監査・全ログを公開しない | AC-L01・04、AC-17 |

段階導入はoperations §13.8。初回はT-L01〜03・05・06の現API／基盤部分、Transaction監査はT-L04 / T-R20、workerはT-L07を各実装時に検証する。文書のみの段階では未実行であり、既存688テストがログ受入を満たすとは扱わない。

## 15. SQL / DBアクセスのセキュリティ検証

architecture §15・NFR-04への適合を下位Security / Integration / Recovery試験で確認する。既存Unit / Contract / Integration / T-R / Business Scenarioは削除せず、以下の追加試験を既存の安全性検証と組み合わせる。

| ID | 検証 | 主な対応 |
|---|---|---|
| T-SQL01 | `' OR 1=1 --`、`'; DROP TABLE equipment; --`等をAPI / Toolの許可された文字列へ渡し、単なる値として扱われること。検索範囲を拡大せず、テーブル・行・履歴を変更しない。文字列を保存する更新では後日の再読込・検索も検証 | NFR-04、AC-05・09 |
| T-SQL02 | Tool名、filter key、table / column / ORDER BY / direction等の未知identifierを拒否し、固定allow-listだけでSQL構造を選ぶ。SQL文字列引数・任意SQL Toolを公開しない | NFR-03・04・08、AC-05・09 |
| T-SQL03 | 非owner・権限なし・偽role / user_idのmutationを拒否。DB検索roleはINSERT / UPDATE / DELETE / DDLを拒否し、変更runtime roleもDDLを拒否。role属性・schema / table / sequence / function権限・default privilegesを確認 | NFR-03・04、AC-05・09・12・17 |
| T-SQL04 | 正本更新後、成功Audit / history / Outbox / Approval消費 / COMPLETED保存の各段階で失敗を注入し全rollback。同一要求再送・stale version・並行対象の競合を検証 | NFR-05・06、AC-10・11・13、T-R06・08 |
| T-SQL05 | API / Tool経由の不変条件拒否と、DB constraint自体の拒否の両方を検証。DB errorとloggingへcredential、SQL本文、内部構造、機密bind値を外部露出しない | NFR-01・04、AC-11・13、既存API / logging試験 |

これらは追加試験仕様であり、全実装・実行済みとは扱わない。既存searchのDELETE攻撃文字列1ケースだけでT-SQL01全体の合格としない。型で拒否されるID等の試験だけで、許可された自由文字列のbindを検証したことにしない。
Core導入時も実PostgreSQLでlock順序・待機timeout・接続寿命・rollback・version・canonical Snapshot / hash・Outbox原子性を回帰検証する。mockでのSQL構造検証だけでは完了としない。

## 16. Graph業務APIシナリオの実行

`backend/tests/interfaces/test_graph_business_scenarios.py`は、Givenの正本fixtureと検証済みGraph、WhenのPOST /agent、Thenの意味論的assertionを使う。Gherkin仕様の意図をpytestで実行し、Cucumber等の新ライブラリを前提にしない。

BS-18の5条件と、影響→代替→SPOFの参照フローを実PostgreSQL / Neo4jで検証する。対応UC / AC、PASSの範囲、実LLM未検証はbusiness-scenarios §7を参照する。Outbox等は状態fixtureの準備に使い、worker復旧・lockの受入assertionをこの業務試験へ混在させない。既存下位試験は維持する。

Dockerで`pytest -p no:cacheprovider backend/tests/interfaces/test_graph_business_scenarios.py -q`を実行する。実LLMのTool選択は別のE2E / Evalsで確認し、ScriptedLLMによるAPI成功をBS-G01合格へ昇格させない。

## 17. Prepare・承認・確定後確認の業務APIシナリオ

`backend/tests/interfaces/test_controlled_action_scenarios.py`でBS-14の対応済みコマンドvariantとBS-19を検証する。初期fixtureはRUNNING version 10。分析後のPrepareが業務状態を変更せずPENDING Approvalを生成すること、二回のAPI経由の承認・実行でv11の確定結果とv12の現在値を分離すること、最初のExecute再送でbusiness history / state history / Outboxが増えないことをassertする。

後続状態を直接SQLで書き換えて正当な更新を模擬せず、Prepare→別の認証主体のApproval→requesterのExecuteを二回行う。要求GETの保存結果とExecute再送の現在観測を同一response契約と仮定しない。初期fixtureの作成と業務操作を区別する。BS-14は通常の変更命令と元の明示的Prepare例文をともに試験し、実LLM未検証範囲はbusiness-scenarios §7に残す。

Dockerで`pytest -p no:cacheprovider backend/tests/interfaces/test_controlled_action_scenarios.py -q`を実行する。既存Approval / Executeの認可、rollback、競合、期限、再送試験を維持する。

## 正式経済入力の検証

`domain/test_economics.py`は展開後8件で、190万円の修理見積、端数を含む十進積、共通期間／順序の正規化、未知率・未知時間・非独立損失、float拒否・期間不整合・重複scopeを確認する。`interfaces/test_economic_inputs_api.py`は展開後12件で実PostgreSQL上のHTTP登録・訂正・別manager承認・確定・Snapshot v2・権限・競合失効・監査失敗rollback・再送・拒否を確認する。全直積を生成せず、役割ごとの入口と重大な状態遷移を選ぶ。共通Approval / Execute / Snapshotの既存試験を回帰し、`persistence/test_db_roles.py`の既存runtime経路にも経済入力を通してquery/runtime/projectionの実権限を確認する。

この段階は正式入力HTTP経路の検証。Agent Tool、画面、実LLM、全BS / Goldenの受入を代替しない。

### 経済入力の画面・Agent接続

追加は展開後Backend 12件（検索・権限・cursor・SQL/LIKE文字・Read Tool / Evidence・Agent要約・モック経路除外10、候補のみ／複数入力の非合算要約2）、Frontend 5件（未知と0・出典text、明示Prepareとretry key、接続解除後の遅延応答、編集リセット、不正payload拒否）。既存の共通更新・Agent / Tool試験を回帰する。実ブラウザでは設備候補選択→フォーム登録→自己承認拒否→別manager承認→元requester確定→登録値検索・表示→訂正フォーム読込→実モデルによるReadを一つの業務経路で確認する。紹介動画や全BS / Goldenの受入へ拡張しない。
