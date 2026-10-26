# F2：共通必須電源の登録供給状態 — B案の最小実装計画

状態：918ddd7の32ファイル・新規22ケースは実装/自動試験実行を承認済み。実装後の回帰で計画外6試験ファイルの互換修正が必要と判明し、追加承認待ちで停止。独立環境の直接API9要求も別承認待ち。起点mainは#277のmerge `334434c2793999c6d2e05ecc71e9417255f4948d`。PR #278を分割しない。

## 1. 目的・制約・完了判定

M-208にも共通必須電源R-02を表示し、PostgreSQLに初期登録した供給状態を取得して、既存の代替利用可能性評価とEvidenceへ渡す。三値はAVAILABLE / UNAVAILABLE / UNKNOWN。実測の通電状態・運転許可とは区別する。

- R-02→M-204/M-208をrequired=trueのSUPPLIESとして登録する。資源コードや設備コードで判定を分岐しない。
- activeを供給状態へ転用せず、M-208自身のRUNNINGから電源の健全性を推定しない。
- 欠落/UNKNOWN/不完全をAVAILABLEへ変換しない。取得障害は未登録と区別する。Processは引き続き状態未モデル化としてUNKNOWN。
- 状態変更の製品UI・HTTP API・業務コマンド・Toolは作らない。Snapshot / Prepare / Approve / Execute / 履歴 / 承認権限を拡張しない。
- 質問欄の9観点・テキストボックスだけの質問UI・LLM不使用を維持する。
- 既存5173/5174の環境・DB・seed・認証・volumeを変更しない。検証用の供給状態は独立した初期データとして設定し、稼働中の状態をUPDATEして切り替えない。

受入は、必須電源への経路が見え、登録状態・根拠レコード・version・登録時刻・読取時刻を区別でき、供給不可ならM-208を利用可能と判定しないこと。供給可能でも、M-208自身や他の必須条件が満たされなければ利用可能にしない。構造上の候補と実際の代替運転は分離する。

A案の承認付き更新は今回の目的の必須条件ではない。旧調査のA案は採用せず、任意タスクとして§8へ残す。R-26等の更新・承認要件は、既存の業務更新に引き続き適用する。seedで既存状態を変更する抜け道は設けない。

## 2. 変更予定ファイル：計32（製品/データ13・試験9・文書10）

以下は予定する全ファイル。追加ファイルや契約差分が必要なら先に報告し、32ファイル・22ケース・3.5日の計画上限を超える拡張を独断で行わない。計画の文書4ファイルは今回更新し、残りは実装承認された範囲で扱う。

### 製品コード・データ：13

| ID | パス | 変更目的 |
|---|---|---|
| P01 | `backend/src/linescope/migrations/014_infrastructure_supply_state.sql`（新規） | 読取専用供給状態表。既存資源へAVAILABLEを補完しない |
| P02 | `backend/src/linescope/persistence/db_roles.py` | query/runtimeへ新表SELECTだけを許可。INSERT/UPDATE/DELETE/TRUNCATE等を付与しない |
| P03 | `backend/src/linescope/persistence/core_reads.py` | 設備/作業/資源状態を一括SELECT。既存get_resourceの追加読取情報として供給状態・根拠を返す |
| P04 | `backend/src/linescope/graph/analysis_states.py` | read_availabilityへ資源IDの任意keyword引数を追加し、PGの同一statementで観測。従来の呼出形も維持 |
| P05 | `backend/src/linescope/application/graph_availability.py` | 資源状態の対象ID・enum・version・時刻を検証し、三値mapと欠落情報へ渡す |
| P06 | `backend/src/linescope/domain/graph_requirement_rules.py` | 供給状態の決定論的な三値変換。activeや設備状態と混同しない |
| P07 | `backend/src/linescope/domain/graph_substitute_candidate.py` | InfrastructureResourceを状態参照対象へ追加し、既存必須依存ANDへ渡す。評価器は増やさない |
| P08 | `backend/src/linescope/application/alternative_evidence.py` | 代替判定の根拠へ資源の登録供給状態・記録参照・版・登録時刻を追加 |
| P09 | `backend/src/linescope/application/spof_evidence.py` | 同じ根拠をSPOF結果にも保持し、経路/世代/状態の対応を維持 |
| P10 | `backend/src/linescope/demo_file_seed.py` | JSON v1互換を維持し、v2の初期供給状態を検証/投入。同値再投入無変更、異値は原子的に拒否 |
| P11 | `backend/src/linescope/persistence/core_demo_seed.py` | 新表を固定allow-listへ追加。初期INSERTと一致照合だけ。任意SQL・UPSERT更新なし |
| P12 | `docs/demo/data/scenario1.json` | v2へ更新し共通必須電源の辺とR-02 AVAILABLEの明示的なデモ初期条件を記載 |
| P13 | `frontend/src/features/investigation/EquipmentInvestigation.tsx` | 既存の選択項目欄に登録供給状態・根拠/時刻の読取表示を追加。入力やボタンは追加しない |

既存GraphCanvasは関係DTOをそのまま描画するため変更しない。上流/下流/共通依存の到達探索自体へ利用可能性の判定を混ぜず、既存の経路Evidenceを維持する。供給状態の根拠はget_resourceと代替/SPOFの読取結果で示す。この範囲のため、新しいHTTP経路やGraph型、Query/Mutation基盤は不要。

### 試験ファイル：9（新規ケースは§6の22件だけ）

| ID | パス | 用途 |
|---|---|---|
| T01 | `backend/tests/domain/test_graph_substitute_candidate.py` | C01〜06の6件追加。従来のProcess/資源の期待は承認済み仕様へ合わせ、欠落UNKNOWN等の検査を維持 |
| T02 | `backend/tests/application/test_infrastructure_supply_state.py`（新規） | C07〜11の5件：実DB読取と障害/Evidence境界 |
| T03 | `backend/tests/test_demo_file_seed.py` | C12〜15の4件：seedと既存DB/公開Graph互換 |
| T04 | `backend/tests/persistence/test_db_roles.py` | C16〜17の2件：実DBのquery/runtime権限 |
| T05 | `backend/tests/interfaces/test_alternative_api.py` | C18〜19の2件：実PG/Neo4jからAPIへ供給不可/不明を反映 |
| T06 | `backend/tests/application/test_spof_analysis.py` | C20の1件追加と既存試験アダプタのkeyword互換修正 |
| T07 | `backend/tests/application/test_alternative_analysis.py` | 既存read_availabilityアダプタのkeyword互換修正だけ。ケース追加なし |
| T08 | `backend/tests/application/test_substitute_analysis.py` | 既存アダプタ/旧呼出形の互換修正だけ。ケース追加なし |
| T09 | `frontend/src/features/investigation/InfrastructureSupplyState.test.tsx`（新規） | C21〜22の2件。見た目の網羅・全文一致は試験しない |

既存アダプタの所在はread_availabilityの定義/呼出を検索して確認した。新規parametrizeの展開数を22に固定し、関数数で少なく見せない。既存ケース削除・skip追加・安全条件の弱体化はしない。予期しないケース増があれば先に件数と理由を報告する。

### 設計・操作・履歴文書：10

| ID | パス | 目的 |
|---|---|---|
| D01 | `docs/design/alternative-power-dependency-plan.md` | 本計画と承認範囲 |
| D02 | `docs/design/data-model.md` | 新表・登録時刻/版・欠落の意味 |
| D03 | `docs/requirements/domain-model.md` | 資源の登録供給状態の三値評価。Process等のUNKNOWNは維持 |
| D04 | `docs/requirements/access-control.md` | 参照は従来の資源Read権限、状態の製品更新は禁止。新しい変更権限なし |
| D05 | `docs/implementation-design/api-tools.md` | 既存Read出力/Evidenceへの追加項目と時刻の意味。新しい書込経路なし |
| D06 | `docs/requirements/acceptance-criteria.md` | F2の供給状態・依存・非誤判定・Evidence・seedの受入を記載 |
| D07 | `docs/demo/scenario1.md` | 架空の初期状態、専用環境での検証、公開済みGraphへの適用制限 |
| D08 | `docs/roadmap.md` | B採用・計画承認待ち、F3と任意タスクの区別 |
| D09 | `docs/roadmap-gantt.svg` | Bの2〜3.5日枠、工程色の凡例、任意タスクを期間未確定の独立行で表示 |
| D10 | `docs/history/2026-10-26-alternative-power-investigation.md` | AからBへの決定、実測/未実施、後の結果・残存制約を追記 |

## 3. 状態表・migration・初期seed

新表`infrastructure_supply_state`を提案する。資源マスターと状態のversionを混同しない。

| 列 | 契約 |
|---|---|
| infrastructure_resource_id | UUID PK/FK。資源1件につき状態レコード最大1件 |
| supply_state | NOT NULL、AVAILABLE / UNAVAILABLE / UNKNOWNだけをCHECK |
| version | 正のBIGINT、初期値1。Bでは製品経路から変更しない |
| registered_at | TIMESTAMPTZ。初回INSERT時のDB登録時刻。再投入で書き換えない |
| source | 初期条件の出典を示すNOT NULLの登録文字列。デモの仮定と明記 |

migration 014は新表の作成のみ。001〜013のchecksum/既存データ、保存済みSnapshot v1〜v5、承認・履歴・Graphのactive_generationを変更しない。既存資源へ既定AVAILABLEや架空の状態行を挿入しない。状態行がない資源の読取結果はUNKNOWN（record_reference/version/registered_atなし、欠落を明記）。

供給状態の表にはquery/runtimeともSELECTのみ。既存role未分離環境の設定を今回こっそり修正しない。検証専用環境では既存のrole構成に従って分離し、管理者資格情報はmigration/初期投入だけに使う。DB ownerによる管理権限まで消すものではなく、管理SQLの製品公開はしない。

JSON v1は従来通り受理し、供給状態がないまま扱う。v2は`infrastructure_states`配列を明示し、各要素はresource_code / supply_state / sourceを持つ。登録時刻とversionを利用者のJSONから推測/上書きせずDB側で初期確定する。配列は従来と同じ有界・重複/参照/余計なフィールドの検査を行う。

初期seedは既存の排他lockと単一transactionを使う。

1. 初期投入可能な未公開Graphにだけ新しい供給状態・関係をINSERTする。
2. 既存状態が同じID・状態・出典なら無変更で保持。version/registered_atも保持し、偽の業務履歴を作らない。
3. 状態または出典が違えばSeedConflict。先に挿入した別の辺/状態も含めて全体rollbackする。
4. 公開済みGraphへの新規辺・状態追加は拒否する。seedを状態変更コマンドや既存データの修復へ転用しない。

## 4. 取得・三値判定・Evidence・表示

接続は`GraphStateReader.read_availability → core_readsの一括SELECT → observe_availability → evaluate_substitute_candidate → 既存required_availability → 代替/SPOF Evidence`。PGの同一statementで設備/作業/資源状態と読取時刻を取得する。型付きID、enum、version、日時を検証し、取得失敗やアダプタ不正はUNKNOWNへの正常化で隠さない。

M-208自身と他の条件が正常、現在時点で探索が完全な場合の受入は次のとおり。

| R-02の登録供給状態 | M-208の代替利用可能性 |
|---|---|
| AVAILABLE | AVAILABLE |
| UNAVAILABLE | UNAVAILABLE |
| UNKNOWN/状態行なし | UNKNOWN |
| 取得失敗 | エラー、AVAILABLEを公開しない |

探索不完全や過去の実状態を尋ねる場合はUNKNOWNを維持する。UNAVAILABLE/UNKNOWNをAVAILABLEとして表示しない。供給が可能でもM-208自身がSTOPPEDならUNAVAILABLE。構造上の候補名が残る場合も利用不可/不明を同じ塊で示し、能力充足だけで『吸収できる見込み』を出さない。

追加する`current_resource_states`の各根拠は資源ID・supply_state・version・registered_at・sourceと`record_reference`（資源ID＋状態version）を持つ。`state_versions`は型付きInfrastructureResourceの状態versionを指し、マスターversionは別の値として維持する。

**registered_atは初期登録時刻、既存のstate_observed_at/observed_atはPGで読んだ時刻。どちらも現物の通電を測定した時刻ではない。** Graph世代・as_of・経路・completeの既存意味を維持し、現在状態を過去へ推定しない。欠落は記録参照/版を捏造せず明示する。

既存get_infrastructure_resourceはマスター項目を維持し、追加のregistered_supply_stateに状態と記録参照を返す。追加情報にも同じSELECTのobserved_atを含め（Envelope Evidenceの読取時刻と同じ）、UIはそのRead内の登録時刻と読取時刻を対にして示す。別のGraph読取の時刻を混ぜない。新しいHTTP経路・要求フィールドは作らない。新情報は既存資源Readと同じ閲覧権限で扱う案を正本へ記載する。

Frontendは既存の選択項目欄で、型付きの資源IDに対応する『登録上の供給状態』『初期条件の出典・版』『登録/読取時刻』を読取表示する。設備と資源が同じUUIDでも混同しない。Graphの辺・名称は既存描画を使い、入力/選択パネル・状態変更ボタン・質問観点を増やさない。

## 5. 公開済みGraphを含む適用方法

- **今回の計画作業**：既存5173/5174、API、DB、seed、認証、volumeを一切変更しない。
- **承認後の実装検証**：既存test Compose/DB隔離fixtureを使い、三値ごとに独立した初期データの使い捨てDBを直列で検証する。前の条件をUPDATEして使い回さない。Neo4jも専用の検証用であり、既存Graphを使わない。同じDB/Neo4jを使うsuiteを同時実行しない。
- **公開済みGraphへのmigration互換検査**：独立した旧版DB・公開Graphを作ってから014だけを適用する。既存レコード/Graph世代を保持し、未登録状態はUNKNOWN。新seedの追加を拒否して全体rollbackすることを確認する。
- **F2デモの新構成を使う場合**：既存デモをその場で再seedせず、別プロジェクト/別DB・volume・未使用ポートを用意し、migration→role設定→v2初期seed→初回Rebuild→CURRENT確認→Readの順に構成する。R-02は初期条件としてAVAILABLEを登録する。
- 実際に検証環境/新しいブラウザURLを作る操作は、実装承認後、名称・認証・ポート・負荷・片付けを具体化してから行う。既存ポートの切替、既存volume破棄、稼働DBへの変更、直接SQLによる本番状態の変更は承認に含めない。既存の手元imageを再利用し、新しいimageのbuild/pull/pruneはしない。

## 6. 追加自動試験：22ケース（Backend20・Frontend2）

以下のC01〜22だけを追加する。既存アダプタの互換修正でケース数を増やさず、既存回帰は別途維持する。parametrizeを用いる場合も展開後で22。必要な検証が増えたら、無断追加や件数合わせの省略をせず理由・追加件数を報告する。

| ID | 層/ファイル | 固定する条件・期待 / 防ぐ失敗 |
|---|---|---|
| C01 | Domain/T01 | M-208相当と必須資源がAVAILABLE→AVAILABLE。供給状態が取得/評価へ接続されない失敗 |
| C02 | Domain/T01 | 必須資源UNAVAILABLE→候補UNAVAILABLE。稼働中の候補を優先して電源停止を無視する失敗 |
| C03 | Domain/T01 | 必須資源UNKNOWN→UNKNOWN。不明を利用可能とする失敗 |
| C04 | Domain/T01 | 資源AVAILABLE、候補自身STOPPED→UNAVAILABLE。電源だけで候補を利用可能にする失敗 |
| C05 | Domain/T01 | 既知値はAVAILABLEでも探索不完全→UNKNOWN。未取得の必須条件を免除する失敗 |
| C06 | Domain/T01 | 過去as_ofでは現在AVAILABLEを流用しない。過去の供給状態を捏造する失敗 |
| C07 | DB/Read/T02 | 同一SELECTで設備/資源ID・状態version・出典を照合し、固定した過去registered_atを保ち読取時刻と区別。ID/版/時刻の混同 |
| C08 | DB/Read/T02 | 資源は存在し状態行なし→UNKNOWN＋欠落表示、架空の版/根拠を作らない |
| C09 | DB/Read/T02 | 資源状態の取得障害→失敗。欠落/初期AVAILABLEへフォールバックしない |
| C10 | DB/Read/T02 | 異なる資源IDの観測結果→拒否。別設備・別資源の状態を流用しない |
| C11 | DB/Read/T02 | 不正な供給状態enum→拒否。設備のRUNNING等を供給状態として受理しない |
| C12 | Seed/T03 | 同一v2の再投入で状態・version・registered_at・既存行・業務履歴が無変更 |
| C13 | Seed/T03 | 異なる供給状態の再投入を拒否し、先行した追加も全体rollback |
| C14 | Migration/Seed/T03 | v1 DBへ014を追加しても既存行/Graph世代を保持。旧v1 JSONが読め、状態はUNKNOWN。旧migrationの書換えやAVAILABLE補完を防ぐ |
| C15 | Seed/T03 | 公開済みGraphにv2の新規辺/状態を追加しようとすると拒否/全体rollback。既存seedの初期投入制限を回避しない |
| C16 | DB権限/T04 | query roleはSELECT可、書込/DDL権限なし、実UPDATE拒否。readonly transactionだけへの依存を防ぐ |
| C17 | DB権限/T04 | runtime roleも新表SELECTだけ、書込/DDL権限なし、実UPDATE拒否。既存のruntime更新権限の波及を防ぐ |
| C18 | 実DB/Graph/API/T05 | R-02 UNAVAILABLE、M-208 RUNNINGでもAPIの候補availabilityがUNAVAILABLE。Evidenceの根拠/versionが初期レコードと一致 |
| C19 | 実DB/Graph/API/T05 | R-02 UNKNOWNならAPIの候補availabilityもUNKNOWN。構造成立を利用可能へ読み替えない |
| C20 | 実DB/Graph/SPOF/T06 | 同じ資源状態がSPOF評価/Evidenceにも使われ、代替APIだけを直す不整合を防ぐ |
| C21 | Frontend/T09 | 資源の登録供給状態と出典・版・登録/読取時刻を読取表示し、同UUIDの設備状態と混同しない |
| C22 | Frontend/T09 | 候補の能力充足・自身RUNNINGがあっても、供給不可の判定を上書きして利用可能/吸収見込みを表示しない |

C16/C17は職務数×SQL全直積を作るのではなく、DB roleごとに実際のSELECT、全更新/DDL権限の検査、実UPDATE拒否を検証する各1ケース。C13は単一の不一致seedについて原子性を検証し、別の意味の失敗を一件に隠すための入力ループを作らない。

20件を超える根拠：純粋な三値6、実DB読取5、初期投入/互換4、DB権限2、API2、SPOF1、表示2は異なる失敗箇所。権限や実DBの原子性をformatterのfake試験で代替できない。pairwiseは不要な直積回避の原則として使い、今回の22は同値分割・境界・重要な相互作用を明示選定した。実装前の承認対象はこの22件。

既存のGraph/認可/承認/実行/質問欄の回帰は維持し、BackendはDocker内、Frontendは必要最小限のチェックで確認する。新しい実モデル評価はない。承認後の手動確認案は、各独立初期DBの実API ReadでAVAILABLE/UNAVAILABLE/UNKNOWNを各3回（計9要求）と、専用Frontendで依存辺/読取表示/代替判定を確認する。これは自動22ケースと別の確認方法で、今回実行していない。所要時間/資源/認証は環境の実行計画とともに提示する。

## 7. 見積もり・残存リスク・停止条件

製品/データ13＋試験9＋文書10＝32ファイル。新規自動試験22、2〜3.5作業日（DB/Read/三値0.75〜1.25、初期seed/Evidence/表示0.5〜0.75、試験/API/ブラウザ/CI/記録0.75〜1.5）。レビュー/実行承認待ちとF3は含めない。単一PRで実装と検証を完了し、mergeは開発者が行う。

残存リスクは、初期状態を実測と誤認すること、旧公開Graphへ新seedを適用できないこと、Bではデモ中に供給状態を画面で変更できないこと、既存Read出力の追加項目に対する呼出元互換。時刻・出典の明示、初期seed制約、独立DB検証、既存回帰で確認する。管理者権限によるDB操作まで物理的に不可能とは主張しない。

正確な追加case数が22を超える、変更ファイルが32を超える、3.5日を超える追加作業が必要、または新しい状態変更経路/サービス/モデルが必要と分かったら、理由・差分・工数を報告して承認前に進めない。件数合わせで安全性検証を削らない。

## 8. 任意の後続：承認付き供給状態変更（未採用）

A案は必須の残作業から外し、必要性が出た場合に改めて採否を判断する任意項目O-F2-WRITEとして記録する。依頼者/承認者の権限、自己承認、Snapshot、version競合、再送/原子性、UI・HTTP契約をその時点で承認する。現在の推奨権限案を確定仕様として継承しない。

Bの状態表・Read・三値評価・Evidence・表示・検査は将来再利用できる。仮のApproval/履歴を作らず、登録データと版から接続する。任意項目はガントへ採否未定の独立行で示し、期間バーや確定PR数へ加えない。既定の残計画はF2→F3の2 PRのまま。F3のstashは保持する。

## 9. 今回の区切り

今回は本計画とロードマップ/ガント/履歴の文書更新のみ。製品コード・JSON・API・UI・DB・seed・認証・既存環境を変更せず、手動試験・モデル評価は実行しない。開発者の追加指示に従い文書をPR #278へcommit/pushする。pushで起動する既存CIは文書差分の対象判定/既存チェックとして区別し、新規22ケースや製品実装の検証とは報告しない。計画を報告したら停止し、実装承認を待つ。

## 実装承認と検証段階（918ddd7に対する承認）

開発者は32ファイル（製品・データ13／試験9／文書10）、追加22ケース（Backend20／Frontend2）を承認した。B案の実装と自動・既存回帰検証を進める。直接API9要求は別途、独立環境の名称・ポート・認証・資源・片付け方針を提示して承認を得るまで行わない。既存5173/5174は変更しない。Draftを維持し、mergeは開発者が判断する。

### 独立環境の実行案（未実施・別承認待ち）

- 名称：`linescope-f2-api-check`。本作業専有のDocker networkとtmpfsのPostgreSQL / Neo4jを作り、三状態を順次、独立した初期DB・初回Graph Rebuildで用意する。共有デモのDB・volume・接続設定を使用しない。
- ポート：APIは`127.0.0.1:8178`、Frontendは`127.0.0.1:5178`。DB / Neo4jのポートはhostへ公開しない。使用中なら停止して報告し、勝手に別サービスを止めない。
- 認証：当該環境だけの一時manager tokenを生成し、既存認証をコピー・変更しない。資格情報は公開記録へ保存しない。業務承認・実行はしない。
- データ：初期JSONのR-02状態だけを各AVAILABLE / UNAVAILABLE / UNKNOWNへ設定し、M-208はRUNNING、共通必須電源辺を維持する。製品seedの値変更や既存環境への再seedは行わない。
- 直接API：各状態で`POST /agent`の明示`find_alternative_paths`を3回、合計9要求。候補M-208の構造成立、三値利用可能性、R-02の根拠ID・version・登録時刻と読取時刻を照合する。期待は順にAVAILABLE / UNAVAILABLE / UNKNOWN。同一状態の3回で登録時刻・versionが不変であることを確認する。
- ブラウザ：同じ専用Frontendで上流Graphの共通電源辺、資源の読取専用表示、利用不可・不明の候補表示を確認する。画面の通常Readは9件の定型API検証とは別に記録する。既存9観点・質問欄の設計を変更しない。
- 資源：既存imageを再利用しbuild/pullしない。GPU・実モデルは使用しない。API最大2 CPU/1GiB、PostgreSQL1GiB、Neo4j768MiB、Frontend256MiB、ブラウザ1GiBを上限目安とする（並列モデル評価なし）。初期化・画面確認・片付け込み10〜20分見込み、保証時間ではない。
- 片付け：本作業専有のcontainer/network/tmpfsと一時token・初期データを削除する。共有container・image・volumeを削除せず、pruneもしない。5173/5174のcontainer ID・公開ポート・volumeが前後一致することを確認する。最新Frontendを継続公開する必要があれば、使い捨て検証環境との扱いを別途確認する。

自動試験のTestClientによるHTTP確認と、上記独立HTTPサーバへの9要求は別の検証である。前者の成功を後者の実施と数えない。

### 回帰で判明した計画上限超過（未変更・承認を求める差分）

Backend全4113ケースは4101成功・11失敗・1skip（389.92秒）。追加20ケースはすべて成功し、失敗は既存回帰。Frontendは追加2を含む78成功。追加22ケースと既存回帰を区別する。

新規migrationの一覧と、既存資源Readの追加項目を固定期待値へ反映する互換修正が、次の6ファイルに必要である。製品の範囲・API要求・試験ケース数を増やさず、既存のassertionを更新する案。**承認32→38ファイルとなるため、これらは未変更で停止する。**

| 追加変更案 | 失敗数 | 必要な修正 |
|---|---:|---|
| `backend/tests/application/test_reads.py` | 6 | 全4職務の資源Read・native型保持の期待に供給状態を追加。SQL bind試験はUUIDと固定JSONキーのbindを区別し、値のSQL埋込禁止を維持 |
| `backend/tests/graph/test_projection_storage.py` | 1 | migration014を期待一覧へ追加。既存要求・Outboxの不変検証を維持 |
| `backend/tests/persistence/test_business_schema.py` | 1 | 同上、既存業務行の保持を維持 |
| `backend/tests/persistence/test_execution_history_schema.py` | 1 | 同上、実行履歴を捏造しない検証を維持 |
| `backend/tests/persistence/test_update_request_schema.py` | 1 | 同上、既存要求を保持する検証を維持 |
| `backend/tests/test_foundation.py` | 1 | 同上、並行migration一回適用・checksum拒否の検証を維持 |

追加ケースは0、合計22のまま。追加工数は互換修正・全件再実行・CIを含め0.25作業日程度を見込む。これらを削除・skip・弱体化して成功にしない。既存Readの追加契約を取り下げたり、migrationを隠したりしてファイル数だけを守らない。今回の計画時に横断的な固定期待値を拾えていなかった点を記録する。

Backend/Frontend lint・型・整形・buildは成功。CI、独立HTTP9要求、製品ブラウザ確認は未実施。Backendのopt-in実モデル1件skipは従来どおりで、F2でモデルは使用しない。追加承認前に6ファイルを変更しない。
