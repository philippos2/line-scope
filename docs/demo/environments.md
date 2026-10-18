# ブラウザ確認環境

現在の確認先をこの表で区別する。過去の履歴にあるポートは当時の記録であり、現在の接続先を示さない。

| ブラウザ | Compose project | API | データ | UI |
|---|---|---|---|---|
| http://localhost:5174 | linescope-s1-availability-preview-20261019 | localhost:8003 | A案。M-204停止・M-208稼働中。R-02→M-204のみ必須供給 | PR #265の修正版。利用可能性ゲート・独立表示・サーバ値表示・インフラ名修正 |
| http://localhost:5173 | linescope-scenario1 | localhost:8002 | A案変更前。M-208は稼働中だがR-02への必須依存により利用可能性が不明 | 今回の修正前のUI。比較確認用に保持し、今回切り替えていない |

**今回の修正確認には5174番を使う。5173番の切替は開発依頼者への確認後に行う。** 5174番では従来の接続tokenも使用できる。秘密値は私有envから取得し、文書・Git・画面証拠へ記録しない。

旧二台停止project `linescope-incident-demo` は削除済みで、上記の5173番とは別物。`linescope-browser-demo` は既存の別projectで、今回起動・停止・再投入していない。

A案のデータ形式と初期投入は[scenario1.md](scenario1.md)、変更順序の記録は[ポートとUIの修正履歴](../history/2026-10-19-ui-availability-and-environments.md)を参照する。
