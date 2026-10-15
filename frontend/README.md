# LineScope Frontend

React / TypeScript / Viteで実APIへ接続するオペレーション画面です。Backendと同じリポジトリで管理し、Docker内で起動・buildします。

## 使える機能

- tokenで接続し、日本語の問い合わせとサーバの回答を表示する。
- 「設備を探す」から候補の設備名・コードを確認し、選択した設備の調査文を作る。送信は明示操作。
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

Tabで「調査領域へ移動」、EnterでボタンとGraphの一覧を操作できます。Snapshot取得後は見出し、エラー時はメッセージへフォーカスが移ります。

通常検証はlint・型チェック・format・buildです。自動テストは必要最小限とし、既存の`npm test`は任意実行です。主要操作は実ブラウザで確認します。使い捨て実API環境の確認には`python3 scripts/verify_frontend_flow.py`を使用できます。

[画面設計](../docs/design/frontend-console.md)、[roadmap](../docs/roadmap.md)、[開発・PR運用](../CONTRIBUTING.md)を参照してください。正式な業務仕様の入口は[deliverables](../docs/deliverables.md)です。

実Embedding / Qdrantを含む引用表示の確認は、ホストOllamaに導入済みのモデルと正確なdigestを指定します。モデルの自動取得は行いません。

```sh
python3 scripts/verify_frontend_flow.py --docker-group docker \
  --embedding-model embeddinggemma:latest \
  --embedding-digest '<導入済みモデルの64桁digest>'
```

指定なしの場合はEmbedding / 検索を明示的なモックにして、正本・本文検証・引用表示を確認します。指定ありの失敗をモックへ自動切替しません。いずれも専用の環境と試験文書を作成・削除し、継続デモへは反映しません。実LLMの回答品質、正式な費用・能力・安全入力、全BS / Goldenの受入とは区別します。

実モデルで設備候補検索を含むブラウザ確認をする場合は、導入済みモデルを指定します（自動取得なし）。指定しない既存フローは候補検索を実施しません。

```sh
python3 scripts/verify_frontend_flow.py --docker-group docker \
  --llm-model qwen3:30b-a3b-instruct-2507-q4_K_M
```
