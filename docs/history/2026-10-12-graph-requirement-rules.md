# 必須依存・利用可能性の基礎規則

仕様正本ではなく、実装チェックポイントの記録。

正本domain-model §4 / §15.1に従う純粋な規則を追加した。DEPENDS_ON / SUPPLIESはrequiredに従い、PRECEDES / CONTROLS / PRODUCESとactive・有効期間内のUSESは必須。CAN_SUBSTITUTEは必須依存そのものに混ぜない。USESのderived requiredが未設定・falseでも必須性を失わせない。未知の関係種別やcanonical上不正なflagは拒否する。

EquipmentはRUNNING / STOPPED / UNDER_MAINTENANCE / UNKNOWN、ProductionOperationはPLANNED / CANCELLEDの正本値をAVAILABLE / UNAVAILABLE / UNKNOWNへ変換する。状態欠落はUNKNOWN。active=trueをavailabilityとして受け付けず、予定利用可能性を実行中状態と同一視しない。Process / InfrastructureResourceの運転状態は正本がないため、後続評価でもUNKNOWNを維持する。Productの運転状態規則は追加していない。

必須条件のANDと独立評価済み一段代替候補のORについて、三値の集約を実装した。入力集合のcompleteは明示boolを必須とし、不完全ならUNKNOWNを返す。空ANDのAVAILABLEは論理的な中立値であって対象自身の運転状態の保証ではない。空ORのUNAVAILABLEは完全な候補集合が空の場合だけ。0 / FALSE / NONEをUNKNOWNやavailabilityへ暗黙変換しない。

今回は基礎規則と単体試験のみ。active / effective期間のfilter、状態の正本取得、必須循環のINDETERMINATE、除外後の成立評価、候補自身の必須条件、一段のみの置換制御、SPOF確定、Tool / API公開は後続。これらの集約関数だけでGraph成立や業務上十分な代替、安全性・能力を判定しない。
