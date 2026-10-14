# 複数業務シナリオのAPI経路チェックポイント

作業記録であり、仕様正本ではない。仕様入口はdeliverables、残工程はroadmap。

- #220 merge確認後、main 55fa431からfeat/decision-business-scenariosを作成。commit319665f、PR #221。
- 明示demo modeでサーバ設定LINESCOPE_DEMO_DECISION_SCENARIOを選択できる。AUTOは既存動作。STOPPED／DEGRADED／SAFETY_STOP／SUFFICIENT_CAPACITY／MISSING_LOSS／MISSING_REPAIR_COST／NONADDITIVE_LOSSの7ケース。
- 実PG状態・Graphを読み、決定論的計算・制約・不足情報・Evidenceを同じAPI結果へ接続。外部入力からfixtureを変更せず、リクエスト間のfixture改変も隔離。
- 関連34成功、5.53秒。追加10ケースで全直積なし。lint・format319ファイル成功。
- verify_minimal_flow.py --docker-group docker --decision-scenario MISSING_LOSSの専用Compose/curl疎通成功。subtotal120000、完全総額と修理総額はNULLのまま。Prepare→別ActorのApproval→Execute→更新後確認も通過。専用volume・認証情報は削除済み。
- 入力はMOCK_FIXTURE。PO-B01〜08、Golden全体、実LLM品質は未解決／未検証。BS数値の一部成功をBusiness Scenario全体の合格としない。
- 既存Starlette/httpx警告と終了時logging output failedは未調査。

## 次の再開点

#221のmergeを確認する。#210以降の約十数PRで得られた業務到達点をもとにroadmapを再確認する時期。旧roadmapの古い現在地、ガント見出し、残PR見積もりと保管中の履歴を、機能PRとは別の文書整理で更新する。次の機能も入力から出力までの業務単位でまとめ、内部部品やPR数から進捗率を算出しない。

CI全成功：3723成功・1skip。収集3724件・hash一致、選択1849＋1875＝3724。試験時間258.06秒／180.85秒。runtime・migration・PR title・集約checkも成功。ローカル使い捨て試験環境は片付け済み。
