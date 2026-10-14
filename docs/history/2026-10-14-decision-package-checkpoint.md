# Decision Packageの再開用チェックポイント

この記録は作業状況であり、業務仕様の正本ではない。仕様の入口は[deliverables](../deliverables.md)、残工程の全体像は[roadmap](../roadmap.md)を参照する。

## 確認済み

- PR #217はmerge済み。今回の基点はmain `327c4c6bf6fce897d8f038a512b879d6000beea5`。
- 対応案の決定論的計算と、実際の文書検索・検証済み引用をDecision Packageへ接続した。費用・能力・安全条件の入力は明示的なデモfixtureであり、正式な業務データではない。
- 現在の作業ブランチは `feat/decision-option-constraints`。この記録時点では変更は未commit・未push・未PR化。
- 現在の変更は `domain/demo_constraints.py`、`application/demo_decision.py`と対応するdomain/interfaceテスト。DBスキーマや更新トランザクションは変更していない。
- PostgreSQLの現在状態による継続案の除外と、mock安全条件による除外を別々の根拠で提示する。安全停止フラグがfalseでも、安全承認済みとは扱わない。
- 代替能力不足は「完全吸収できない」という制約であり、部分的な影響軽減まで不可能と断定しない。対応案の不足情報と残存リスクUNKNOWNを返し、最適案や実行権限を確定しない。

## 今回の検証

Docker内で最新の作業ツリーをmountして実行した。

```sh
pytest backend/tests/domain/test_demo_constraints.py backend/tests/domain/test_demo_comparison.py backend/tests/interfaces/test_demo_decision_flow.py -q -p no:cacheprovider
ruff check backend scripts
ruff format --check backend scripts
```

- 関連テスト23件成功、2.33秒。今回の追加は6件。
- lint成功、format確認は313ファイル成功。
- Starlette/httpx非推奨警告1件。終了時に `LineScope logging output failed` が出た。原因調査は未実施であり、正常動作確認済みとは扱わない。
- 今回の変更について全CI・実Ollama/Qdrantのsmoke再実行はまだ行っていない。

## 次の着手点

1. 対応案の制約・不足情報についてAPI出力と実環境smokeの検証範囲を確認する。
2. 日本語commit・PRを作成し、CIの実測結果を追記して、今回所有する使い捨て環境を片付ける。mergeは開発者の確認後。
3. 正式業務入力、比較期間・能力・安全条件などの未決事項は要件側のPO-B01〜08を確認し、fixtureから推測して確定しない。

## 文書変更の保留

- この記録は機能PRへ混在させず、文書変更の区切りで公開する。
- roadmapの更新履歴の残し方は次の文書整理時に判断する。見出し「日付を使わないガントチャート」は、その時に「ガントチャート」へ変更する。
- 進捗をPR数・内部部品数から算出しない。業務シナリオの疎通、正式データでの成立、未実装・未検証を分けて更新する。
