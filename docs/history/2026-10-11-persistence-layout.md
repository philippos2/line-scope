# Persistence関連コード・テストの配置整理

## 範囲

配置整理の第二段階。database、db_roles、core_*の11モジュールをbackend/src/linescope/persistenceへ、Coreクエリ・実role・検索接続の5テストモジュールをbackend/tests/persistenceへ移動する。呼出側、root conftest、故障注入先のimportを更新する。旧パスの再exportや互換shimは追加しない。

migrationの配置とimportlib.resourcesのlinescope/migrations参照は維持する。SQL/Cypher、transaction所有者、locking、rollback、認可、Snapshot、Audit/Outbox、DB roleの権限とAPI/Tool契約は変更しない。今回も配置整理であり、サービス側の責務分離や依存反転の変更は後続。

## 検証と後続

本体56モジュールのAST比較でimport以外の処理変更がないことを確認する。既存の全体試験で収集件数・DB role・rollback・version conflict・Graph連携を確認し、CIのpackaged migrationsとCompose起動確認も行う。テストは既存assertを保持する。共通の使い捨てDB fixtureとtests path設定を維持し、DB/Graph試験は並行実行しない。

残る業務サービス・純粋検証・API/Agentの配置を段階的に整理した後に、責務分離の改善へ進む。文書群とREADMEの全面整理はバックエンドが一段落してからとする。LogiScopeコードは再利用していない。

ローカル検証: 本体56モジュールのAST比較成功。全体初回は2,473 passed / 1 failed / 1 skipped / 1 warning（184.98秒）。失敗は移動したenv upgradeテストの相対パスだけであり、新階層へ修正後にPersistence全74件成功（7.83秒）。ruff check / format成功（152ファイル）。最終全体実行はCIで確認する。
