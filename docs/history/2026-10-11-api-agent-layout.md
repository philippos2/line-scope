# API / Agent / LLM接続の配置整理

## 範囲

配置整理の第五段階。api・http_loggingをinterfaces、agent_input・agent_tools・read_agent・update_intentをagent、Ollama接続のllmをintegrationsへ移動する（本体7モジュール）。HTTP/API・観測テスト17、Agentテスト4、LLM接続テスト1を対応するtests packageへ移動し、DB schema検証3をtests/persistenceへまとめる。呼出側、共有fixture、故障注入先、verify_local_llm.pyのimportを更新する。旧パスの互換shimは追加しない。

HTTP・Tool契約、LLM prompt、LLMへの権限、認可、会話・retry、transaction、SQL/Cypher、Snapshot、Audit/Outbox、テストassertを変更しない。Qdrant・UI・worker常駐など未実装部分は追加しない。LogiScopeコードは再利用していない。

## 配置整理の区切り

本体の主な配置はapplication（業務サービス）、domain（純粋検証）、persistence（PG）、graph（同期）、interfaces（HTTP入口）、agent（Agent制御）、integrations（LLM接続）。テスト側も同じ責務単位へ対応する。Unit / Integration / Contract等の試験階層はpackage名と区別する。

rootにはCLI・デモ初期投入・設定・logging・Trusted Execution Context・cursor codecを入口/共通基盤として残す。tests rootには共通conftest、foundation・logging・demo seedの横断テストを残す。すべてのファイルを機械的に下位フォルダへ移すことは目的としない。主要な配置整理はこの単位で一区切りとし、次は既存境界の改善へ進む。

/agent handlerの業務振り分け、ProposalStoreの保存/認可/状態解釈、サービス内SQL、Application/Agent間の依存、LLM adapterのToolError依存等は現状のまま。配置整理だけで責務分離・依存反転が完成したとは扱わない。改善は既存transaction意味を維持する小さな単位で行う。README・文書群の全面整理はバックエンド実装が一段落してから。

## 検証

本体59モジュールのAST比較でimport以外の処理変更がないことを確認。全体試験とCIで収集件数、Agent・HTTP挙動、packaged migrations、Compose起動を検証する。

ローカル結果: Docker内全体2,474 passed / 1 skipped / 1 warning（184.59秒）。移動前と同じ件数。ruff check / format成功（162ファイル）。
