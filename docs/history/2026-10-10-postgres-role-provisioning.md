# PostgreSQL管理・runtime・検索roleの分離

日付: 2026-10-10。開始点: 2fc0ea5（PR #90 merge後）。
ブランチ: feat/postgres-role-provisioning。POによるmergeを確認しmainをfast-forwardした。

## 決定・変更範囲

既存owner linescopeは管理・migration用として維持し、APIへ渡さない。linescope_runtime / linescope_queryを別LOGIN credentialとし、標準Composeが両接続を明示設定する。bootstrapとmigrationを同じ管理roleにまとめるのは専用の小規模デモDBにおける判断であり、管理roleまで非superuser化したとの主張はしない。

db_roles.pyの管理専用provisionはfixed role / table / privilegeを用い、migration lockと一transactionで権限を再適用する。既存row / schema / checksum / ownerは変更しない。管理CLI migrate-and-provisionはmigration後にGRANTを適用し、失敗ならAPI起動を止める。migrationとprovisionは別transactionなので、migrationだけ完了した場合は修正後に再実行する。

検索は既存検索対象10表のSELECTだけ。runtimeは必要なSELECT / INSERT / UPDATE、監査・成功履歴はappend-only、OutboxはSELECT / INSERT、Projection controlはSELECT。DELETE / TRUNCATE / DDL、要求・監査への検索roleのアクセスを拒否する。masterのFOR SHARE用にはruntimeへUPDATE(version)の限定権限が必要で、任意SQL・credential公開を許可する理由とはしない。

table-level REVOKEだけで列ACLが消えるとの前提を置かず、既存列ACLも除去する。未知future table / sequence / functionは自動公開せず、管理ownerのglobal / schema default privilegesを制限する。function PUBLIC EXECUTEはglobal defaultを除去する。既存同名roleのownership / membership / 特権属性は自動流用せず拒否する。共有DB用の汎用provisionではない。

passwordは生成済みの互いに異なる64桁hexだけを許可し、bound set_configと固定DO block内のPostgreSQL formatを使う。Python側のSQL補間・手動escapeは行わない。管理DDL / catalog照会のPostgreSQL固有例外であり、通常の新DBアクセスをRaw SQL標準へ戻す判断ではない。

## 既存環境と実装上の限界

upgrade_demo_env.pyはmode 0600の既存.envへ不足credentialを追記し、既存管理password・tokenを保持する。値の上書きやvolume削除はしない。runtime / 検索credentialを変える際は既存sessionの即時失効を仮定せず、API停止と再起動を管理手順とする。

実際のユーザーローカル.env・既存DB volumeにはこのturnで適用していない。使い捨てproject / private envで起動・初期投入・再適用を検証した。標準Compose以外の直接Python利用にはREAD_DSN未設定の互換動作が残る。readinessはruntime接続確認で検索接続の健康保証ではない。新workerの専用role・権限はworker実装時に別設計する。

## 検証

- 実LOGIN roleの専用33ケース成功。role属性、検索mutation / DDL / TEMP / private table拒否、runtime DDL / 履歴改変 / control更新 / 管理role昇格拒否、future table / sequence / function拒否、列ACL除去、特権role衝突拒否、provision rollback、CLIのsecret検証、private env upgradeを確認。
- 制限runtimeで保全予定Prepare → 人間Approve API → requester Execute API → replay成功。割当Prepare / Approval / Executeで履歴・Outbox保存成功。実際にOutbox INSERTをREVOKEした場合は業務値・履歴・Outbox・Approval消費を全rollbackし、権限復旧後に再実行成功。
- 全体回帰2243 passed / 1 skipped / 1 warning（152.10秒、exit code 0）は追加29ケースまでの時点。後半4ケースは最終の専用33ケースに含めて成功。最終差分の全体回帰はGitHub CIで確認する。既知Starlette警告と前回同様の終了時logging診断は別メモの課題として維持。
- Dockerの新規runtime build / migration / provision / API健康成功。管理サービスでseed後にprovisionを再実行してmigration適用0、設備2件保持。APIプロセス内で実current_userがruntime / queryであることとRead Toolの設備2件取得を確認。
- HTTP readiness成功。存在しない/tools/search_equipmentを試した404はAPI障害とは扱わず、正式に公開されていないTool HTTP経路を追加せず内部Read Toolで確認した。実LLM E2Eをこのsmokeで検証したとの主張はしない。
- ruff check / format --check（127ファイル）、git diff --check成功。初回の2ケースはfixtureの列名・role名を修正して再実行した。

正本の接続・GRANT・upgrade手順はoperations §14。新規起動・既存.env upgradeの入口だけREADMEへ追記し、全面README再構成は行わない。LogiScopeコードの再利用はない。

## 次工程

POのmerge後にmain更新。Read層からSQLAlchemy Core標準導入を小さく進める。重要write / lock / Snapshot / Outboxの意味は維持し、安全なRaw SQLを機械変換しない。Core、worker / Projection、ログ終了時診断は未完了で、SQL / DB policy全体・バックエンド全体の完了とは報告しない。
