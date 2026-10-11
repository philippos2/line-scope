# AgentのApplication境界

`/agent` の再試行判定、カテゴリ別Prepare振り分け、会話継続とRead Agent呼び出しを `application/agent_service.py` へ移した。

HTTP側は入力解析、Application呼び出し、結果のAPI envelope / HTTP status変換を担当する。Applicationは注入された既存サービスを利用し、HTTP・DB接続・SQLに依存しない。

保存済みretryの取得は会話context検証に先行する。Prepare後の応答取得が失敗しても保存済みIDを返す。カテゴリ別権限検証、会話の所有者・TTL、LLM未設定時の動作と、人間によるApproval / Executeの境界を維持する。既存の更新トランザクションやlockは変更しない。

Applicationの直接テストと既存API・DB試験で検証する。API factoryのcomposition root、ProposalStoreの複合責務、サービス内Persistence境界などの改善余地は残る。今回の抽出だけでClean Architectureが完成したとは扱わない。
