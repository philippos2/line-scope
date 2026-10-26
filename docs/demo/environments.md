# 正式デモ環境

正式な接続先は **http://127.0.0.1:5173**。Compose projectは`linescope-demo`、APIは`127.0.0.1:8002`。#278をmergeしたmain `55965a327366be4300b40d3e3ed8f595d9e6c91a`の固定ソースを使用する。

| 接続先 | 現在の扱い |
|---|---|
| 5173 / API 8002 | 正式版。M-204/M-208の共通必須電源R-02、登録供給状態AVAILABLE、質問欄9観点 |
| 5174 / API 8003 | 旧確認環境。停止済み |
| 5178 / API 8178 | #278の隔離プレビュー。正式版へデータを移し、停止済み |

`linescope-scenario1`、`linescope-s1-availability-preview-20261019`、`linescope-f2-api-check`、`linescope-browser-demo`は停止済み。旧コンテナ・永続volume・非公開のDB退避を復旧用に保持する。`prune`や旧volumeの一括削除は行っていない。稼働しているデモは`linescope-demo`だけに統一する。

## 起動・停止

本マシンの私有`.env.demo`と、通常Composeに重ねる`compose.demo.yaml`を使用する。DB/Neo4j/Qdrant/文書本文は専用の永続volume。ソースは`.env.demo`に指定された固定snapshotからread-onlyでmountし、作業ブランチ切替で正式版のコードを変更しない。使用imageは既存のものを再利用するため、旧project名由来のimage名でも削除しない。

```sh
docker compose -p linescope-demo --env-file .env.demo \
  -f compose.yaml -f compose.frontend.yaml -f compose.rag.yaml -f compose.demo.yaml \
  --profile frontend up -d --no-build --pull never --wait api projection qdrant frontend
```

停止は同じ引数で`stop`。通常の停止に`down --volumes`を使用しない。常駐serviceは`restart: unless-stopped`。DB portはhostへ公開しない。

`.env.demo`はGit管理外・mode0600。固定snapshotと既存imageはこのマシンで準備済みであり、別マシンで上記だけを実行できるという意味ではない。別マシンへの導入では、対応するsource snapshot・image・私有設定を用意する。

## 認証とデータ

5178で使用した一時manager tokenを正式版でも使用できる。従来のデモの登録済み認証も保持している。値は私有`.env.demo`の`LINESCOPE_USERS`、または本マシンの`.git/demo-runtime/access-token.txt`から取得し、Bearer token欄へ**値だけ**を貼り付ける。秘密値はGit・文書・画面証拠へ記録しない。API切替により以前のsession cookieは引き継がれないため、初回は再接続する。

業務データは開発者が確認した5178を基準に復元し、19業務テーブルの件数・内容hashの一致を確認した。新たなseedや状態上書きは行わない。旧5174の変更要求6件等は旧DBの退避に保持し、新しい業務データへ混在させない。Neo4jはPostgreSQL正本から既存の管理Rebuildで再構築した。

旧5174の参考文書`DEMO-EQUIPMENT-INVESTIGATION`第1版、本文volume、Qdrant indexと検索設定も移した。新しいモデルの取得・実行はしていない。質問欄は#277で確定した9観点の定型照会で、LLM分類・生成は使用しない。文書検索のembedding推論を伴う再実行は今回未確認であり、metadata・本文・indexの保持確認と区別する。

切替・再起動・検証と既知の制約は[正式デモ環境への切替履歴](../history/2026-10-26-demo-environment-promotion.md)を参照する。本書の更新は接続先と運用に限定し、「やること／やらないこと」の文書整理は別のF3で行う。
