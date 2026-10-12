# 通常GraphのLLM入力表現と応答時間

仕様正本ではなく、調査・変更・検証の記録。

#167後の実LLM試行では、Ollamaの最終生成がAgentの60秒予算を使い切った。serviceログで生成途中のcancelを確認した。初回呼出しのモデル読込に約28秒を要する試行もあった。要約指示だけでは、読み込み済みmodelでも時間内に収まらなかった。

Agent専用のgraph_model_viewを追加し、重複typed nodeと全属性が一致するedgeを参照表へまとめる。経路順、required、有効期間、complete / limit_reason、世代、状態versionを保持し、元結果へ復元できることをテストする。API / Tool返却やサーバEvidenceを変更しない。責務はAgentのLLM入力組立に限定し、DB / Graph探索 / 権限 / 60秒予算は変更しない。

隔離Composeと暫定qwen3:30b-a3b-instruct-2507-q4_K_Mで、search_equipment→trace_downstream_impact→最終回答がstatus=okで完了した。サーバ結果を既存probeで照合し、6対象・2製品・6代表経路・CURRENT・Evidence・初期state versionが合格した。Ollamaの3呼出しは約10.96 / 7.08 / 36.09秒だった。一回の成功で応答時間や一般品質を保証しない。

回答文にはUUID列挙と広い「不明事項なし」の表現が残った。自然言語の読みやすさ・不確実性表現は継続評価が必要であり、一般AI品質やGolden Scenarioの合格とは扱わない。コールドスタート、より大きなGraph、長い会話は未保証。model具体選定と私有.envは変更せず、LogiScopeコードは再利用していない。
