# LineScope Frontend

React / TypeScript / Viteから実APIへ接続する操作画面です。初期画面の「登録設備を表示して調査を始める」から対象を選び、中央の関係Graphで下流影響と上流依存を調べます。React Flowでノード選択・経路強調・拡大縮小・移動を行い、隣で属性と経路を確認します。比較・根拠・入力管理・変更承認のパネルを開いてもGraphは保持します。別の承認者は「変更・承認・実行」から変更要求IDを開きます。

## 起動と検証

全サービスの起動・私有設定・文書取込みは[起動ガイド](../docs/getting-started.md)を参照します。APIは同一originの `/api` 経由で呼び出し、認証tokenをbrowser storageへ保存しません。接続解除・切替で取得情報を消去します。

```sh
docker build --target development -t linescope-frontend-check frontend
docker run --rm linescope-frontend-check npm run check
```

業務の通し確認は `scripts/verify-workflow-browser.mjs` を使用します。**接続先へシナリオ用経済入力を1件登録・承認・実行します。** 書き込みを許可したデモ環境だけを対象にし、実業務環境へ実行しません。試験データは実DBに保存され、終了後も結果を確認できます。

私有のmode 0600のenvファイルへ以下を設定します。tokenは値だけを記載し、Git・URL・コマンド引数へ含めません。

- `LINESCOPE_BROWSER_URL`：対象Frontend URL
- `LINESCOPE_BROWSER_TOKEN`：依頼者のtoken
- `LINESCOPE_BROWSER_APPROVER_TOKEN`：別の承認者のtoken
- `LINESCOPE_BROWSER_OUTPUT`：container内の結果保存先（例 `/out/story`）
- `LINESCOPE_BROWSER_REVISION`：対象実装のGit revision

```sh
docker build --target browser-check -t linescope-workflow-browser frontend
docker run --rm --network host --env-file /private/browser.env \
  -v /private/results:/out \
  linescope-workflow-browser node scripts/verify-workflow-browser.mjs
```

必要な事前条件はM-204の設備・依存Graph、2名のmanager、導入済みTool callingモデル、実Embedding／Qdrantとデモ参考文書です。APIを裏から呼んで準備・承認・実行を代行せず、全工程をブラウザUIから操作します。スクリーンショットとreportを出力し、未選択費用の不明表示、実検索の引用、実行後の再比較、390／768／1440pxのoverflowも確認します。

旧3ペイン画面向けの `verify_frontend_flow.py` と機能別browser probeは旧操作の記録です。現行画面の通し受入には上記のworkflow probeを使用します。一般自然文の全件成功、全更新variant、全Business ScenarioのUI受入をこの1シナリオの成功から宣言しません。

[画面設計](../docs/design/frontend-console.md)・[ロードマップ](../docs/roadmap.md)・[開発規則](../CONTRIBUTING.md)を参照してください。
