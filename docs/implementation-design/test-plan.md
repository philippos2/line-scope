# LineScope テスト計画・テスト仕様書

## 1. テストレベル

Unit / Integration / API Contract / Transaction / Concurrency / Projection / Graph / RAG / Security / E2E / Recovery

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
