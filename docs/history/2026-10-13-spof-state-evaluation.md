# SPOF候補の単独除外と単一状態観測

仕様正本ではなく内部実装チェックポイント。domain-model §15、api-tools §17に従う。

収集済みSPOF factsの全Equipment / ProductionOperationについて、一回のPostgreSQL状態観測を行うApplication処理を追加した。重要対象ごとの候補集合と一段代替factsの一致を状態I/O前に確認し、候補ごとに除外集合をその候補一要素へ固定する。別の候補を同時除外した結果を流用しない。

純粋SPOF計算を使い、除外前構造成立、必須上流への所属、単独除外後の成立・代替利用可能性を評価する。現在状態が既知の停止なら利用不可、状態欠落や過去の代替利用可能性は未知を維持する。Graph不完全は全候補をINDETERMINATEとし、探索完全性と判定確定性を分離する。

実DB試験で一回の観測、候補別の相異なる結果、既知停止、欠落、過去時点、無関係候補、空指定、node打切り、facts不整合、状態観測後のRebuildによる最終gate拒否を検証した。最終gate成功前に結果を公開しない責務は呼出元に維持する。

内部結果はSPOF / NOT_SPOF / INDETERMINATEを保持する。公開DTOではapi-toolsのCANDIDATE / NOT_CANDIDATEへ変換する後続作業が必要。Evidence・Tool / HTTP / Agent公開とBusiness Scenario受入は未完。構造評価は運転能力・安全性・経済評価を保証しない。
