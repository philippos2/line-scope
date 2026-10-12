# 共通依存ToolのApplication / API / Agent接続

仕様正本ではなく実装・検証記録。

find_common_dependenciesを、Graph adapter注入時だけの固定Tool一覧へ追加した。通常参照Agentに公開し、Approval / Execute / Prepare / 任意SQL/Cypherの経路は追加していない。

認可と入力検証を接続前に行い、distinct targetsをUUID正規化後に確認する。全rootを実効node予算に収容できない要求は拒否する。同じserver time、generation、as_of、shared gate、deadlineで上流探索し、共通候補ごとに全対象の経路を揃える。限界で不完全な空集合を「共通依存なし」と扱わない。

通常探索と同じ経路検証をserialize_pathsへ抽出し、保存方向と論理Traversal方向を照合してEvidenceを構築する。全探索で確認したEquipmentの現在状態を一回の正本観測へ集約する。過去関係時点と現在状態を区別する。

data.common_candidatesはtyped ID配列、representative_pathsはtarget / candidate付き経路。サーバEvidenceを維持し、LLM向け参照表にも共通Toolを適用する。探索complete=falseはAPI status=partialに接続する。共通候補を原因やSPOFと断定する指示は行わない。

実DB / Neo4jで候補・対象別経路・状態version・global limit・inactive / missing target・非CURRENT拒否を検証し、ScriptedLLMによるHTTP / Agent結合で返却契約を確認した。実LLMの共通Tool選択・説明品質は未検証。Product等の業務コードからの対象解決は、現在のRead Toolで取得できるIDまたは追加情報を必要とし、未知IDを推測しない。
