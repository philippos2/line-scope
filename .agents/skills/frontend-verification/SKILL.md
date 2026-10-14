---
name: frontend-verification
description: LineScopeのFrontend変更をDocker内のlint・型チェック・buildと必要最小限のブラウザ確認で検証し、CI結果を確認してPRを引き渡すときに使う。
---

# Frontend verification

[Frontend案内](../../../frontend/README.md)、[起動ガイド](../../../docs/getting-started.md)、[CONTRIBUTING](../../../CONTRIBUTING.md)を参照する。

## 必要な検証を選ぶ

Frontendの自動テストは必要最小限とし、省略を許容する。ケース数や見た目の網羅性を成果にしない。通常はDocker内の`npm run check`（lint・型・format・build）と主要操作の実ブラウザ確認を使う。既存`npm test`は具体的な必要性がある場合だけ実行する。

組み合わせテストが必要なら[test-design](../test-design/SKILL.md)を参照する。Frontendの検証を簡素にする方針を、BackendのSecurity・認可・原子性の検証を弱める理由にしない。

変更後のソースがimageへ入っていることを確認する。

```sh
docker build --target development -t linescope-frontend-check frontend
docker run --rm linescope-frontend-check npm run check
```

実APIとの通し確認が必要なら`python3 scripts/verify_frontend_flow.py --docker-group docker`を使う。Docker groupが不要な環境では引数を省く。使い捨て環境を作成・削除するscriptであり、開発者がブラウザで確認する継続デモとは区別する。単なる文言変更で全フローを無条件に繰り返さない。

実ブラウザでは、変更した主要操作、不明・部分結果・mockの表示、認証情報の扱いを確認する。実応答、stub、mockのどこを確認したかを明示する。Fixture成功を全業務受入や一般LLM品質の合格として扱わない。

## CIと引渡し

CI実行対象は[CONTRIBUTING](../../../CONTRIBUTING.md)と実workflowを確認する。Frontend単独変更のBackend省略が対象判定によるものか、集約checkが成功したかを確認する。CIログの実測結果をPRへ追記し、一時認証ファイル・この試験が所有する環境を片付ける。継続デモのvolumeや退避中stashを削除しない。

変更内容、実行した検証、未実施範囲、mock、既知の制限を報告する。確認・結果追記・片付け・clean treeを終えてから「CI確認・結果追記・片付けまで完了しました。mergeできます。」と案内する。
