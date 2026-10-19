# LineScope Frontend

React / TypeScript / Viteから実APIへ接続する設備調査画面です。設備を検索・選択すると、関係図、登録状態、推定損害額、代替候補を一画面で示します。設備検索と候補一覧は左ペインに常設し、上部6タブで共有します。要約帯の4項目と調査結果は、タブを往復しても保持します。入力訂正・承認付き変更の導線改修は後続Bで行います。

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

実APIの主経路3項目（表示幅・キーボード・遅延切替・全ノードと一覧の名称を含む）と、明示的な応答制御8項目（名称取得の失敗と再試行、能力入力0／複数、検索・下流・代替・比較・金額の失敗と再試行）のさらにタブ間の選択・図の位置保持と質問対象・原因別エラーを確認する2項目を加え、実文書検索・失敗・再試行の1項目も加え、計14項目を確認します。タブのスクロール中の固定表示も検査します。全項目で横overflowと通常表示の禁止語（「名称を確認」「名前を確認」を含む）を検査します。登録データを書き換えず、制御した補助応答を実バックエンドの受入結果と混同しません。利用可能・不可・不明の表示と能力の組み合わせは `AlternativeAssessment.test.tsx` の8件、取得の同時実行・上限・重複・再試行・中断は`labelLoader.test.ts`の1件で確認します。

現行の確認対象は[M-204停止とM-208代替候補のシナリオ](../docs/demo/scenario1.md)です。旧シナリオでM-208を停止・復旧させるブラウザ試験は廃止しています。実APIを使い、設備検索、関係図、損害額、代替候補、評価範囲、設備切替を確認します。

[画面設計](../docs/design/frontend-console.md)・[ロードマップ](../docs/roadmap.md)・[開発規則](../CONTRIBUTING.md)を参照してください。

比較タブは主画面から引き継いだ入力を最初から表示し、候補取得前でも確認・変更できます。入力詳細は日本語表示、返却値の原文は技術情報です。`ComparisonPresentation.test.tsx`の4件で、既知0・未算定・代替ゲート・製品別出典・インフラ名称の意味を検査します。

A2の参照ドロワーは、タブ下の「関係図を見る」「根拠を見る」から開きます。広い画面は右固定、1280px未満は全面の重ね表示です。取得済み情報を使い、開閉で再検索しません。確認用の `scripts/verify-reference-drawer-browser.mjs` は、上記と同じ私有envで実行します。実APIの読取を使う3項目で、要求対象の検査だけは明示した制御応答を使用し、登録データは変更しません。

工程Bでは、4カテゴリの検索・登録・訂正に登録済みの候補と日本時間の日時選択を追加しています。候補は参考値で、手入力を保持します。変更タブには無効理由と次の操作を表示し、起点を変えても保存要求は保持します。

書込を含む `scripts/verify-input-workflow-browser.mjs` は検証専用環境でのみ実行します。`LINESCOPE_BROWSER_APPROVER` と `LINESCOPE_BROWSER_ALLOW_WRITES=isolated-verification` が必要です。継続プレビューの5173・5174番への実行は拒否します。4カテゴリの変更準備・別担当者承認・元依頼者実行と、候補・待機中の操作の6項目を確認します。
