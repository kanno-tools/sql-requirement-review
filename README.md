# sql-requirement-review

BigQuery の SQL が業務要件（営業の質問）と合っているかをレビューする、Gemini CLI / Claude Code 用の Skill。
AI エージェントやエンジニアが書いた SQL を、要件の分解 → SQL の逆翻訳 → 突き合わせ → 罠チェック（15 項目）→ 読み取り専用の実行確認 の順で点検し、判定（合致／要確認／不一致）・ズレ一覧・エンジニアへの確認質問を返す。

**このリポジトリに実データ・社名・実テーブル名は含まない。** テストは架空の化粧品卸「ミツキ化粧品」のデータ（`tests/datasets.sql`、[sql-reading-dojo](https://github.com/KANNOHI1/sql-reading-dojo) から複製）で行う。

## 構成

```
skill/                          ← 配布するのはここだけ
  SKILL.md                      手順と出力形式
  references/trap-checklist.md  罠 15 項目（見つけ方・Alteryx 対応・典型的な被害）
  references/metric-definitions.md  指標定義表の雛形（使う環境で記入する）
  references/verdict-sheet.md   判定票（集計用の固定形式）
  references/batch-review.md    ログ（xlsx）の一括レビューの設計と手順（v2）
  scripts/                      v2 の分解・判定・集計のプログラム（Skill と一緒にコピーされる）
tests/
  cases.yaml                    罠入り SQL 15 本 + 正しい SQL 10 本（罠に見えるが正しいもの）
  datasets.sql                  架空データ（sql-reading-dojo の複製）
  datasets_extra.sql            このリポジトリ独自の追加表（T14 用の sales_raw）
  check_cases.py                ケース自体の正しさを DuckDB で検証
  make_blind_inputs.py          ブラインド評価の入力（答え抜き）を作る
  blind-eval/                   ブラインド評価の手順・結果表・出力の実物
  schema.md / metric-definitions.md  テスト用のテーブル定義・指標定義
docs/
  guide.md                      非エンジニア向けの解説（何か・挙動・使い方）
  field-trial.md                初回試行の手順と判定票の使い方
  STATUS.md                     現在地・次にやること・未解決（状態の正）
  journal.md                    作業ログ
CLAUDE.md                       規則と「情報の正」の表（毎セッション自動で読まれる）
.claude/                        /save /recall コマンドと SessionStart フック
```

## 配置（Gemini CLI）

```bash
git clone https://github.com/KANNOHI1/sql-requirement-review.git
mkdir -p ~/.gemini/skills/sql-requirement-review
cp -r sql-requirement-review/skill/. ~/.gemini/skills/sql-requirement-review/
rm -rf sql-requirement-review          # clone は Skill をコピーしたら消す（下記）
```

Gemini CLI を再起動し、`/skills` に `sql-requirement-review` が出ることを確認する。Claude Code なら `~/.claude/skills/` に同じ形で置く。

**要件・SQL・結果のファイルは、このリポジトリの clone の中に置かない。** clone の中に置くと、後で `git add -A` → push した時にレビュー対象のデータが公開リポジトリに載る。Skill をコピーしたら clone は消し、レビュー作業は別の場所（例: `~/sql-review/`）で行う。万一 clone の中で作業しても、`.gitignore` で `req*.md`・`*_result.md`・`*_carry.md` は追跡対象外にしてあるが、これは最後の保険であって前提にしない。

## 使い方

要件と SQL を 1 ファイル（例: `req01.md`）に置き、

```
@req01.md を sql-requirement-review スキルでレビューして。結果は req01_result.md に保存して
```

`bq` が使える環境では dry run と件数確認まで行う。実行は SELECT と `--dry_run` に限る（SKILL.md 手順 5）。

実際の要件と SQL で試すときは `docs/field-trial.md` の手順で行う。エージェントのログ（xlsx）を一括でレビューするなら `references/batch-review.md`（v2。`pip install pandas openpyxl` が要る）。

## テスト

```bash
pip install duckdb pyyaml
python tests/check_cases.py
```

罠入りケースは正解 SQL と結果が違うこと、正しいケースは一致することを確かめる（ケース自体の嘘を防ぐ）。Skill の検出精度は、答えを伏せた別モデルに SKILL.md どおりレビューさせて測った（v1: C01〜C12・K01〜K02 は 14/14 × 2 周。C13〜C15 は 2026-09-29 に追加し 3/3 × 1 周。正しい SQL の K03〜K10 は同日に追加し 8/8 合致・誤検出ゼロ × 1 周）。手順と出力の実物は `tests/blind-eval/` にある。
