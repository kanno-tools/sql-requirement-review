#!/usr/bin/env bash
# work/ の reqNNN.md を 1 件ずつ Gemini CLI に渡し、reqNNN_review.md に保存する。
#   bash ~/.gemini/skills/sql-requirement-review/scripts/run_reviews.sh work/ [最大件数]
# - Gemini にファイルを書かせない（標準出力をシェルで保存する）。YOLO は不要
# - 済んだ件は飛ばすので、途中で止めても再開できる
# - bq は実行させない（プロンプトで禁止）
set -u
WORK="${1:?work ディレクトリを指定}"
LIMIT="${2:-0}"
SKILL_DIR="${SKILL_DIR:-$HOME/.gemini/skills/sql-requirement-review}"
LOG="$WORK/run.log"

read -r -d '' PROMPT <<'P'
標準入力に「レビュー依頼」（要件・SQL・テーブル定義）がある。これを sql-requirement-review スキルでレビューして。
- 手順 5（bq の実行）は行わない。判定の直下と「実行確認」欄は「読解のみ（未実行）」
- 出力は SKILL.md の「出力形式」の全文をそのまま
- その後に 1 行 `---VERDICT---` を置き、続けて references/verdict-sheet.md の形式で判定票を書く（エンジニアの判断欄は空欄のまま含める）
- ファイルは書かない。前置き・後書き・英語の再説明を出さない
P

done_n=0
for f in "$WORK"/req[0-9][0-9][0-9].md; do
  [ -e "$f" ] || { echo "req*.md が無い: $WORK"; exit 1; }
  out="${f%.md}_review.md"
  if [ -s "$out" ]; then continue; fi
  if [ "$LIMIT" -gt 0 ] && [ "$done_n" -ge "$LIMIT" ]; then break; fi
  start=$(date +%s)
  if gemini -p "$PROMPT" < "$f" > "$out.tmp" 2>>"$LOG" && grep -q '^## 判定' "$out.tmp"; then
    mv "$out.tmp" "$out"
    echo "$(date '+%F %T') OK  $(basename "$f") $(( $(date +%s) - start ))s" | tee -a "$LOG"
  else
    echo "$(date '+%F %T') NG  $(basename "$f") 判定が見つからない。$out.tmp を確認" | tee -a "$LOG"
  fi
  done_n=$((done_n + 1))
done
echo "今回 $done_n 件。未処理: $(ls "$WORK"/req[0-9][0-9][0-9].md 2>/dev/null | while read -r r; do [ -s "${r%.md}_review.md" ] || echo x; done | wc -l) 件"
