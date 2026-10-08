# v2 の導入と一括レビューの手順（作業用。終わったら消してよい）

すべて JupyterLab のターミナルで、1 行ずつ打つ。Gemini は使わない。

## 1. Skill を入れる（古いものを消して入れ直す）

```
git clone git@github.com:kanno-tools/sql-requirement-review.git ~/.gemini/skills/sql-requirement-review
```

## 2. 入ったことを確認する

```
ls ~/.gemini/skills/sql-requirement-review/scripts ~/.gemini/skills/sql-requirement-review/references
```

`scripts` に `aggregate.py  run_reviews.sh  split_log.py`、`references` に `batch-review.md  metric-definitions.md  trap-checklist.md  verdict-sheet.md` が出れば v2。

## 3. 必要なライブラリを入れる（初回だけ）

```
pip install pandas openpyxl
```

## 4. 指標の定義表を書く（任意だが推奨）

`~/.gemini/skills/sql-requirement-review/references/metric-definitions.md` を Jupyter で開き、「売上」の行を埋める。分かっている範囲でよい。税と返品が未確定なら「不明」、日付の基準は「購入日（DATE 型・JST 前提）」、備考に「千円単位の丸めは表示ルール」。空欄のままでも動く。

## 5. 作業フォルダを作り、ログを置く

作業フォルダは `project_nl/2_product/sql-requirement-review/` の中に `sql-review` として作る。

```
mkdir -p ~/project_nl/2_product/sql-requirement-review/sql-review
cd ~/project_nl/2_product/sql-requirement-review/sql-review
```

`project_nl` がホーム直下に無ければ、`~/` の部分を実際の場所に読み替える。移動できたか確かめるには `pwd` と打つ。

念のため、親フォルダ `project_nl/2_product/sql-requirement-review/` が git の clone でないことを確認する（`ls -a ..` で `.git` が出なければよい）。clone の中なら、手順 1 の最後で消しているはずなので通常は出ない。

Jupyter のファイル一覧で `sql-review` フォルダにログの xlsx を置く。以下ではファイル名を `log.xlsx` としている。違う名前なら読み替える。

## 6. 一括レビューを回す

```
S=~/.gemini/skills/sql-requirement-review/scripts
python $S/split_log.py --xlsx log.xlsx --out work/
```

「行数 305、レビュー入力 227 件」のような 1 行が出れば分解は成功。列名が違うと「列が見つからない」と出る。

```
bash $S/run_reviews.sh work/ 10
```

10 件だけ回る（10〜20 分）。1 件ごとに `OK req001.md 45s` のような行が出る。終わったら `work/req001_review.md` を Jupyter で開き、判定・ズレ一覧・確認質問が読める形になっているか見る。問題なければ残りを回す。

```
bash $S/run_reviews.sh work/
```

途中で止めても、同じ行をもう一度打てば続きから再開する。

## 7. 集計する

```
python $S/aggregate.py work/
```

`work/summary.md` ができる。見るのは「判定の分布」「直す場所ごとの件数」「人の正誤判定との突き合わせ」の 3 つ。

## 注意

- テーブル定義のファイル（`schema.md`）は今回は省いている。Skill が SQL から推定し、その旨を書く。あとで INFORMATION_SCHEMA から作れば、6 の 1 行目の末尾に ` --schema schema.md` を付けて精度が上がる
- ターミナルで `gemini` が動く状態であること（普段 Gemini CLI を起動しているのと同じターミナルなら大丈夫）
- `work/` の中身（要件・SQL・結果）は git 管理下に置かない
