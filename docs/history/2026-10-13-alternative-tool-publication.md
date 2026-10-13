# 代替分析Toolの公開

仕様正本ではなく実装チェックポイント。正本api-tools §17 / §20 / §21、domain-model §15に従う。

`find_alternative_paths`をGraphAnalysis、ToolDispatcher、参照専用Agent、既存`POST /agent`へ接続した。重要対象・除外対象の検証後、単一世代のGraph収集と一回のPostgreSQL状態観測を使い、最終同期gate成功後に構造化結果とサーバEvidenceを返す。Infrastructureアクセスは既存adapterに維持し、HTTP handlerへDB処理を追加していない。

公開schemaはimportant_targets / excluded_nodesを必須とし、relation_types、timeout、認証主体の上書きを受け付けない。Agentへ一段置換と必須依存経路の違い、構造成立と実稼働・能力・安全性の違い、未知・探索不完全の扱いを指示する。モデル向けGraph圧縮はAPI結果と分離する。

実PostgreSQL / Neo4jとScriptedLLMによるAPI試験で、許可role、非CURRENT拒否、対象不存在、構造化結果・Evidence、経路上限時のHTTP 200 / partial、更新要求を作らないことを確認する。ScriptedLLMの成功は実LLMによる自然言語Tool選択・説明品質の受入合格を意味しない。能力・安全・経済評価、SPOF公開、業務受入は後続。
