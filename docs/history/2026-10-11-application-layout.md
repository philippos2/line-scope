# 業務サービス関連の配置整理

## 範囲

配置整理の第四段階。Prepare・Approval・Execute・Proposal保存・検索Tool・変更command等の16モジュールをbackend/src/linescope/applicationへ、直接サービスを検証する対応テスト35モジュールをbackend/tests/applicationへ移動する。HTTP/APIテストは現位置に残し、共有fixture・故障注入先も含めimportを更新する。旧パスの互換shimを追加しない。

今回もSQL、認可、transaction、locking、version validation、rollback、Snapshot、Audit/Outbox、状態遷移、API/Toolとテストassertの処理は変更しない。テストにはUnitと実DB Integrationの両方が含まれ、application package名を試験階層の名称と混同しない。

## 境界の現状と後続

ProposalStoreの保存・認可・状態解釈、サービス内SQL、HTTP /agent内の振り分けは既存のまま残す。application packageへの移動だけでこれらの責務分離が完成したとは扱わない。API/Agent等の配置整理を先に完了し、その後に境界改善を行う。

業務サービスはdomainの検証とpersistence / graphへ既存どおり依存する。import以外のAST比較と既存全体テストで挙動維持を確認し、CIでpackaged migrationsとCompose起動も確認する。DB/Graph試験を同じ試験DBで並行実行しない。

文書群とREADMEの全面整理はバックエンドが一段落してから。LogiScopeコードは再利用していない。

ローカル結果: Docker内全体2,474 passed / 1 skipped / 1 warning（185.17秒）。移動前と同じ件数。ruff check / format成功（156ファイル）。本体58モジュールのAST比較でimport以外の変更なし。
