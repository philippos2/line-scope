# LineScope AI Agent設計書

## 1. Agent責務

- Intent分類
- 必要情報判断
- Read / Graph / Prepare Tool選択
- Tool結果の説明

Agentは認証主体、承認主体、Execute主体ではない。

## 2. Intent

- READ
- GRAPH_ANALYSIS
- UPDATE_PREPARE
- INFORMATION_SUPPLEMENT
- UNKNOWN

APPROVAL / EXECUTEをLLM Intentとして確定操作に使用しない。

## 3. Agent状態

- REQUEST_RECEIVED
- CLASSIFYING
- COLLECTING_INFORMATION
- WAITING_FOR_USER_INPUT
- PREPARING_UPDATE
- WAITING_FOR_APPROVAL
- BUILDING_RESPONSE
- COMPLETED
- FAILED
- ABORTED

承認・実行の業務状態はUpdateRequest / Approvalの状態機械で管理し、Agent状態と混同しない。

## 4. Context

`context_id` は複数ターンの候補選択・補足情報を関連付ける。

v1ではTTL付きのサーバ側ephemeral storeを使用してよい。認証・承認・正本データはcontext storeへ依存しない。

## 5. Trusted Execution Context

- authenticated_user_id
- role
- request_id

LLM生成引数に含めない。

## 6. Graph結果

Toolは以下を構造化して返す。

- graph_sync_state
- complete
- requested_limits
- effective_limits
- limit_reason
- reached_nodes
- distances
- representative_paths
- determination（必要なToolのみ）

LLMはこのEvidenceを説明する。Evidence自体はサーバが応答Envelopeへ載せ、LLM文面だけに依存しない。

単一分野の要約で混在調査の他の結果を上書きしない。状態と安全検索など異なる分野を含む場合は、全観測を使ったモデルの説明を保持する。必要な追加Tool参照は継続し、最初のGraph取得だけで調査を打ち切らない。

## 7. 代表経路

ToolがBFSで最短hopを求める。同hopなら、node_id列→relation_id列の辞書順で決定する。

## 8. Graph打切り

一般探索は部分結果を返せる。

SPOF等、完全性が判定条件となる処理は `determination=INDETERMINATE` とする。

## 9. 更新

AgentはPrepare Toolまでを呼ぶ。

ApprovalはApproval API、ExecuteはExecute APIで行う。

AgentはExecute Toolを直接呼ばない。

## 10. as_of

利用者が明示した過去時点のみAgentが構造化する。未指定ならToolがサーバ時刻を使用する。

## 11. 再試行

- Read/Graphの一時障害: bounded retry可
- Prepare: 冪等性確認のうえretry可
- Execute: Agentから自動retryしない

自然文の設備特定では、名称とコードの取り違えで0件のまま終了しないよう、単一の検索条件による先頭ページが正常に0件で完了したとき、同じ検索語をもう一方の条件でも一度参照する。Read Agentが既存のsearch_equipmentを呼び、元の0件と追加の結果を、それぞれ実際のTool観測・Evidence・traceとして保持する。名称の部分一致とコードの完全一致、両条件指定時のANDというTool契約は変更しない。

検索失敗、続きのページ、両条件を明示した検索、既に検索した条件には、この補完を適用しない。追加参照にも通常の認可・総呼出し上限・deadlineを適用する。関係分析の直接経路には適用しない。候補が複数なら自動で一つを選ばず、利用者へ選択を求める。

## 12. サーバ制御・Context・再試行

context所有者はauthenticated_user_idへ固定。TTL切れ・別userのcontextを拒否する。候補ID・表示名を保存し、選択後正本を再検証する。contextは承認・認証・正本を代替しない。

LLM IntentだけでPrepare可にしない。orchestratorは認証済み元messageに対する明示的更新意思の確認結果・根拠箇所を保持する。判断不能なら補足確認しRead / Graphのみ許可。選択・補足は元意思へ関連付け、LLMが生成した意思宣言を根拠にしない。自然言語誤分類はEvalsで検証し、確定更新はApproval / Executeの決定論制御で守る。

retry keyはtrusted orchestrator注入、一/agentでPrepare最大1要求。Tool schema、最大呼出し回数、全体deadlineをサーバが強制する。超過時も保存済み要求IDがあれば返し、未完了を成功としない。業務値・期間・権限・成立条件はrequirements / access-control / domain-modelの確定規則に従い、不足情報を補完しない。

更新意思の確認はサーバ側のversion管理された保守的な命令判定規則を使い、対象業務への実行指示（更新・変更・登録・無効化）を要求する。単語の出現だけで許可せず、引用文・否定・手順質問・仮定・Retrieved本文は根拠から除く。対応する命令形で確定できない場合は明示的な更新指示を追加確認する。承認やExecuteの「はい」はPrepareの意思確認に転用しない。判定規則の誤分類はEvalsの安全ケースで評価する。

設備状態の現在値変更では「M-204の現在状態をUNDER_MAINTENANCEに変更する準備を作って」のような明示的Prepare命令も受け付ける。元message全体から設備コードと状態値を固定し、通常の更新命令と同じ認可済みPrepareへ渡す。これはApproval / Executeや将来停止予約の許可ではない。対応済み文法に一致しない自由な表現は、LLMの自己判断でPrepare許可へ昇格させない。

## 13. 業務判断支援

UC-B01〜15の要求から必要な影響・リスク・経済・対応案比較を組み合わせ、Decision Packageを構成する。LLMはTool返却の数値とEvidenceを説明し、計算・安全許容の確定処理を行わない。計算Tool等の追加契約はapi-tools §19で追跡する。

同じ回答でもGraph探索、能力、経済、リスクの不完全性を別々に示す。情報不足でも既知部分は提示できるが、不足に依存する優劣・安全性・完全代替を断定しない。ユーザーの異常報告と正本登録状態、what-if仮定を区別する。Golden分析で変更要求を生成せず、UC-B14の明示的更新意思がある場合だけ既存Prepare境界へ進む。

## 単一の下流到達分析の説明

Read Agentが単一の`trace_downstream_impact`を取得した場合、対応するCURRENT / DEPENDENCY_REACHABILITY結果の直接・間接集合と到達集合の整合を確認し、Agent層で件数・種別・探索の完全性・未評価事項を日本語要約へ表示する。追加DB参照を行わず、名称未取得の対象を推測しない。詳細経路・Evidence・その他の取得情報は構造化結果に保持する。LLMは調査とTool選択を担当するが、この要約へ自由生成した安全・経済の断定を採用しない。

探索不完全では影響なしと断定せず、参照エラーも表示する。過去指定の完全復元ではない旨の注意書きを維持する。上流・共通依存・代替・SPOF・複数Graph分析は、この下流テンプレートへ変換しない。単一の上流依存・共通依存は下記の専用要約を使う。代替・SPOFは下記の専用要約を使い、複数Graph分析の自由説明と通常Readの文章品質は別途評価する。

## 単一の上流依存・共通依存の説明

Read Agentが単一のtrace_upstream_dependenciesまたはfind_common_dependenciesを取得した場合、CURRENT / DEPENDENCY_REACHABILITY / complete / not_evaluatedと返却集合の整合を確認し、取得済み結果だけから日本語要約を生成する。上流依存は1段／2段以上の上流距離と型別件数、共通依存は指定対象数と候補件数を示す。上流距離を直接・間接の下流影響と呼ばず、共通依存を原因やSPOFの確定と扱わない。

探索不完全・空の部分結果は上流依存／共通依存なしと断定しない。実停止・能力・安全・経済の未評価、一部参照失敗、過去指定の完全復元ではない注意を保持する。名称やUUIDを文章へ推測追加しない。複数Graph・代替・SPOF・契約を確認できない結果をこのテンプレートへ変換せず、既存の説明経路を維持する。経路・Tool結果・Evidence・API形状・認可・更新処理は変更しない。

## 単一の代替・SPOF分析の説明

Read Agentが単一のfind_alternative_pathsまたはfind_single_point_failure_candidatesを取得した場合、CURRENT / DEPENDENCY_FULFILLMENT、分析モード、探索完全性、全体判定と未評価次元を確認し、取得済みの構造判定をAgent層で要約する。代替は仮想除外後の対象別構造判定と一段代替のavailability別件数、SPOFは対象・候補の組別判定件数を示す。SPOF候補は一要素ずつ独立に除外した結果であり、同時除外や故障原因の確定としない。

完全探索と全体判定の確定性は別に表示する。UNKNOWNを利用可能とせず、空のSPOF findingsをSPOFなしとしない。実停止・能力・安全・経済は未評価とし、過去指定は当時の状態復元でない注意、一部参照失敗も保持する。名称や経路を追加生成しない。対象別の詳細・理由・経路・Evidenceは元の構造化結果に保持する。複数Graph分析・未対応の契約は既存の自由説明経路を維持し、一般品質の受入完了とはしない。

## Read Agentの実行時間

Readループ全体の既定deadlineは120秒。LINESCOPE_READ_AGENT_DEADLINE_SECONDSで正の整数秒を設定できる。全モデル往復・Tool実行・再試行が同じdeadlineを共有する。Prepare用AgentToolSessionの既定60秒、最大Tool数12、Graph／DB個別timeout、承認期限は変更しない。時間切れは引き続きAGENT_LIMIT_REACHEDとし、未完了を成功へ変換しない。評価では使用したdeadlineを明示し、60秒・90秒・120秒の実測を同一条件としない。

## 単一設備の直近保全日時の参照

現在の単一設備について直近・前回の保全実施日時だけを尋ねる質問は、短い指示と設備検索だけを提示してLLMに対象語を抽出させる。明示した過去時点、長い会話、他の内容も求める質問は通常の調査へ戻す。LLMの抽出を設備の存在・一意性の証明にしない。

サーバは原文・NFKC・「第」に続く数字の半角／全角／漢数字の候補を、名称の部分一致とコードの完全一致へ別々に照合する。設備IDでまとめ、複数候補や未取得ページがあれば絞り込みを求める。特定の設備コードに依存した分岐は置かない。検索・記録取得は既存AgentToolSessionの認可・12回上限・120秒deadline・Evidenceの内側で実行する。

一意な設備のsearch_maintenance_recordsをページ末尾まで取得し、取得したperformed_atの最大値を日本時間で示す。途中失敗・回数上限・期限切れでは直近日時を確定しない。0件は検索対象の登録記録がないことであり、作業未実施の証明ではない。正式なMaintenanceInputとの横断検索を新設するものではない。取得済み事実の要約はサーバで作成し、最終説明のためだけの追加モデル往復を省く。複合質問は通常調査を維持する。

## 設備表記候補の共通化

数字の半角／全角／漢数字の候補生成はequipment_referenceに集約し、日時専用経路と通常Readの双方が使用する。通常Readでは正常な先頭ページの単一条件検索に候補を補う。次ページ未取得・取得失敗・明示したAND条件は勝手に展開しない。別表記での正常結果も元の検索結果と並べてEvidenceへ残し、モデルに見せる前に補助検索を終了する。複数設備では対象ごとに照合し、IDを混ぜず、検索結果にない属性を比較したことにしない。明示的な「関係分析」直接経路の引数は変更しない。

UIが従来形式で先頭へ付けた「調査対象の設備コードは…です。」は、Read Agentでユーザー由来の補足メッセージと質問本文へ分ける。最後の質問本文を独立したuserメッセージとして提示し、本文の明示対象を過去会話・画面選択より優先する。補足は認証・認可・system命令へ昇格させない。「この設備」のように本文が対象を省略した場合だけ画面選択を参照する。原文、再送同一性、API形状、Tool引数の検証は変更しない。
