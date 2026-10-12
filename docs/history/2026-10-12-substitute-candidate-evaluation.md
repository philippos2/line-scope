# 一段代替候補自身の成立・利用可能性

仕様正本ではなく、実装チェックポイントの記録。

正本domain-model §15.1 / §15.3 / §15.4に従い、一つの代替候補自身と全必須上流の構造成立・利用可能性を評価する純粋計算を追加した。構造評価は既存structural_fulfillmentを使用し、候補の必須条件をさらに代替する経路は設けない。active / effectiveな直接CAN_SUBSTITUTEの存在・向き・同一種別、必須関係の分類、探索予算と完全性、正本状態取得は呼出元が検証する。今回はDB・Graph reader・公開Toolへ接続していない。

構造循環・情報欠落・探索不完全は利用可能性UNKNOWN。候補または必須上流の除外は構造不成立・UNAVAILABLE。構造成立時も候補自身と全必須上流の運転利用可能性をANDで確認し、設備RUNNINGだけで候補全体をAVAILABLEにしない。利用可能性の欠落はUNKNOWN。既知の必須停止はANDの不成立を証明するが、UNKNOWNだけをUNAVAILABLEへ変換しない。

Equipment / ProductionOperationの値は既存状態変換を経たPostgreSQL正本由来の三値を要求する。Process / InfrastructureResourceは運転状態正本がなくUNKNOWNを維持し、提供されたAVAILABLE値から運転可能とは判断しない。Productの運転状態規則は追加しない。historicalを明示boolで要求し、過去時点には現在の稼働値を流用しない。除外による構造評価と、過去の運転状態不明を区別する。

追加23テストで全AND依存、停止・保全・未知、除外元に依存する候補、循環・不完全性、状態欠落、過去時点、運転状態未定義の型、不正入力を検証した。AC-G05 / G09、T-R14 / R15の候補評価部分を支えるが、候補探索と関係Evidence、候補間OR、重要対象の成立／除外前検証、SPOF確定、API / Tool公開は後続。能力・安全性・経済性は判定しない。
