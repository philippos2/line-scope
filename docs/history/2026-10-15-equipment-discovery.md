# 設備名から調査対象を選ぶ導線

仕様正本ではなく作業記録。

#243のmerge（c8c5f6c）を確認しmainをff-only更新。M-204中心で設備コード暗記を前提にしているという開発者の指摘を受け、既存設備検索結果を使う対象選択を次工程に選んだ。正式入力のPO-B01〜08は未承認のまま保ち、業務入力・新権限は追加していない。

## 変更

- 「設備を探す」で検索文の下書き、明示送信後に直近search_equipmentの名前・コード候補を表示。候補選択でIDを含む現在状態・下流調査文へ反映し、入力欄へfocus。選択だけでは送信・Prepareしない。
- 別対象の選択・新しい検索・固定比較デモは前のcontextを使わない。通常の問い合わせ継続は既存contextを維持。サーバで存在・認可を再検証する。
- 取得済み候補を全工場一覧・現在状態としない。続きあり・空・不正形・古い結果を明示。処理中や再調査失敗後の候補選択を無効化。名称・コードからHTMLを実行しない。
- 比較デモはM-204固定と表示。実検索は既存POST /agentで、新APIや架空の場所・ライン・状態は追加していない。
- 開発者から前回の工程図がガントに見えないと指摘。状態表を撤去し、16本を中心とする累積PR枠の横棒SVGに置換。実日程・作業時間の見積もりではないと明記し、PO着手条件と品質回帰・総合受入の順序を説明した。12〜20 PRの暫定見積もりと動画の本体完成後という順序は維持。

## 検証と途中経過

frontend-architecture / frontend-verificationを適用。追加Unitは4件（選択後の明示送信・context分離、空候補、続き＋古い候補の無効化、HTMLと不正形）で、既存を含む22件通過。無条件の直積追加はしていない。

lintでブラウザスクリプトのURL global参照、型チェックでTesting LibraryにPlaywright用exactオプションを使った誤り、format差分を検出し修正。

初回の実モデル付き通し確認は、ブラウザ起動前の既存HTTP確認が15秒でtimeout。実モデル指定時だけHTTP側を90秒にし、既存Agent予算60秒を待てるよう補助スクリプトを修正した。サーバの時間制限・合格条件は緩和しない。モデル自動取得やmockへの自動fallbackも行わない。

## 未受入範囲

候補検索はLLMのTool選択に依存する。全設備を起動時に取得する一覧、ページ自動取得、ライン・場所検索、新たなダミー設備の増設はしていない。一般LLM品質・正式入力のモック置換・全BS / Goldenは残工程。継続デモへの反映と使い捨て環境での検証を区別する。

実ブラウザ再確認で検索ToolはHTTP 200まで成功したが、候補表示で失敗。設備名の返却fieldはequipment_nameであり、UIとUnit fixtureでnameと取り違えていたため修正した。不正形の候補として表示を拒否しており、別対象の誤選択はしていない。Unit fixtureも実DTOに合わせ再検証した。固定値だけのUnit成功を実API接続の成功と扱わない。比較デモの既存Tab操作を保つfocusの調整も行った。

工程SVGはChromiumで描画して確認。横棒・ラベル・PO条件に文字切れがないことを確認した。

## 最終ローカル結果

- 修正後のFrontend lint・型・format・build成功、Unitは22 passed（追加4件、1.53秒）。補助Pythonのruff check / format成功。
- `python3 scripts/verify_frontend_flow.py --docker-group docker --llm-model qwen3:30b-a3b-instruct-2507-q4_K_M`がPASS。実Chromium / HTTP / PG / Neo4jでM-204・M-208の名称候補を取得し、M-208の選択によるID付き下書き・focus・自動送信なしを確認。選択後の送信bodyとcontext分離はUnitで検証し、実モデルのM-208下流回答品質の受入とはしない。
- 既存の比較・Graph・引用・4カテゴリのPrepare/Approval/Execute・拒否・identity切替・keyboard・幅別確認もPASS。検索はREAL_LLM_SEARCH、引用はMOCK_EMBEDDING_QDRANT、比較条件はMOCK_FIXTURE。実Embeddingや一般LLM品質の評価成功とは混同しない。
- 成功ログは/tmp/linescope-equipment-browser-final.log。失敗した初回と再確認も別ログに保持。試験専用Composeのvolumeと一時browser image・container・資格情報を片付け済み。継続デモにはデプロイしていない。
- PR #244を作成。最新headのCI件数・hash・required checksと片付けを確認してPR本文へ追記する。

開発者の指摘を受け、直近#227〜242のPRタイトルがscopeなしの運用であることを確認した。#244を`feat: 設備名の候補から調査対象を選ぶ導線を追加する`へ修正し、CONTRIBUTINGにscopeを付けない運用を記録。push済みcommitは書き換えず、以後のPRタイトルへ適用する。
