# 公開cloneからのデモ再現

公開リポジトリのmain adcd8caを一時ディレクトリへdepth 1で新規cloneし、python3 scripts/verify_minimal_flow.py --docker-group dockerを実行した。終了code 0、result PASS。

実HTTP / PostgreSQL / Neo4jで、影響と仮置き比較→Prepare→承認前Execute拒否→別承認者のApproval→requesterのExecute→再送→更新後確認を実行。M0 fixed scenarioでありGolden全体の合格ではない。LLM未使用、費用・能力・リスク・文書検索・比較入力はモックを含む。

結果: /tmp/linescope-clean-clone-result.json、実行ログ: /tmp/linescope-clean-clone.log。専用Compose project、volume、資格情報、一時cloneは終了時に削除した。通常.env / volumeは変更していない。Dockerキャッシュと既存ホストDocker環境は使用した。別PCの未設定環境・ガイドの通常永続環境手順を独立に全実行した確認ではない。

#226の実Embedding / Qdrant / Ollama試験、#228〜229の実Read評価と合わせ、仮置き入力を明示したデモバックエンドが一段落する範囲を確認した。正式業務入力、全BS、一般LLM品質、Frontendは残件である。
