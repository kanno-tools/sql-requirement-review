# やり取りの置き場

Skill の管理側と、Skill を使う環境側の設計担当（Gemini CLI）が、このフォルダを通じて文書で意見交換する。公開リポジトリなので、**固有名（会社名・得意先名・プロジェクト ID・データセット名・表名・列名・コード値・金額）は書かない。** 構造の言葉（「取引の正本の表」「金額列が 1 本だけ」「除外条件」）で書く。

## ファイル名

- 管理側 → 設計担当: `docs/replies/<日付>-to-agent-designer.md`
- 設計担当 → 管理側: `docs/replies/<日付>-from-agent-designer.md`

同じ日に複数あれば末尾に `-2` を付ける。

## 設計担当が書く時の手順

1. `~/.gemini/skills/sql-requirement-review` で `git pull`
2. `git switch -c reply/<日付>` でブランチを切る（main には直接 push しない）
3. `docs/replies/<日付>-from-agent-designer.md` を書く。宛先の文書（`-to-` のファイル）の見出しに沿って答える
4. 書き終えたら、固有名が混ざっていないか読み返す
5. `git add docs/replies/<日付>-from-agent-designer.md` → commit → `git push -u origin reply/<日付>`。**`git add -A` は使わない**（記入済みの定義表やレビュー結果を巻き込む）
6. 利用者が PR を作り、diff を見てからマージする

## 管理側が読む時

`git fetch origin` で `reply/<日付>` ブランチを取り、ファイルを読む。返答は `-to-` のファイルに書き、PR 経由で main に入れる。
