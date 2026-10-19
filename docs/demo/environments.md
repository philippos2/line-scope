# ブラウザ確認環境

現在の確認先をこの表で区別する。過去の履歴にあるポートは当時の記録であり、現在の接続先を示さない。

| ブラウザ | Compose project | API | データ | UI |
|---|---|---|---|---|
| http://localhost:5174 | linescope-s1-availability-preview-20261019 | localhost:8003 | A案。M-204停止・M-208稼働中。R-02→M-204のみ必須供給 | A1＋A2＋B確認版（入力候補・日時選択・変更手続き）。左ペイン常設・上部6タブ・要約帯・比較の選択引継ぎ・質問対象の明示。実LLM・実Qdrant文書検索接続あり。右側上部タブをスクロール中も固定表示 |
| http://localhost:5173 | linescope-scenario1 | localhost:8002 | A案変更前。M-208は稼働中だがR-02への必須依存により利用可能性が不明 | 今回の修正前のUI。比較確認用に保持し、今回切り替えていない |

**今回の修正確認には5174番を使う。5173番の切替は開発依頼者への確認後に行う。** 5174番では従来の接続tokenも使用できる。秘密値は私有envから取得し、文書・Git・画面証拠へ記録しない。

旧二台停止project `linescope-incident-demo` は削除済みで、上記の5173番とは別物。`linescope-browser-demo` は既存の別projectで、今回起動・停止・再投入していない。

A案のデータ形式と初期投入は[scenario1.md](scenario1.md)、変更順序の記録は[ポートとUIの修正履歴](../history/2026-10-19-ui-availability-and-environments.md)を参照する。

## 5174番の文書検索

`compose.rag.yaml`を重ねた実Qdrant経路を使用する。API用read keyと管理用write keyは私有envで分離し、既存の`embeddinggemma:latest`をdigestと768次元で固定する。参考資料`docs/demo-documents/equipment-investigation.md`を`DEMO-EQUIPMENT-INVESTIGATION`第1版として登録済み。同じ版を再投入しない。

再起動時もRAG構成を外さない。イメージ・DB資格情報・volumeは再作成しない。

```sh
docker compose --env-file .env.scenario1-availability-preview \
  -p linescope-s1-availability-preview-20261019 \
  -f compose.yaml -f compose.frontend.yaml -f compose.rag.yaml \
  --profile frontend up -d --no-build --no-deps --wait qdrant api frontend
```

検索は「出典と経路」→「関連文書」で行う。検索対象、処理中、失敗と再試行、本文抜粋と出典を同じ領域に表示する。成功時は検索結果の見出しへフォーカスする。検索失敗で前の成功結果を消さない。
