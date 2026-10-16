# Graph UI 第2段階の実ブラウザ報告

実PostgreSQL／Neo4jと常設UIを使用。fixture APIの直接呼出しやmock応答は使用していない。認証情報は含めない。

```json
{
  "revision": "3aacbc813ef2142f42d5b48799332772ebd1ca11",
  "stages": [
    {
      "stage": "find_common_dependencies",
      "seconds": 0.107,
      "complete": true,
      "determination": null,
      "subjects": 6
    },
    {
      "stage": "find_alternative_paths",
      "seconds": 0.117,
      "complete": true,
      "determination": "DETERMINATE",
      "subjects": 2
    },
    {
      "stage": "find_single_point_failure_candidates",
      "seconds": 0.2,
      "complete": true,
      "determination": "DETERMINATE",
      "subjects": 12
    },
    {
      "stage": "node-attributes",
      "seconds": 0.073
    }
  ],
  "status": "PASS"
}
```
