# 共通依存候補の選択計算

仕様正本ではなく、実装チェックポイントの記録。

R-11 / UC-18 / AC-G04 / api-tools §17に従い、複数対象の上流集合の共通要素と対象別代表経路を選ぶ純粋な計算を追加した。入力は対象と検証可能なBFS predecessor事実。既存representative_pathsの検証を使い、対象自身は非root集合に含めない。typed ID順で決定論的に返す。

一候補について全対象からの経路を揃えて返す。共通候補の経路だけが出力paths予算を消費し、無関係な短い経路で予算を使わない。予算不足では候補の一部の証拠だけを返さずcomplete=false / PATH_COUNTとする。入力探索が不完全なら、確認できた共通候補は保持できるが、空集合を「共通依存なし」の確定結果にしない。limit_reasonはTIMEOUT → NODE_COUNT → DEPTH → PATH_COUNTの優先順を維持する。

必須依存、実際の停止、可用性、代替、SPOFをこの共通到達集合だけで判定しない。任意SQL/Cypher、DB、HTTP、LLMへの依存を持たせない。

今回の範囲は内部計算と単体試験。Tool登録・API / Agent公開・active検証・単一generationのshared gate・as_of・全探索のnode / deadline予算・Equipment状態Evidenceは後続のApplication実装で保証する。AC-G04の全体完了や実LLMの共通依存問い合わせ対応とは扱わない。
