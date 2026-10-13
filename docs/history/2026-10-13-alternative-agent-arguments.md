# 代替分析の現在時点引数修正と再評価

仕様正本ではなく評価・変更記録。[初回baseline](2026-10-13-fulfillment-agent-baseline.md)のFAILを対象とする。

同じダミー質問、モデル、公開schema、SYSTEM_PROMPTの最初のnative Tool応答を隔離診断で確認した。生成引数は正しいProduct / Equipment ID集合に加え`explicit_as_of="now"`を持っていた。timezone付き日時以外を拒否する既存契約がINVALID_ARGUMENTを返していた。通常ログへpromptや引数全文は追加していない。

現在分析ではexplicit_as_ofを省略し、サーバに時刻を決めさせる規則をTool schemaとSYSTEM_PROMPTへ明示した。nowを解釈する実装、引数の自動書換え、検証緩和、deadline延長は導入していない。上流依存・代替・SPOFを直接／間接影響と呼ばない指示も追加した。

2026-10-13、同じfulfillment-demo:v1の二質問を新しい使い捨てCompose環境で再実行。初期seed / Rebuild、既存Qwen3 30bモデル、context 16384、temperature 0、num_predict 700、warm、Agent予算60秒を維持した。

| ケース | 実測結果 | 保証範囲 |
|---|---|---|
| 代替 | find_alternative_pathsのみ呼出し、40.94秒、8代表経路。完全探索・現在時点・構造成立・一段代替と正本version / Evidenceを照合 | 単発構造化probe PASS |
| SPOF | find_single_point_failure_candidatesのみ呼出し、27.85秒、8代表経路。M-204のNOT_CANDIDATEと正本version / Evidenceを照合 | 単発構造化probe PASS |

日本語回答は対象・候補、構造判定、一段代替、未評価の能力・安全・経済を区別し、初回の上流を「影響候補」と呼ぶ表現はこの二回答では出なかった。ただしUUID再列挙、内部node_refの表示、「操業影響」を「操作影響」と訳す表現は改善余地がある。一般品質の承認、名前だけの対象解決、繰返し・cold条件、Business Scenario全体の合格とはしない。

不正nowは代替・SPOF両入口でDB参照前に拒否する回帰試験を追加した。試験と実LLMの専用Compose環境はvolumeを含め片付け済み。
