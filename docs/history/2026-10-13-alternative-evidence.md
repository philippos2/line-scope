# 代替評価の構造化結果と経路Evidence

仕様正本ではなく、実装チェックポイントの記録。

正本api-tools §17 / §21、domain-model §15に従い、検証済みGraph facts・評価結果・正本状態からReadResultを構築する内部処理を追加した。通常の必須経路と一段置換を区別し、保存方向・論理方向・source record ID / versionを維持する。全必須関係と直接置換factsをEvidenceへ残す。世代・時点・状態version・missing状態も追跡できる。

max_pathsを全代表／置換経路で共有し、経路Evidenceが不足すれば全体complete=false / INDETERMINATE、各構造判定INDETERMINATE、availability=UNKNOWNへ限定する。既知の観測factsは保持するが、証拠不足の結果を確定した代替保証へ変換しない。既存探索のTIMEOUT / NODE_COUNT / DEPTHをPATH_COUNTより優先し、上限ちょうどでは打切りにしない。

評価結果にhistoricalを保持し、builderで分析モード・除外集合・入力対象・完全性を照合する。過去Evidenceへ現在利用可能性の確定評価を流用しない。未返却の関係から経路を生成せず、根拠欠落はGRAPH_UNAVAILABLEとする。公開データの構造成立とOPERATIONAL_IMPACT / CAPACITY / SAFETY / ECONOMICSを分離する。

追加13の実DBテストと既存9テスト、計22テストをDocker内で実行した。14の全経路・一段置換、保存／論理方向、共有path上限、上限ちょうど、node上限優先、過去時点、未返却関係拒否、分析モード／除外集合不一致を確認した。AC-G05 / G08 / G09 / G10のEvidence部分を支えるが、認可済みTool / API / Agentへの公開と業務受入は未完。予算・最終gateは呼出元Applicationが所有し、builder成功だけで公開しない。

公開入口への接続レビューで、代替EvidenceがGraphAnalysis本体の共通変換へ依存していたため、serialize_pathsと分析範囲定数をgraph_evidenceへ分離した。通常Graphと代替Evidenceが同じ変換を使い、公開Applicationがbuilderを呼んでも循環依存を作らない。公開契約は変更せず、代替Evidence・通常Graph・共通依存の実DB回帰40テストとlint / formatを再実行した。
