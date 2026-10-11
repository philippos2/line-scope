---
name: backend-verification
description: LineScopeバックエンドの変更後にpytest、ruff、migration、実DB/API検証、CI、checkpoint commitとPR引渡しを行う。試験の選択、実測結果、未実施範囲、片付けを明確にする。
---

# LineScope Backend Verification

小さくレビュー可能な変更を検証し、部分合格をプロダクト完成と扱わない。

[文書入口](../../../docs/deliverables.md)、[test-plan](../../../docs/implementation-design/test-plan.md)、[acceptance-criteria](../../../docs/requirements/acceptance-criteria.md)と対象正本を確認する。Business受入はbusiness-scenarios、LLM品質はevals、環境・ログはoperationsを参照する。現在のコマンドはcompose.test.yaml、backend/pyproject.toml、.github/workflowsを確認する。

## 範囲と検証

変更目的・契約への影響・未完成/仮実装/TODOを確認する。関連試験のbaselineと必要な回帰を選び、Production code/constraint/transaction変更では実DBの必要性を判断する。可逆な文書だけの変更に無関係な試験を新設しない。

backendの試験・lintはDocker内で行う。基本コマンドは次の形とし、実際のCompose定義と整合させる。

イメージへCOPYされたコードで試験する場合、変更後に`docker compose -f compose.test.yaml build tests`を行う。既存イメージを使う場合は変更したbackend/scriptsを明示的にmountし、古いコードを検証していないことを確認する。Docker socketの権限に応じて既存の`sg docker -c`経路を使う。

```sh
docker compose -f compose.test.yaml run --rm tests pytest -p no:cacheprovider <対象> -q
docker compose -f compose.test.yaml run --rm --no-deps tests ruff check backend scripts
docker compose -f compose.test.yaml run --rm --no-deps tests ruff format --check backend scripts
docker compose -f compose.test.yaml run --rm tests
```

同じ使い捨てDB/Neo4jを共有するsuiteを同時に走らせない。lint等の独立検証は並行可。migration・SQL/lock変更はsnapshot/hash/version/rollback/outboxを意味でassertする。Test削除・assertion弱体化・安全チェック無効化・CI除外でGreenにしない。

Business Scenarioは意味論的結果・決定論的fixtureで検証し、LLM自然言語の完全一致やmockの成功を主な受入根拠にしない。計算入力fixtureを正式業務規則へ昇格させない。PASS/FAIL/BLOCKED/NOT_IMPLEMENTEDと未検証を区別する。

## CheckpointとPR

開発者の指示と既存変更を確認してmainをff-onlyで更新し、意味のあるbranchに小さいcheckpointを残す。無関係な未完成作業は破棄せず、必要時だけstashし、どこに残したか報告する。

Conventional Commit titleと既存PRテンプレート（概要/検証/残課題・対象外）を使い、変更理由と実際の検証を記載する。mainはSquash mergeを標準とし、過去履歴のrewrite/force-pushはしない。GitHub設定・required checksの現状を推測で変更しない。開発者がmergeする運用を維持する。

CI green後も、ログの実測件数/時間、required checks、結果の追記、test環境の片付け、作業ツリーを確認する。削除はこの試験が所有する使い捨て環境に限定し、通常のデモvolumeへdown --volumesを向けない。開発者が先にmergeしても残る確認を省略しない。

完了時は「CI確認・結果追記・片付けまで完了しました。mergeできます。」と案内する。この文を確認前に発行しない。次工程はmergeを確認して進め、Codexが代わりにmergeしない。

## 報告

変更内容/理由、実行コマンド・結果・件数、未実施と理由、known failure/skip/warning、関連ACの保証範囲、未解決/次工程を示す。重要判断は正本または非正本の履歴へ適切に記録する。READMEの古い実装状況を正本より優先しない。
