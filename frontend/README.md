# LineScope Frontend

React / TypeScript / Viteで実APIへ接続するオペレーション画面です。Backendと同じリポジトリで管理し、Docker内で起動・buildします。

## 使える機能

- tokenで接続し、日本語の問い合わせとサーバの回答を表示する。
- 取得したObjectとCURRENTの下流Graph代表経路を選択・表示する。
- 修理・交換・継続・代替の比較、制約・不足情報・計算根拠を確認する。
- Evidenceの情報源・観測日時・Graph世代・入力version・原文を確認する。
- 明示Prepare、保存Snapshotの確認、承認・拒否、元requesterによるExecuteと結果確認。

左ペインは今回取得したObjectの一覧です。全設備の検索画面ではありません。GraphはAPIの代表経路の描画で、React Flowは導入していません。比較の費用・能力・安全条件はMOCK_FIXTUREです。「変更準備・承認・実行」を開き、変更指示または変更要求IDから操作できます。承認者には要求IDを渡し、接続解除・再接続後に保存Snapshotを読み直します。Execute後は確定afterと現在観測を分けて表示します。通信失敗時は書き込みを自動再送せず、保存状態を再取得してください。

## 起動

[起動ガイド](../docs/getting-started.md#ブラウザで操作する)に従ってBackendの資格情報・seed・Graphを準備してから実行します。

```sh
docker compose -f compose.yaml -f compose.frontend.yaml --profile frontend up --build -d frontend
```

`http://127.0.0.1:5173`を開き、サーバに登録されたtokenの値だけを貼り付けて接続します。初回接続後はHttpOnlyのセッションcookieでF5後も接続を復元します。接続切替・解除は上部の「接続設定」から行えます。

## 開発と検証

UIのcomponentは`src/app`／`src/features`、HTTP窓口は`src/api`に置きます。APIの値を表示する責務と、サーバの業務計算・認可を分離します。

```sh
docker build --target development -t linescope-frontend-check frontend
docker run --rm linescope-frontend-check npm run check
```

通常検証はlint・型チェック・format・buildです。自動テストは必要最小限とし、既存の`npm test`は任意実行です。主要操作は実ブラウザで確認します。使い捨て実API環境の確認には`python3 scripts/verify_frontend_flow.py`を使用できます。

[画面設計](../docs/design/frontend-console.md)、[roadmap](../docs/roadmap.md)、[開発・PR運用](../CONTRIBUTING.md)を参照してください。正式な業務仕様の入口は[deliverables](../docs/deliverables.md)です。
