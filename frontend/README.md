# LineScope Frontend

React / TypeScript / Viteから実APIへ接続する設備調査画面です。設備を検索・選択すると、関係図、登録状態、推定損害額、代替候補を一画面で示します。比較・出典・入力訂正・承認付き変更は下段の補助機能です。

## 起動と検証

現在の継続プレビューと比較用環境は[環境一覧](../docs/demo/environments.md)で確認します。全サービスの起動・私有設定・文書取込みは[起動ガイド](../docs/getting-started.md)を参照します。APIは同一originの `/api` 経由で呼び出し、認証tokenをbrowser storageへ保存しません。接続解除・切替で取得情報を消去します。

```sh
docker build --target development -t linescope-frontend-check frontend
docker run --rm linescope-frontend-check npm run check
```

新UI用の読取検証は `scripts/verify-scenario1-browser.mjs` を使います。私有envに `LINESCOPE_BROWSER_URL` と `LINESCOPE_BROWSER_TOKEN`、必要に応じて `LINESCOPE_BROWSER_OUTPUT=/out` を設定します。

```sh
docker build --target browser-check -t linescope-scenario1-browser frontend
docker run --rm --network host --env-file /private/browser.env \
  -v /private/results:/out \
  linescope-scenario1-browser node scripts/verify-scenario1-browser.mjs
```

実APIの主経路3項目（表示幅・キーボード・遅延切替を含む）と、明示的な応答制御7項目（能力入力0／複数、検索・下流・代替・比較・金額の失敗と再試行）の計10項目を確認します。全項目で横overflowと通常表示の禁止語を検査します。登録データを書き換えず、制御した補助応答を実バックエンドの受入結果と混同しません。利用可能・不可・不明の表示と能力の組み合わせは `AlternativeAssessment.test.tsx` の8件で確認します。

現行の確認対象は[M-204停止とM-208代替候補のシナリオ](../docs/demo/scenario1.md)です。旧シナリオでM-208を停止・復旧させるブラウザ試験は廃止しています。実APIを使い、設備検索、関係図、損害額、代替候補、評価範囲、設備切替を確認します。

[画面設計](../docs/design/frontend-console.md)・[ロードマップ](../docs/roadmap.md)・[開発規則](../CONTRIBUTING.md)を参照してください。
