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


## 90秒条件と追加指示

- source `51669fa`、90秒、元の5質問で3/5。状態53秒（cold load 18566msを含む）・対象不存在5.4秒・上流18.5秒は構造化PASS。状態と原因不明の文章は保持された。
- 下流・共通依存は約58〜59秒でHTTP500 INTERNAL_ERRORとなり、deadline到達ではない。応答検証が拒否しているため、失敗時にも終了理由・token数・本文／thinkingの文字数だけを追えるよう追加した。
- 原結果は[90秒測定](2026-10-16-read-quality-90s.json)。実際の提示はRead 27 Tool。LogiScopeの5 Toolとの差はあるが、Tool個数だけを単独原因と断定しない。
- ユーザーが120秒までの緩和も許可したため、Readの既定を120秒へ更新。90秒測定はそのまま残し、成功扱いしない。性能改善は今後の課題として、全面再設計より完成を優先する。
- Tool終了計画の新引数は採用していない。Claude評を一律の事実とせず、現実装と実測で採否を判断する。


## デモ完成の基準を再確認

- ユーザーは実業務の顧客がおらず、開発依頼者本人が操作して確認するデモ・習作であり、実用性より「曲がりなりにも形になっていること」を優先すると明示した。
- requirements §1、acceptance-criteria、NFRとevalsの一般品質リリース阻害条件を、この目的へ整合させた。機能・認可・承認・原子性・不明を維持し、一般LLM／検索品質・短時間応答・全UI variantの網羅は改善課題へ移す。未受入をPASSに変更しない。
- 今回の代表経路と制限の記録、その後の起動・再現・最終運用確認を完成までの2 PRとする。Tool絞込み・モデル変更・streaming等を完成前の必須工程に追加しない。
- 120秒の下流診断はHTTP200、モデル終了STOP・生成450 tokens・thinking内容は未出力。ただしモデルがrelation_typesからPRECEDESを除いたため到達2件となり、期待6件のfixture検証はFAIL。時間・700 token上限だけを単独原因と断定できない。原結果は[下流診断](2026-10-16-downstream-protocol-diagnostic.json)。

- 再現確認だけを別PRへ分けず、既存4経路のデモ受入と主要ブラウザ経路を今回へ集約する方針へ更新。デモ基準で進捗約95%、今回1 PR・追加0 PRを予定する。前の2 PR概算はこの判断前の値。
- 検索baselineは6/6で正解rank 1、hit@1・recall@3・MRRは1.0、正本引用一致。小規模合成datasetの測定であり一般品質を合格にしていない。原結果は[検索baseline](2026-10-16-retrieval-quality-baseline.json)。
- 実PG／Neo4jで正式入力・Golden・Graph・承認更新の関連140成功（27.19秒）。受入runnerとprobeの関連検証を実施。新規pytestは12＋runner境界2＝14、検索の新規6質問を合わせた新規検証は20。

## 最終代表経路の実動確認

- 開発依頼者は、精度やレイテンシは実業務水準を求めないが、実際に動作する習作を求めると再確認した。代表シナリオの実接続・一連操作を必須とし、外観だけで完成扱いしない。
- source `7ffeac474fc3ac42c73ca54a0c974042b86637e3`、開始時cleanでデモ受入4段階すべてPASS。起動・migration・Graph再構築、別承認者とrequesterによる更新、複数対象の原子性、実Embedding／Qdrant／引用、実LLMによる正式入力比較を確認。[原report](2026-10-16-demo-acceptance-final.json)。任意自然文の全件合格を意味しない。
- 同じ実装でブラウザの正式入力比較経路PASS。入力編集、別ユーザーの承認、確定、条件付き150日、version 2、Graph／Evidence、接続断、画面幅を確認した。
- 復旧・staging・knowledge rebuild・DB roleの既存試験105成功、21.70秒。Starletteの既知非推奨warning 1件と終了時logging output failedが出たが試験失敗はない。
- 最新の関連検証307成功、受入runner／probe32成功、Ruff check／format成功（382ファイル）。最終の全体CIは以下へ確認後追記する。
