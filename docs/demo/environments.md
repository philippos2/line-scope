# 正式デモ環境

正式な接続先は **http://127.0.0.1:5173**。Compose projectは`linescope-demo`、APIは`127.0.0.1:8002`。#278をmergeしたmain `55965a327366be4300b40d3e3ed8f595d9e6c91a`の固定ソースを使用する。

| 接続先 | 現在の扱い |
|---|---|
| 5173 / API 8002 | 正式版。M-204/M-208の共通必須電源R-02、登録供給状態AVAILABLE、質問欄9観点 |

現在の操作対象は`linescope-demo`のみ。旧環境の停止・退避・移行の経緯は[正式デモ環境への切替履歴](../history/2026-10-26-demo-environment-promotion.md)を参照する。

## 起動・停止

本マシンの私有`.env.demo`と、通常Composeに重ねる`compose.demo.yaml`を使用する。DB/Neo4j/Qdrant/文書本文は専用の永続volume。ソースは`.env.demo`に指定された固定snapshotからread-onlyでmountし、作業ブランチ切替で正式版のコードを変更しない。使用imageは私有設定で指定した既存imageを再利用し、削除しない。

```sh
docker compose -p linescope-demo --env-file .env.demo \
  -f compose.yaml -f compose.frontend.yaml -f compose.rag.yaml -f compose.demo.yaml \
  --profile frontend up -d --no-build --pull never --wait api projection qdrant frontend
```

停止も同じ正式project・私有設定・Compose構成で行う。

```sh
docker compose -p linescope-demo --env-file .env.demo \
  -f compose.yaml -f compose.frontend.yaml -f compose.rag.yaml -f compose.demo.yaml \
  --profile frontend stop
```

通常の停止に`down --volumes`を使用しない。常駐serviceは`restart: unless-stopped`。DB portはhostへ公開しない。

`.env.demo`はGit管理外・mode0600。固定snapshotと既存imageはこのマシンで準備済みであり、別マシンで上記だけを実行できるという意味ではない。別マシンへの導入では、対応するsource snapshot・image・私有設定を用意する。

## 認証とデータ

正式環境の認証値は私有`.env.demo`の`LINESCOPE_USERS`、または本マシンの`.git/demo-runtime/access-token.txt`から取得し、Bearer token欄へ**値だけ**を貼り付ける。秘密値はGit・文書・画面証拠へ記録しない。API切替により以前のsession cookieは引き継がれないため、初回は再接続する。

業務データは正式環境の永続PostgreSQLに保存する。新たなseedや状態上書きは行わない。Neo4jはPostgreSQL正本から構築した派生モデルとして保持する。移行時の照合・退避の詳細は切替履歴を参照する。

参考文書`DEMO-EQUIPMENT-INVESTIGATION`第1版のmetadata・本文・Qdrant indexと検索設定を保持する。質問欄は#277で確定した9観点の定型照会で、LLM分類・生成は使用しない。文書検索のembedding推論を伴う再実行は今回未確認であり、metadata・本文・indexの保持確認と区別する。

切替・再起動・検証と既知の制約は[正式デモ環境への切替履歴](../history/2026-10-26-demo-environment-promotion.md)を参照する。本書の更新は接続先と運用に限定し、「やること／やらないこと」の文書整理は別のF3で行う。
