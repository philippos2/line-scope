# Graphと判断・変更の連動：実ブラウザ報告

常設PostgreSQL／Neo4j／Qdrant／LLM／Embeddingを使用。2つの独立したブラウザsessionで依頼者と別承認者を操作。秘密情報は含めない。

```json
{
  "result": "PASS",
  "scope": "PERSISTENT_UI_END_TO_END_REAL_SERVICES",
  "revision": "88de7ee38f9fba9b77324c67b8ba08cacca20329",
  "stages": [
    {
      "stage": "login"
    },
    {
      "stage": "equipment-selected",
      "seconds": 5.4
    },
    {
      "stage": "state",
      "seconds": 11.2
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
      "update_request_id": "11b853e3-8c38-4a44-8c4d-89080068047c"
    },
    {
      "stage": "approved-in-separate-session"
    },
    {
      "stage": "executed"
    },
    {
      "stage": "graph-refreshed-after-execution"
    },
    {
      "stage": "recompared",
      "repair_total": "300000",
      "input_code": "UI-STORY-1792194825305"
    }
  ],
  "browser_errors": []
}
```
