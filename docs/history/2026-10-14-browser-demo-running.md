# ブラウザ確認用の継続デモ環境

非正本の環境記録。開発者のブラウザ確認を優先し、Evidence表示追加は未着手。

- #234 merge後のmain ef36e0bに基づく画面を起動。
- Compose projectはlinescope-browser-demo、私有設定は.env.browser-demo。既存.envは保持。
- API 8000／Frontend 5173は127.0.0.1だけに公開。PG／Neo4jは専用volume。
- seed-demo-graphとrebuild-graphを実行し、projectionを起動。Graph CURRENTと比較案4件を実HTTPで確認。
- 接続tokenはGit管理外data/browser-demo/manager-token.txt、起動・停止案内はdata/browser-demo/start.txt。
- API比較はPARTIAL、費用／能力／安全入力はMOCK_FIXTURE。ローカルOllama model設定ありだが今回summaryはFALLBACK。実LLM文章生成の成功とは扱わない。
- 継続デモ用コンテナは削除しない。試験用使い捨て環境とは区別する。
- 次はEvidenceの読みやすい表示を継続する。Frontendテスト追加は必要最小限。
