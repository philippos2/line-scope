# 正式デモ環境への昇格・旧環境の停止

## 目的・承認・範囲

#278 merge後、開発者は文書整理に先立ち、最新版を正式デモへ昇格・置換し、旧環境を不要とする指示を出した。完了後に別PRを作成し、mergeは開発者が行う。F3のstashは適用せず、製品コード・業務規則を変更しない。環境の接続先・起動設定と必要最小限の履歴/ロードマップだけを更新する。

backend-transaction-review / backend-secure-coding / backend-verification / frontend-verificationを適用し、停止時に失われるtmpfsと永続volumeを区別した。#278の隔離環境をそのままポート変更するだけでは保存性がないため、PostgreSQLを退避・復元し、Neo4jは正本から再構築する。

## 実施内容

- mainを#278のSquash merge `55965a327366be4300b40d3e3ed8f595d9e6c91a`へff-only更新し、`chore/promote-demo-environment`へ分離。履歴書換え・force pushなし。
- 正式projectは`linescope-demo`、Frontend5173/API8002。既存imageを再利用し、固定source snapshotをread-only mountする`compose.demo.yaml`を追加。通常Compose・Frontend・RAGを重ねる。source snapshotはmainから作成し、branch作業中の未commitコードを配備しない。
- `.env.demo`をmode0600で生成。DBのadmin/query/runtime/projectionを分離し、既存の認証identityと5178用tokenを維持する。秘密値は公開記録へ保存しない。
- 古い呼出元・Projectionを止めてから、確認済みプレビューDBと旧5173/5174/browser-demoのDBを非公開ファイルへ退避。確認済みプレビューの正本を新しい永続PostgreSQLへ復元し、初期seedや状態UPDATEを行わない。旧5174の変更要求6件は旧DB退避へ保持し、新しい業務要求へ混在させない。
- 旧5174のみの参考文書metadata1件と本文、停止したQdrantの保存領域を新しい専用volumeへコピー。既存のembedding設定・digestを保持し、新モデル取得・GPU推論は行わない。
- migration検証/role付与後、既存のGraph管理処理でschemaを確認し、PostgreSQL正本からRebuildした。Graph generationは派生モデルとして更新され、業務行のversionや時刻を改変しない。
- 旧`linescope-scenario1`、`linescope-s1-availability-preview-20261019`、`linescope-f2-api-check`、`linescope-browser-demo`の全コンテナを停止。稼働デモは正式projectの6サービスへ統一。旧コンテナ/volumeと私有退避は保持し、削除やpruneは行わない。旧tmpfsの正本は停止前に退避・内容照合済み。

## 確認した範囲

| 確認 | 結果 |
|---|---|
| Compose設定 | 本マシンの私有envと既存imageで構成を展開・起動 |
| 正本データ | 設備・状態・関係・正式入力・要求/承認/履歴等の19テーブルで、件数と全行内容hashが移行元と一致 |
| 永続性 | PostgreSQL/Neo4j/QdrantとAPI/Projection/Frontendを再起動後、同じ19テーブルの一致とvolume mountを確認 |
| API・Graph | 正式APIでM-208の構造成立/AVAILABLE、R-02供給状態とEvidenceを確認。再起動後の3回も確認 |
| ブラウザ | 正式5173の実APIでM-204/M-208共通R-02、読取専用供給状態、代替提案・能力表示を確認。再起動後も再確認。応答置換なし、JS例外0 |
| 文書データ | 参考文書metadata1件・本文hash一致・Qdrant collectionの1 pointを保持。検索設定も移行 |
| 起動状態 | 正式6サービス稼働、旧projectは全停止。旧port5174/5178/8003/8178は閉鎖 |

起動直後の最初のAPI照合はpartialで候補一覧が空となり、検証スクリプトが停止した。APIログには約4689msのpartial応答が残る。後続の実API・ブラウザ・再起動後3回は完全なAVAILABLE結果で一致した。最初のpartial応答本文は保存できておらず、起動直後の負荷/探索制限が原因と断定しない。この初回を成功へ含めず、製品修正や制限の緩和は行わなかった。

## 未確認・維持事項

文書検索の実embedding推論、全質問/全更新/承認の実通し、他の供給状態の再検証は今回行っていない。#278の三値9要求・自動回帰とは区別する。新規自動ケースは追加しない。

正式接続先・起動方法は`docs/demo/environments.md`へ限定して記録する。デモ範囲の再整理はF3で開発者の相談結果を待つ。F3のstashと#276のarchiveは変更しない。環境切替PRのCI・PR引渡しは別途確認する。

環境一覧・ガントの実施行を更新し、SVGをHTMLへ埋め込んで描画と文字の収まりを確認した。native SVGの最初のスクリーンショットはtimeoutとなったため、XML/文字領域検査とHTML埋込描画で再確認した。製品試験の成功とは混同しない。
