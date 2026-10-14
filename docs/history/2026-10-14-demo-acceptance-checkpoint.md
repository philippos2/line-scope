# デモ受入チェックポイント

PR: #226 / feat/demo-backend-acceptance / 56166a8

最小API経路、複数設備のPrepare→Approval→Execute、実Embedding/Qdrant検索、実Ollamaによる表示順選択とサーバ側日本語要約を、一括実行するverify_demo_acceptance.pyを追加した。専用Compose環境を順次使用し、全4経路PASSを確認した。

実測報告: /tmp/linescope-demo-acceptance-report.json（0600）。実行時revisionは2ae9dc7、working_tree_dirty=true。モック業務入力を含むデモ経路の受入であり、正式Business Scenario全体の合格ではない。一般LLM groundingとWeb UIは未受入・未実装。

CI: 3754件収集、3753 passed / 1 skipped。shard 1: 1867 passed / 268.73秒。shard 2: 1886 passed / 1 skipped / 160.67秒。collection hash一致。runtime、migration、lint成功。追加テスト4件。専用環境とテスト環境を片付けた。

次の候補: 一般Read Agentの回答根拠を扱う最小の品質検証、またはcloneからデモまでの再現手順とREADME整理。正式業務入力の置換をこのデモ受入と混同しない。#225時点のデモ一段落まで4〜7PRという見積もりのうち、今回が一括受入の1PR。見積もりは残る業務経路の検証結果で更新する。

履歴は機能PRに混在させずstashで保持し、後続の文書PRで取り込む。
