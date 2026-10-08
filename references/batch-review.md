# ログの一括レビュー（v2）: 直す場所を出す

目的は**チームでエージェントを育てること**。ログの SQL を 1 本ずつこの Skill で判定し、「どこを直せば何件減るか」を出す。

**Gemini への指示**: 「ログ（xlsx）を一括でレビューして」と言われたら、xlsx を自分で読まない（行の切れ目・複数 SQL・セル内改行の解釈を LLM がすると壊れる）。下の A→B→C を `scripts/` のプログラムで実行する。B は自分の会話の中で 1 件ずつ読んで判定しない（文脈が溢れる）。`scripts/run_reviews.sh` が `gemini -p` を 1 件ごとに別プロセスで起動する。

## 3 段

| 段 | 何が | 誰が | 入力 → 出力 |
|---|---|---|---|
| A 分解 | `scripts/split_log.py` | Python | ログ xlsx → `work/reqNNN.md`（1 行 1 件）＋ `work/meta.csv` |
| B 判定 | `scripts/run_reviews.sh` | Gemini CLI（1 件 1 回） | `reqNNN.md` → `reqNNN_review.md`（レビュー結果＋判定票） |
| C 集計 | `scripts/aggregate.py` | Python | `*_review.md` ＋ `meta.csv` → `summary.md`・`rows.csv` |

設計の理由:
- **LLM に xlsx を読ませない。** 行の切れ目・複数 SQL・セル内改行の解釈はプログラムで確定的に行う。LLM が見るのは 1 件分だけ
- **要件は同じセッションの過去の質問をつなげて作る。** 3 分の 2 のセッションが複数ターンで、後のターンの質問は「それを店舗別で」のような省略形（中央値 50 字）。エージェントは過去ターンを見て SQL を書いているので、レビュー側にも同じ情報を渡さないと突き合わせが成立しない。「今回の質問」は明示し、過去分は文脈と書く。`--context turn` でつながない比較もできる
- **エージェントの回答文はレビュー入力に入れない。** 入れると回答に引きずられ、「SQL だけから何の質問に答えているかを書く」手順が崩れる
- **1 行に複数 SQL がある時は最後の 1 本を対象にする**（書き直しの跡。最後が回答に使われた可能性が最も高い）。本数は meta に残す。`--sql all` で全部も可
- **Gemini にファイルを書かせない。** 標準出力をシェルで保存する。YOLO 不要。bq も実行させない
- **1 行 1 ファイル。** 判定票は同じファイルの `---VERDICT---` 以降。集計はそこだけ読む
- **重複除去はしない。** エージェントは毎回ほぼ違う SQL を書くので（実測で 227 本中 221 種類）、型でまとめても減らない

## 手順

前提: Skill を `~/.gemini/skills/sql-requirement-review/` に置き（`scripts/` も一緒に入る）、`references/metric-definitions.md` を記入してある。作業ディレクトリは git の外（例: `~/sql-review/`）。ターミナルから打つ（Gemini の会話の中で打ってもよいが、B は必ず `run_reviews.sh` 経由）。

```bash
pip install pandas openpyxl
S=~/.gemini/skills/sql-requirement-review/scripts
# A. 分解（テーブル定義 schema.md は INFORMATION_SCHEMA から作っておく。無ければ --schema を省く）
python $S/split_log.py --xlsx log.xlsx --out work/ --schema schema.md
# B. まず 10 件だけ回して出来を見る → 問題なければ全件（途中で止めても再開できる）
bash $S/run_reviews.sh work/ 10
bash $S/run_reviews.sh work/
# C. 集計
python $S/aggregate.py work/
```

列名が違う時は `--col-timestamp 列1` のように指定する。他のシートに `正誤判定` 列があれば、セッション ID とターン番号で突き合わせて自動で取り込む。

## summary.md の読み方

1. **判定の分布**: 不一致の割合がエージェントの「数字が違う」率の上限
2. **直す場所ごとの件数**: ここが本題。用語集（T09・T08）、スキーマの説明文（T13）、日付ルール（T06・T07）、要件の解釈ルール（T02・T04・T05・T11・T12）、表の構造の知識（T01・T10・T14）、NULL・文字列（T03・T15）。件数が多い場所から直す
3. **人の正誤判定との突き合わせ**: 「先に読む行」＝人と Skill が食い違った行。Skill の誤りか人の見落としかを 1 件ずつ見る。ここが Skill の実データでの精度
4. **SQL 本数別・ターン別・エラー言及**: 書き直しが多い行、引き継ぎのある行、エラーが出た行で判定が悪化していないか

## コストの目安

1 件あたり Skill 一式＋テーブル定義＋依頼で 1.5 万トークン前後、出力 3 千。227 件で 350 万トークン程度、時間は逐次で 2〜4 時間。BigQuery は読まない（bq 禁止）。

## 結果の扱い

`summary.md`・`rows.csv`・`reqNNN_review.md` はすべてこの環境の中で使う。用語集・システムプロンプト・スキーマ説明の修正はここから起こす。「先に読む行」を 1 件ずつ見て、判定票のエンジニア欄を埋めると、次の回で Skill と人の一致率が測れる。
