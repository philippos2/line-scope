# SPOF公開DTOと経路Evidence

仕様正本ではなく内部実装チェックポイント。正本api-tools §17 / §23、domain-model §15に従う。

単独除外評価を公開CANDIDATE / NOT_CANDIDATE / INDETERMINATEへ変換し、重要対象・候補の組ごとの結果、経路、一段代替、正本状態とversionのEvidenceを構築する内部処理を追加した。分析モード、対象集合、候補集合、単独除外条件の一致を検証する。

既存代替DTOから経路・関係factsの組み立てだけをfulfillment_evidenceへ抽出して共有した。判定処理は共有しない。全分析の代表経路へ一つのpath上限を適用し、上限不足で全findingを判定不能にする。取得していない関係を生成せず、代替方向と保存source / targetを区別する。

公開Tool / HTTP / Agent接続とBusiness Scenario受入は後続。構造分類は能力・安全・経済評価ではない。
