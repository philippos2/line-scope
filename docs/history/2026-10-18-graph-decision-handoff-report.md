# Graph設備引継ぎと承認実行の実ブラウザ報告

常設の実PostgreSQL／Neo4j／Qdrant／LLM／Embeddingを使用。アプリソースは`abe9d1e`。tokenは含めない。

## Graphから別設備への引継ぎ

```json
{
  "revision": "abe9d1ef546cc9e11d2a4298ed91f9c53c3ecc2f",
  "stages": [
    {
      "stage": "find_common_dependencies",
      "seconds": 0.115,
      "complete": true,
      "determination": null,
      "subjects": 6
    },
    {
      "stage": "find_alternative_paths",
      "seconds": 0.101,
      "complete": true,
      "determination": "DETERMINATE",
      "subjects": 2
    },
    {
      "stage": "find_single_point_failure_candidates",
      "seconds": 0.149,
      "complete": true,
      "determination": "DETERMINATE",
      "subjects": 12
    },
    {
      "stage": "node-attributes",
      "seconds": 0.068
    },
    {
      "stage": "graph-equipment-to-comparison-and-input",
      "equipment_code": "M-208",
      "graph_origin": "M-204",
      "checked_selection": true
    },
    {
      "stage": "decision-target-switch-clears-old-selection",
      "graph_preserved": true
    }
  ],
  "status": "PASS"
}
```

## 承認・実行・再取得・再比較

```json
{
  "result": "PASS",
  "scope": "PERSISTENT_UI_END_TO_END_REAL_SERVICES",
  "revision": "abe9d1ef546cc9e11d2a4298ed91f9c53c3ecc2f",
  "stages": [
    {
      "stage": "login"
    },
    {
      "stage": "equipment-selected",
      "seconds": 6.3
    },
    {
      "stage": "state",
      "seconds": 6.1
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
      "update_request_id": "dbf7fab1-0fec-43da-8c22-56084feb36ef"
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
      "input_code": "UI-STORY-1792281000775"
    }
  ],
  "browser_errors": []
}
```
