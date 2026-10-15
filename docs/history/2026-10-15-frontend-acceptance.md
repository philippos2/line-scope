# Frontendの代表UI受入と仕上げ

非正本の作業履歴。仕様・受入条件はfrontend-console / requirements / api-tools / transaction-designを参照する。

## 指示・対象・再開地点

- 開発者の#240 merge報告をGitHubで確認。mainをa9502c9へff-only更新し、feat/frontend-acceptanceで着手。
- 紹介動画は後回し。PRは業務経路として確認できる単位にまとめ、資料から再開できる履歴を残す。
- 今回は代表経路の画面受入・必要な操作性修正・ガイドをまとめる。業務規則・API・DB・認可・transactionは変更しない。

## 変更と試験選定

- 調査領域へのskip link、入力・summaryを含むfocus表示、Snapshot取得後／失敗時のfocus移動を追加。
- Snapshot本体とTargetが確認できない応答から承認操作を有効化しない。
- 既存ブラウザフローへ実引用・keyboard・画面幅、他3カテゴリと拒否の4経路を追加。Role × State × Operationの直積を作らない。
- Unit追加4件：実効EXPIRED、明示拒否後の保存再取得、VERSION_CONFLICT後の操作停止、Execute確定後の現在観測とGET失敗。既存14＋追加4＝18件。
- ブラウザ試験のrequesterだけmanagerにし、別managerが承認。共通の最小検証fixtureは既定maintenanceを維持する。
- --embedding-model / --embedding-digestの両方を指定した場合だけ実Qdrant構成を追加。省略時は検索／Embeddingを明示モック、正本・管理本文・認可は実処理。実経路失敗時の自動fallbackなし。

## 確認範囲

| UI条件 | 検証する代表範囲 | 階層・保証の限界 |
|---|---|---|
| UI-01 | 比較問い合わせ→実PG / Neo4j→Graph / Object / Evidence | 実Chromium / HTTP。一般Read LLMの品質は別 |
| UI-02 | partial表示、サーバ実効EXPIREDの操作抑止 | ブラウザ代表結果＋固定応答Unit。全非CURRENTのブラウザ再実行ではない |
| UI-03 | MOCK_FIXTURE、費用、除外理由の表示 | 比較入力は仮置き。正式経済・能力・安全受入ではない |
| UI-04 | 設備状態・保全予定CREATE・生産予定UPDATE・依存CREATE、別人Approval / requester Execute、拒否 | 各カテゴリの代表。全CRUD / 割当 / 複数Targetの画面網羅ではない |
| UI-05 | 確定afterとcurrent / 観測時刻の分離、現在観測と後続GETの失敗 | 通常実行は実DB、障害応答のUIは固定応答Unit |
| UI-06 | cookie / storage、実引用に含むimg / onerror文字列の非実行 | 引用は試験文書。実設備の保全指示ではない |
| UI-07 | skip link、Graph一覧、Enter / Space / Tab、取得後・エラーのfocus、1440 / 768 / 390pxでページ全体の横overflowなし | Chromium代表操作。全browser・支援技術・全variantの包括的受入ではない |

## 実測結果

- Docker内のFrontend lint / typecheck / format / build、Unit18件PASS。
- 実Embeddingは導入済みembeddinggemma:latest（768次元、digest 85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1）。モデルの自動取得なし。
- 実Embedding / QdrantからPostgreSQL再認可・本文hash検証を経た引用を実APIとブラウザで確認。生成LLMは未使用。
- 4カテゴリ・拒否を含む最終実Embedding / QdrantブラウザフローPASS。専用container / volume / network・一時credentialを片付けた。390pxの引用画面も目視確認。
- モデル指定なしの明示モック経路もPASS。語句一致モックは「M-204の保全手順」を本文と照合できず、初回の引用確認が失敗した。問い合わせを両経路共通の「M-204 保全手順」に修正し、実Vector・明示モックを再実行してPASS。失敗工程名もログへ記録する。
- 最終ソースでDocker内Frontend check / Unit18件、変更Python2ファイルのruff check / format、git diff --check成功。実・モック両経路の専用container / volume / network / 一時credentialを削除済み。継続デモには反映していない。
- CIの件数・時間・片付けは確認後にPRへ追記する。

## 残件・次工程

- 代表デモ経路の受入を全業務完成と扱わない。正式入力はPO-B01〜08の判断が必要。全BS / Golden・一般LLM / 検索品質・運用復旧の正式受入は別。
- 全CRUD・設備割当・複数Target・要求置換・実障害注入を含む画面受入は未網羅。Backendの既存実DB試験を削除・弱体化しない。
- この工程のmerge後、開発者が実際に操作したフィードバックの修正を優先し、現スコープの一区切りを判定する。正式業務入力へ進む場合はPO判断の具体化から着手。紹介動画は着手しない。
