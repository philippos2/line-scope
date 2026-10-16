# 常設デモの稼働確認

- 開発依頼者から画面停止の報告を受けた。既存 `linescope-browser-demo` のFrontend／API／Projection／PostgreSQL／Neo4jは約4時間前に終了しており、containerとvolumeは残っていた。停止主体・原因は未確定。
- PR #255のmergeを確認しmainを `edab3f7` へff-only更新。既存 `.env.browser-demo` と同じCompose projectを用い、最新imageをbuildしてFrontend・API・Projectionと依存DBを起動した。データ削除・再seedは実施していない。
- Frontendは127.0.0.1:5173、APIは127.0.0.1:8000。PostgreSQL／Neo4j／APIのhealth成功、Read既定120秒を確認した。
- 一時環境の実検索受入は成功済みだが、常設デモにはQdrantと実Vector接続が含まれていない。代表経路の実装受入100%と、常設環境ですべて利用できる状態を区別する。常設RAGの設定・文書投入・疎通確認は残作業。
- 任意自然文のTool選択精度と待ち時間の改善は、既知制限として完成後の課題に維持する。
- 復旧後のFrontendと認証付きAPI readinessはHTTP200。実QwenによるM-204状態参照も43.3秒・HTTP200・status ok・errors空で成功し、search_equipment／get_equipment_stateからSTOPPED・version 1を取得した。
