# LineScope Frontend

React / TypeScript / Viteから実APIへ接続する画面です。「工場トラブルと被害額」で対象設備と正式な損失根拠を選ぶと、React Flowの影響Graphと円／時間の推定を同時に表示します。ノードと経路、金額の内訳・出典から、比較・引用・承認付き変更・再調査へ進みます。従来の設備単位の調査、共通依存・代替・SPOFも利用できます。

## 起動と検証

全サービスの起動・私有設定・文書取込みは[起動ガイド](../docs/getting-started.md)を参照します。APIは同一originの `/api` 経由で呼び出し、認証tokenをbrowser storageへ保存しません。接続解除・切替で取得情報を消去します。

```sh
docker build --target development -t linescope-frontend-check frontend
docker run --rm linescope-frontend-check npm run check
```

2台トラブルの通し確認は `scripts/verify-incident-browser.mjs` を使用します。**正式入力の損失率とM-208の登録状態をUIから訂正・別manager承認・実行します。** 成功時は同じ承認付きUIで初期値へ戻し、変更履歴は保持します。失敗時は途中の確定状態が残るため、reportで停止工程と要求IDを確認してください。初期値に戻すことでversion・監査まで巻き戻す試験ではありません。書き込みを許可した専用デモ環境でのみ実行します。

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
  linescope-workflow-browser node scripts/verify-incident-browser.mjs
```

必要な事前条件は[2台トラブルの初期データ](../docs/demo/incident-story.md)、別のmanager 2名、設定済みLLM、実Embedding／Qdrantと取り込み済み参考文書です。調査・属性取得は明示操作を使い、自由生成の成功に依存させません。準備・承認・実行はAPIを裏から呼んで代行せず、実UIで操作します。画面・reportを保存し、未知／期間不一致、共有範囲の一回計上、Graph保持、更新後再取得、対象切替時の旧下書き消去、390／768／1600pxのoverflowを確認します。

設備単位の旧代表経路を確認する場合は `verify-workflow-browser.mjs` を使います。経済入力を1件登録・確定し、試験データは保持します。旧3ペイン向けの `verify_frontend_flow.py` は現行シナリオの受入と区別します。代表経路の成功から、全更新variant・全BS・任意自然文の成功を宣言しません。

[画面設計](../docs/design/frontend-console.md)・[ロードマップ](../docs/roadmap.md)・[開発規則](../CONTRIBUTING.md)を参照してください。
