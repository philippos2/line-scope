# LineScope Frontend

React / TypeScript / Viteから実APIへ接続する設備調査画面です。設備を検索・選択すると、関係図、登録状態、推定損害額、代替候補を一画面で示します。比較・出典・入力訂正・承認付き変更は下段の補助機能です。

## 起動と検証

全サービスの起動・私有設定・文書取込みは[起動ガイド](../docs/getting-started.md)を参照します。APIは同一originの `/api` 経由で呼び出し、認証tokenをbrowser storageへ保存しません。接続解除・切替で取得情報を消去します。

```sh
docker build --target development -t linescope-frontend-check frontend
docker run --rm linescope-frontend-check npm run check
```

現行の確認対象は[M-204停止とM-208代替候補のシナリオ](../docs/demo/scenario1.md)です。旧シナリオでM-208を停止・復旧させるブラウザ試験は廃止しています。実APIを使い、設備検索、関係図、損害額、代替候補、評価範囲、設備切替を確認します。

[画面設計](../docs/design/frontend-console.md)・[ロードマップ](../docs/roadmap.md)・[開発規則](../CONTRIBUTING.md)を参照してください。
