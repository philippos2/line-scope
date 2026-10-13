# 代替・SPOFの実LLM baseline

仕様正本ではなく評価記録。operations §19、evals §8に従う。

2026-10-13、単独の使い捨てCompose環境で初期seed-demo-graph、schema設定、Rebuild、Projection再開を実施。通常デモvolumeとprivate .envは変更していない。モデルは既存`qwen3:30b-a3b-instruct-2507-q4_K_M`、context 16384、temperature 0、num_predict 700、Agent予算60秒。モデルを事前ロード（約25.35秒）したwarm条件。元コードはmain `18f63aa`、公開Tool schema・SYSTEM_PROMPTは同コミットのもの。

質問は初期fixtureのProduct P-100 IDとEquipment M-204 IDを明示し、現在時点の一段代替／構造成立と、同対象・候補の単一障害点候補をそれぞれ問い合わせた。既知ID付きのprobeであり、コードや名前だけからの対象解決品質の評価ではない。

質問datasetは`fulfillment-demo:v1`。今回の問い合わせ文はverify_graph_agent.pyのalternative / spofの固定テンプレートと同じで、各IDはdemo_id / DEMO_EQUIPMENTから決定する。評価の主張は単発のwarm実行に限定する。

| ケース | 実測結果 | 判定 |
|---|---|---|
| 代替 | find_alternative_pathsを選択したが、引数検証でINVALID_ARGUMENT。HTTP 200 / needs_inputとなりTool結果なし | FAIL。構造評価の結果に到達していない。不正引数の拒否は維持されている |
| SPOF | get_product → get_equipment → trace_upstream_dependencies → find_single_point_failure_candidates。約55.41秒。P-100に対するM-204はNOT_CANDIDATE、CURRENT・完全探索・8代表経路・初期正本versionとサーバEvidenceを照合 | この構造化probeはPASS。一般的説明品質・全Business受入は未承認 |

SPOF回答はM-208による一段置換と未評価次元を説明した。一方、上流依存を「直接・間接影響候補」と呼ぶ表現は改善余地がある。説明品質まで全面合格とはしない。

代替の不正引数の詳細原因は未特定。通常ログへ引数・prompt全文を追加して調べず、隔離評価で必要部分のみ確認する後続課題とする。実LLM品質にFAILが残ることを明示し、ScriptedLLMの成功やCI総件数で上書きしない。使い捨て環境は全volumeを含め片付け済み。

後続で[現在時点引数の原因特定・修正・再評価](2026-10-13-alternative-agent-arguments.md)を実施した。この初回FAILの記録は保持し、後続の単発成功と区別する。
