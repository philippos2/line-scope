# Read品質受入・モデル待ち時間の切り分け

## 再開点と範囲

- PR #254のmerge `cf23ba9bdcfe99954c9f17c8c84c245148b1748d`を確認し、mainをff-only更新。作業branchは`fix/read-quality-acceptance`。
- 旧branchは通常削除がSquash mergeにより拒否されたため、そのまま保持。force-push・履歴書換え・他Repositoryの変更は行わない。
- 今回は計画済みの回答／検索品質と全BSの受入。モデルや実行基盤の全面変更を前提にしない。

## 見つかった不具合と修正

- 状態と故障原因の調査中に安全入力検索が加わると、単一分野の安全要約が回答全体を上書きして状態説明が落ちた。構造化結果がPASSでも文章は不合格だった。
- `supported_answer`で調査全体のTool集合を確認し、単一分野でカバーできるときだけサーバ要約を採用する。異なる分野の調査は取得結果を保持してモデルの全体説明へ戻す。
- LLM呼出し時間・入力／出力byte数・提示schema件数・Tool件数をallow-listの運用ログへ追加。providerが返すprompt／生成token数、prefill／decode／load時間も数値だけ採用する。本文・prompt・provider生応答・thinkingはログへ出さない。
- 重複したSystem指示を整理。単一分野の完了応答と混在調査の説明を区別する。

## 60秒条件の測定と棄却した試行

同じread-demo-v2の5質問、導入済みQwenを使用。質問削減や時間制限の暗黙変更で合格にしない。

| 条件・source | 構造化結果 | 判定 |
|---|---|---|
| #254＋計測（source cf23ba9、dirty） | 3/5 | 下流・共通依存が時間切れ。状態の文章には上記上書き不具合もあった |
| 指示整理 ab76d05 | 3/5 | 下流・共通依存が時間切れ。軽量化だけで改善したとは判断しない |
| 混在回答修正＋要約添付 00a29db | 3/5 | 下流・共通依存が時間切れ |
| 経路をモデル入力だけから省略 1f6476f | 2/5 | 状態・下流・共通依存が時間切れ。共通依存のモデル入力約45KB→27KBでも解消しなかった |
| 経路省略を戻し詳細計測 3c7852c | 3/5 | 下流・共通依存が時間切れ。原データとEvidenceを保持 |

効果を確認できなかったserver_summary添付・経路省略は戻した。公開API・モデル向けGraphの可逆表現は維持する。終了計画をTool引数へ追加する案は実装採用せず、ユーザーの時間制限緩和の指示に従った。

これらの初期ログ・原reportは一時領域に置いていたが、実行環境切替後には参照できない。上表と以下の数値は実行時の確認出力から残す。原reportを保存済みと扱わず、後続の確定測定はRepositoryの履歴へ保存する。

## ボトルネックの観測

- 遅延は架空Toolだけの試験でなく、実PostgreSQL／Neo4jを通したRead Agentで観測。最初の状態調査ではToolのDB処理7〜9ms、LLMを5回呼んで全体58.5秒。
- 下流はGraph取得後のLLMが47.2秒でdeadline到達。共通依存も最後のLLMで時間切れ。DB・Snapshot・承認を遅延原因と断定しない。
- 導入モデルは`qwen3:30b-a3b-instruct-2507-q4_K_M`、digest `19e422b0231392335cfc49cfd172de7034bb1aeabb08aa307cce745c60b272fe`。Ollama 0.35.1。`think:false`・context 16384・出力上限700。
- RTX 3060 12GB。Ollamaのモデル占有報告約20.4GBに対しGPU上約10.6GB。Ollamaを親とするllama-serverがCPU約1200%を使用していた。観測値であり最大値・単独原因の証明ではない。
- 初回prompt 5564 tokensのprefill 12191ms、load 1ms。続く58 tokensの生成5345ms、125 tokensの生成12130ms。別の172 tokens生成は17099ms、prefill 2043ms。約10 tokens/sの生成が支配的な呼出しもあり、常にprefillが主因ではない。

## ユーザー指示とClaude評の照合

- ユーザーは「多少制限を緩めても仕方あるまい」と許可。Read全体の既定を60→90秒とし、環境設定で調整可能にする。Prepareの60秒、Tool数12、DB／Graph個別制限、承認期限を広げない。60秒と90秒の測定を区別する。
- Claude評は仮説として実装と照合。Readには既にPrepareを提示せず、AgentApplicationから明示的な登録入力比較を直接実行する経路も存在する。比較JSONを必ずLLMへ再生成させる設計ではない。
- 細いLLM接点・適切なTool提示は検討対象だが、固定語句で質問の業務範囲を黙って縮めない。API streaming、Agent全面移植、Prepare経路廃止を新しい完成条件にしない。
- 隣のLogiScopeをread-only参照。`docs/history/local-llm-selection.md`は同じQwen／RTX3060でCPU46%・GPU54%、context8192を記録。`agent-demo-verification.md`は実接続10/10成功、約5〜16秒。後続`artifacts/target-grounding-demo-accepted.json`も5/5成功、4.14／29.23／13.08／4.66／4.90秒。
- LogiScopeの現`Limits`は全体900秒・LLM300秒。OpenAI互換API・少数Tool・小さい結果・context8192という違いがあり、単に同じモデル／GPUだから同じ負荷・同じ受入条件とは扱えない。`artifacts/demo-verification.json`の現ファイルは失敗記録で、履歴の成功記録と混同しない。
- 姉妹アプリの成功から負荷差の検証を省いた点を反省材料として残す。既存の正本・承認・Snapshot等を作り直す根拠にはしない。LogiScopeのコードは移植していない。

## 検証と再開点

- 新規pytestは計11ケースの予定：LLM失敗計測2、混在上書き4、60／90秒境界の追加1、無効設定3、配線1。既存のprovider計測値・Tool／HTTP相関試験も強化する。
- 検索はretrieval-demo-v1の6文書・6質問を追加し、正解順位・hit@1・recall@3・MRR・正本引用一致を測る。合成datasetの成功を一般品質へ拡大しない。
- 関連試験232成功、provider内訳追加後276成功。90秒設定の関連297成功（2.12秒）。一度、取り消した経路省略用の新規assertが残り275成功・1失敗となったが、独立したEvidenceを保持する元契約のassertへ修正し、対象61成功・Ruff check／format成功（382ファイル）。
- 最新の90秒条件、検索baseline、CIの結果は確認後に追記する。進捗は約90%、残り2〜3 PR（本品質PR＋運用復旧1〜2）。品質受入を完了扱いしていない。
