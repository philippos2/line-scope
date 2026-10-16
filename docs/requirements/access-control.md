# LineScope 権限・承認要件書

## 1. 前提

v1は単一工場であり、工場内のGraphノード単位秘匿は行わない。

認証済みuser_idとroleを権限根拠とし、利用者発話・LLM出力を権限根拠にしない。

## 2. ロール

- 製造現場担当者
- 設備保全担当者
- 生産管理担当者
- 工場管理者

## 3. 操作権限

| 対象 | 操作 | 現場 | 保全 | 生産管理 | 工場管理 |
|---|---|---:|---:|---:|---:|
| 設備・状態 | 参照 | 可 | 可 | 可 | 可 |
| 設備状態 | 更新要求 | 可 | 可 | 不可 | 可 |
| 設備状態 | 承認 | 不可 | 可 | 不可 | 可 |
| 保全 | 参照 | 可 | 可 | 可 | 可 |
| 保全 | 更新要求 | 不可 | 可 | 不可 | 可 |
| 保全 | 承認 | 不可 | 可 | 不可 | 可 |
| 生産運用 | 参照 | 可 | 可 | 可 | 可 |
| 生産運用 | 更新要求 | 不可 | 不可 | 可 | 可 |
| 生産運用 | 承認 | 不可 | 不可 | 可 | 可 |
| 依存関係 | 参照 | 可 | 可 | 可 | 可 |
| 依存関係 | 更新要求 | 不可 | 可 | 可 | 可 |
| 依存関係 | 承認 | 不可 | 不可 | 不可 | 可 |
| 経済情報 | 参照 | 不可 | 可 | 可 | 可 |
| 経済情報 | 更新要求 | 不可 | 不可 | 不可 | 可 |
| 経済情報 | 承認 | 不可 | 不可 | 不可 | 可 |
| 能力情報 | 参照 | 不可 | 可 | 可 | 可 |
| 能力情報 | 更新要求 | 不可 | 不可 | 不可 | 可 |
| 能力情報 | 承認 | 不可 | 不可 | 不可 | 可 |
| 安全情報 | 参照 | 不可 | 可 | 可 | 可 |
| 安全情報 | 更新要求 | 不可 | 不可 | 不可 | 可 |
| 安全情報 | 承認 | 不可 | 不可 | 不可 | 可 |

## 4. 自己承認

- 設備状態: 工場管理者のみ可
- 保全: 工場管理者のみ可
- 生産運用: 工場管理者のみ可
- 依存関係: 自己承認不可
- 経済情報・能力情報・安全情報: 自己承認不可

## 5. 実行権限

承認済みUpdateRequestをexecuteできるのは元のrequesterのみとする。

承認者やLLMがrequesterに代わってexecuteしない。

## 6. 承認期限

Approval成立から30分。

未承認要求には期限を設けない。期限判定はサーバ実時刻でexecute時に同期実施し、now >= expires_atで拒否する。approve再送で承認期限を延長しない。

## 7. 更新履歴閲覧

- 製造現場担当者: 自身が要求した更新のみ。ただし経済・能力・安全情報は要求者本人でも閲覧不可
- 設備保全担当者: 設備状態・保全・経済・能力・安全情報関連
- 生産管理担当者: 生産運用・経済・能力・安全情報関連
- 工場管理者: 全件

`GET /update-requests/{id}` も同じ閲覧境界に従う。ただしrequester本人は自身のUpdateRequestを参照できる。ECONOMIC_INPUT / CAPACITY_INPUT / SAFETY_INPUTは例外として、本人にも現在の対象情報閲覧権限を要求する。

## 8. 承認対象

承認者はサーバ保存のcanonical Snapshotを確認し、そのSnapshot Hashに対して承認する。

Agentが生成した説明文だけを承認対象としない。

## 9. レビューで確定した権限・期限

- 未承認要求は無期限。ただしapprove / execute時に対象version・Snapshot・業務制約を再検証し、変化した要求は失効する。
- 一UpdateRequestは単一業務カテゴリに限定する。同じカテゴリの複数Targetは可能。カテゴリはEQUIPMENT_STATE / MAINTENANCE / PRODUCTION_OPERATION / DEPENDENCY / ECONOMIC_INPUT / CAPACITY_INPUT / SAFETY_INPUT。AssignmentはPRODUCTION_OPERATIONであり、予定値と割当を同一要求で原子的に変更する。
- Execute時にrequesterの現在更新権限と、承認者の現在承認権限・自己承認規則を再検証する。必要権限が失われた承認はINVALIDATED。COMPLETEDの再送はowner確認と現在の要求閲覧権限の下で保存済み結果を返し、新規更新権限の喪失によって確定結果を書き換えない。
- Graph分析は保全・生産管理・工場管理のみ。現場担当者は依存関係の通常Readまで。UC-04 / UC-16〜20の全Graph Toolに同じ規則を適用し、ノード単位秘匿は導入しない。
- KnowledgeDocument access_classはv1ではFACTORY_INTERNALのみ。認証済み全ロールに許可し、未知のclassは拒否する。

## 10. Snapshot閲覧と承認待ちの発見

Prepare応答にUpdateRequest IDとApproval IDを返し、v1は人が承認者へ渡してGETで確認する。通知サービス・承認待ち一覧APIは追加しない。履歴検索は既存閲覧境界を守る。

単一カテゴリ承認者は既存閲覧範囲でSnapshot確認可能。承認APIは閲覧権限・全Target承認権限・自己承認規則を確認。異種カテゴリ混在は拒否し、既存閲覧権限を拡張しない。

## 11. 業務判断支援の追加情報

UC-BのGraph部分は既存のGraph分析権限に従う。経済情報は本書の経済情報の権限に従う。故障情報はrequirements §14.3 PO-B07で確定するまで許可を推測しない。Business ScenarioのActor記載は業務利用者の想定であり、新データの認可契約を代替しない。

Decision Packageは結論だけでなくEvidence、Tool Trace、計算入力を含めて認可する。新Toolを既存Read権限だけで自動公開しない。複数Targetは全Targetの権限・承認条件を満たさなければ全体拒否し、1 UpdateRequest = 1業務カテゴリを維持する。分析の実行可能案という表示はApprovalの成立を意味しない。

## 経済情報の権限

ECONOMIC_INPUTカテゴリはmanagerだけがPrepareでき、別のmanagerだけが承認・拒否できる。managerの自己承認例外は本カテゴリへ適用しない。Executeは元requesterかつ現在もmanager、承認者も現在managerであることが必要。承認期限・Snapshot hash・version・再送は既存共通契約を維持する。maintenance / production / managerは入力、出典、計算結果、保存要求、更新履歴を閲覧できる。floorには公開しない。能力・安全・故障情報への権限付与を意味しない。

COMPLETEDの再送は元requesterかつ現在の経済情報閲覧権限の下で保存済み結果を返す。現在の更新権限を失っただけで確定結果を書き換えず、floorへ変更された主体には結果を公開しない。

## 能力情報の権限

CAPACITY_INPUTの入力・出典・計算結果・Snapshot・保存要求・履歴はmaintenance / production / managerだけが閲覧できる。managerがPrepare、別managerが承認・拒否、元requesterかつ現在managerがExecuteする。承認者の現在manager権限も再検証する。floorには元requesterでも公開しない。COMPLETED再送は元requesterかつ現在の能力情報閲覧権限で許可する。安全・故障情報への権限付与ではない。

## 安全情報の権限

- SAFETY_INPUTの入力・観測・基準・出典・条件・判定結果・Snapshot・履歴はmaintenance / production / managerが閲覧する。
- managerが要求し、別managerが承認・拒否、元requesterかつ現在managerが確定する。承認者の現在manager権限も検証する。
- floorには元requesterでも公開しない。COMPLETED再送は元requesterかつ現在の安全情報閲覧権限で許可する。
- 稼働状態の記録は運転許可ではない。安全判定を理由に既存の状態登録を拒否しない。故障情報への権限付与は本契約に含めない。

## 対応計画・故障履歴の権限

| 操作・情報 | 許可 |
|---|---|
| MaintenanceInput検索・取得・計算・出典・Snapshot・履歴 | maintenance / production / manager |
| 登録・訂正Prepare | manager |
| Approval | 要求者と異なるmanager。実行時にも現在roleを再検証 |
| Execute | 元の要求者であり現在もmanager |
| floor | 上記情報・操作すべて拒否 |

既存MaintenancePlan / MaintenanceRecordの権限を変更しない。分類・損失など新情報を既存の広い読取経路へ混入させない。Agentは新情報の検索・取得のみ行う。
