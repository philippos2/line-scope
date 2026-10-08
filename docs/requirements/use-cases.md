# LineScope ユースケース詳細仕様書

## 1. 共通

- 対象を一意に特定する。
- 権限を確認する。
- 不足情報を推測しない。
- 更新はPrepare→Approval API→Execute APIの3段階とする。
- Graph分析はCURRENT時のみ実行する。

## 2. UC-01 設備状態確認
全ロール。設備特定→現在状態取得→回答。不在・曖昧なら更新なしで終了。

## 3. UC-02 設備履歴確認
全ロール。設備・期間特定→履歴取得→時系列回答。

## 4. UC-03 保全履歴確認
全ロール。設備または保全識別子→保全実績取得→回答。

## 5. UC-04 生産影響確認
保全・生産管理・工場管理。対象特定→Graph CURRENT確認→UC-16〜20の必要分析→根拠付き回答。

## 6. UC-05 設備状態更新
要求者: 現場・保全・工場管理。Prepare→Snapshot確認→承認→元要求者がExecute API→正本再確認。

## 7. UC-06 保全予定登録
要求者: 保全・工場管理。CREATE。plan_code等で重複検証。

## 8. UC-07 保全予定変更
要求者: 保全・工場管理。version一致を必須とする。

## 9. UC-08 保全結果登録
要求者: 保全・工場管理。record_codeを持つCREATE。

## 10. UC-09 生産運用情報変更
要求者: 生産管理・工場管理。
対象:
- planned_status
- planned_start
- planned_end
- Equipment割当集合

Equipment割当はProductionOperationEquipmentAssignmentを正本として同一UpdateRequest内で原子的に変更し、GraphのUSESをOutbox経由で更新する。

## 11. UC-10 更新後確認
COMPLETED後にPostgreSQL正本を再参照する。Graph更新を伴う場合、CURRENTになるまでGraph分析は正常結果を返さない。

## 12. UC-11 曖昧な更新要求
候補を提示し、同じcontext_idで利用者確認を受ける。Agentが任意選択しない。

## 13. UC-12 未承認更新
Execute APIはAPPROVEDでないUpdateRequestを拒否する。

## 14. UC-13 Snapshot変更
承認対象のtarget、operation、before、after、versionが変わった場合、ApprovalをINVALIDATEDとし再Prepareする。

## 15. UC-14 更新途中失敗
業務更新をROLLBACKする。技術的再試行可能障害では承認を再利用可能とし、version/業務ルール競合ではINVALIDATEDとする。

## 16. UC-15 重複実行
同一UpdateRequestまたはApprovalの再Executeで二重更新しない。COMPLETED済みなら既存結果を返す。

## 17. UC-16 下流影響伝播分析
影響方向をBFSで探索し、最短hopで直接/間接を分類する。上限到達時は部分結果と不完全性を返す。

## 18. UC-17 上流依存探索
上流探索方向をBFSで探索し、代表経路を返す。

## 19. UC-18 共通依存候補探索
複数対象の上流集合を比較し、共通要素と代表経路を候補として返す。

## 20. UC-19 代替経路探索
停止対象を除外した構造候補を探索し、PostgreSQL状態で実利用可能性を確認する。

## 21. UC-20 単一障害点候補探索
指定重要対象に対し必須経路・代替を評価する。探索打切り時は `INDETERMINATE`。

## 22. UC-21 依存関係登録・変更・無効化
要求者: 保全・生産管理・工場管理。承認者: 工場管理者。自己承認不可。
Prepare→Snapshot→Approval API→元要求者Execute API→共通Graph mutation lock→再検証→正本更新→履歴→Outbox→commit。

## 23. レビューで確定した補足

UC-10 / 15は確定afterと現在再参照を別フィールドで返し、別更新のversion差を示す。UC-13はSnapshotを編集せず、旧PENDING / APPROVEDをINVALIDATEDとして新規Prepareする。

UC-04 / 16〜20は保全・生産管理・工場管理のみ。UC-09の期間付き集合置換はdomain-model §15.2、UC-19 / 20の成立条件・利用可能性・過去分析は§15.1・15.3に従う。未承認要求は無期限だがapprove時に再検証する。Prepare結果IDは人が承認者へ渡し、通知機能を追加しない。
