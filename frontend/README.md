# LineScope Frontend

React / TypeScript / Viteから実APIへ接続する設備調査画面です。左の検索で起点を選び、関係図・登録状態・損害額・代替候補を調べます。上部6タブと要約帯で調査・比較・質問・根拠・入力・変更手続きを利用します。

## 起動と検証

継続プレビューは[環境一覧](../docs/demo/environments.md)、起動・私有設定は[起動ガイド](../docs/getting-started.md)を参照します。APIは同一originの`/api`へ接続し、tokenをbrowser storage・URL・ログへ保存しません。

lint・型・整形・buildは既存のdevelopment imageで`npm run check`を実行します。ソースがimageへ未反映なら、変更後のsrcとscriptsをmountして確認します。不要な別名imageのbuild・pullを繰り返しません。通常CIはvitestを実行しないため、必要なローカル単体の結果とは区別します。

### ブラウザ検証の保守方針

**常設の読取確認はシナリオ1の1本を保守します。** 旧UI専用の重複script群と旧環境構築ランナーは廃止し、変更履歴はgitに残します。臨時scriptの成功だけを常設検証の成功とは扱いません。

| script | 用途と実行条件 |
|---|---|
| `scripts/verify-scenario1-browser.mjs` | 常設の読取主経路1本。実APIで検索→関係図と名称→損害額200,000円／時間→M-208の代替能力60／80→比較→M-208への切替と入力確認の案内を確認。LLM・応答mock・環境作成・データ書込は使わない |
| `scripts/verify-reference-drawer-browser.mjs` | 関連変更時の補助確認。参照の開閉・位置・フォーカス等。常設主経路の代わりではない。要求対象だけ制御応答を使う |
| `scripts/verify-input-workflow-browser.mjs` | 許可した専用環境だけの補助確認。実Prepare→別manager承認→元requester実行。`LINESCOPE_BROWSER_APPROVER`と`LINESCOPE_BROWSER_ALLOW_WRITES=isolated-verification`が必要。5173・5174番は拒否する。実行前に環境・認証・操作を提示し明示許可を得る |

主経路の入力データは[シナリオ1](../docs/demo/scenario1.md)です。別の値へ更新した環境では、初期値の期待値を無断で書き換えず、専用環境か既存プレビューのデータ状態を確認します。実APIの成功を、実LLMの成功・全UIの受入・他カテゴリの実書込の成功へ拡大して報告しません。

私有env（0600）に`LINESCOPE_BROWSER_URL`・`LINESCOPE_BROWSER_TOKEN`・必要なら`LINESCOPE_BROWSER_OUTPUT=/out`を設定します。既存のbrowser-check imageを使い、**変更後のscriptを明示mount**します。

```sh
# BROWSER_IMAGEは手元の既存browser-check image名を指定する。
docker run --rm --pull never --network host --env-file /private/browser.env \
  -v "$PWD/frontend/scripts:/app/scripts:ro" \
  -v /private/results:/out \
  "$BROWSER_IMAGE" node scripts/verify-scenario1-browser.mjs
```

これはrepo直下からの実行例です。scriptは失敗時も`report.json`と画像を保存し、予期しない書込要求をブロックして失敗にします。補助2本は必要な変更時だけ実行し、実行しなければ未実行と記録します。新規の網羅的なブラウザ試験やCIへの自動追加は行いません。

## 画面と確認範囲

比較の起点と代替候補は別の設備です。起点自身の能力入力は代替用に使えません。比較用の入力を調査画面で取得できていないとき、右欄は「{起点}の比較用入力を確認する」と表示し、比較画面で登録状況を確認する入口にします。保全入力は未取得の可能性があるため、算定・能力が空というだけで比較リンクを無効にしません。使える入力がなければ登録・訂正が必要だと案内します。

[画面設計](../docs/design/frontend-console.md)・[ロードマップ](../docs/roadmap.md)・[開発規則](../CONTRIBUTING.md)を参照してください。
