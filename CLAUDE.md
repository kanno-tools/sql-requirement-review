# sql-requirement-review

## 目標
BigQuery の SQL が営業の質問（業務要件）に答えているかを、SQL を読めない利用者の代わりに判定する Gemini CLI 用 Skill を作る。**Skill は置いた環境だけで動くように作る**（2026-09-29 決定）。実データ・社名・実テーブル名はこのリポジトリに入れない。

## 情報の正（論点 → ファイル）
| 論点 | 正になるファイル |
|---|---|
| レビュー手順・出力形式 | `SKILL.md` |
| 罠の定義・見つけ方 | `references/trap-checklist.md` |
| 指標定義表の雛形 | `references/metric-definitions.md` |
| テストケースと正解 SQL | `tests/cases.yaml` |
| テスト用データ | `tests/datasets.sql`（dojo の複製。編集しない）、`tests/datasets_extra.sql`（独自追加） |
| テスト用のテーブル定義・指標定義 | `tests/schema.md`、`tests/metric-definitions.md` |
| 検出精度の実績と評価手順 | `tests/blind-eval/README.md`（結果表・出力の実物）。README の「テスト」節は要約 |
| 初回試行の手順 | `docs/field-trial.md` |
| 判定票の形式 | `references/verdict-sheet.md` |
| v2 ログ一括レビューの設計・手順 | `references/batch-review.md`。実装は `scripts/`、動作確認は `tests/check_tools.py` |
| 日ごとの整理（非エンジニア向け） | `docs/summaries/<日付>.md` |
| Skill の解説（非エンジニア向け） | `docs/guide.md` |
| 現在地・次にやること・未解決 | `docs/STATUS.md` |
| 作業ログ | `docs/journal.md` |

## 規則
- 記憶は git に置く。**git に入っていない結論は存在しないものとして扱う**
- 数値や結論を会話の記憶から拾わない。必ず上の表のファイルを開く
- 作業前に `docs/STATUS.md` の該当行と実体ファイルを読む。済んでいれば「済んでいる」と返す
- ファイル変更・外部操作・決定を受けたら、手を動かす前に `docs/journal.md` に 1 行書いて push する（形式は同ファイル冒頭）
- journal の日時は `[now]` 行に出た JST だけを使う。推測で書かない
- 結論が出るたびに `/save`。復帰は SessionStart フックの出力で足りなければ `/recall`
- ToolSearch やスキルは必要になるまで読み込まない
- PR を作っても、PR の監視（subscribe）と定期確認（send_later）は付けない。このリポジトリは菅野さん以外触らず CI も無いので、確認は無駄なトークンになる（2026-09-29 決定）。マージ・コメント対応はセッション内の指示で行う
