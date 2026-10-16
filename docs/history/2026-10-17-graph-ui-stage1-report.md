# Graph中心UIの常設ブラウザ測定

source b73ed89、常設環境、実API・実DB・実LLM・実Embedding／Qdrant。全11段階が成功。全BSや全UIの受入を意味しない。

```json
{
  "result": "PASS",
  "scope": "PERSISTENT_UI_END_TO_END_REAL_SERVICES",
  "revision": "b73ed8984bb12bb8a38045f7d6bf6a51a2dc8b58",
  "stages": [
    {
      "stage": "login"
    },
    {
      "stage": "equipment-selected",
      "seconds": 16.7
    },
    {
      "stage": "state",
      "seconds": 5.8
    },
    {
      "stage": "impact",
      "reached": 6
    },
    {
      "stage": "upstream"
    },
    {
      "stage": "comparison-unknown"
    },
    {
      "stage": "evidence",
      "source": "QDRANT",
      "citations": 1
    },
    {
      "stage": "prepared",
      "update_request_id": "30fbdabb-2e8b-4ef1-9595-6570a9b6eadb"
    },
    {
      "stage": "approved"
    },
    {
      "stage": "executed"
    },
    {
      "stage": "recompared",
      "repair_total": "300000",
      "input_code": "UI-STORY-1792164087905"
    }
  ],
  "browser_errors": []
}
```

その後のCSSだけの修正は、同じ入口→実Graph→製品ノード選択を再実行し、強調されたpathのcomputed strokeが `rgb(240, 189, 102)` であることを確認した。機能の通し確認と表示修正後の確認を区別する。
