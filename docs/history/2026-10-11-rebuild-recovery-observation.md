# Rebuild復旧前のcontrol観測

仕様正本はtransaction-design §17・§20とoperations §10。本記録は実装判断の履歴。

- 新leaderとexclusive mutation lockを保持して、固定SQLAlchemy Core SELECTでcontrol一行を読む。短い読取transactionを所有し、Neo4j I/Oをまたぐrow lockは取得しない。
- flag、rebuild_id、active_generation、fatal_errorをimmutableな観測結果で返す。control・Outbox・Graphを変更しない。
- flagが残りrebuild_idが存在する場合のみ旧ticketを取り出せる。観測は所有権やNeo4j検証の証明ではなく、resumeは引き続き旧ID・pointer・flagの条件付き更新と実Graph検証を行う。
- 読取の前後にleaderと排他lockを確認する。読取後に状態が変化した場合、古い観測ticketのresumeは拒否される。
- Neo4j検証情報の取得、controllerの自動復旧接続、未検証generationのcleanupは後続。CURRENT判定や復旧完了を追加していない。

実PostgreSQL/Neo4jを使うGraph回帰試験で、無変更の観測、残存ticketからの引継ぎ、古い観測の拒否、flag解除済み状態、pointer/error保持、leader/lock喪失を確認する。control欠落は読取境界の故障注入で確認する。
