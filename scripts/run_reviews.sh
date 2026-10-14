#!/usr/bin/env bash
# work/ の reqNNN.md を 1 件ずつ Gemini CLI に渡し、reqNNN_review.md に保存する。
#   bash ~/.gemini/skills/sql-requirement-review/scripts/run_reviews.sh work/ [最大件数] [--runs N]
# - Gemini にファイルを書かせない（標準出力をシェルで保存する）。YOLO は不要
# - 済んだ件は飛ばすので、途中で止めても再開できる
# - bq は実行させない（プロンプトで禁止）
# - --runs N: 同じ依頼を N 回レビューする（2 回目以降は reqNNN_review2.md, reqNNN_review3.md …）。
#   N 回とも「合致」のときだけ合格。判定の揺れを拾うための厳格ゲート。aggregate.py が揺れと合否を集計する
set -u
RUNS=1
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --runs) RUNS="${2:?--runs に回数を指定}"; shift 2;;
    --runs=*) RUNS="${1#*=}"; shift;;
    *) ARGS+=("$1"); shift;;
  esac
done
WORK="${ARGS[0]:?work ディレクトリを指定}"
LIMIT="${ARGS[1]:-0}"
case "$RUNS" in ''|*[!0-9]*|0) echo "--runs は 1 以上の整数: $RUNS"; exit 1;; esac
SKILL_DIR="${SKILL_DIR:-$HOME/.gemini/skills/sql-requirement-review}"
LOG="$WORK/run.log"

read -r -d '' PROMPT <<'P'
標準入力に「レビュー依頼」（要件・SQL・テーブル定義）がある。これを sql-requirement-review スキルでレビューして。
- 手順 5（bq の実行）は行わない。判定の直下と「実行確認」欄は「読解のみ（未実行）」
- 出力は SKILL.md の「出力形式」の全文をそのまま
- その後に 1 行 `---VERDICT---` を置き、続けて references/verdict-sheet.md の形式で判定票を書く（エンジニアの判断欄は空欄のまま含める）
- ファイルは書かない。前置き・後書き・英語の再説明を出さない
P

# k 回目の出力ファイル名（1 回目は従来どおり _review.md）
outname() { if [ "$2" -eq 1 ]; then echo "${1%.md}_review.md"; else echo "${1%.md}_review$2.md"; fi; }
verdict_of() { sed -n 's/^## 判定[:：][[:space:]]*\(合致\|要確認\|不一致\).*/\1/p' "$1" | head -n 1; }

done_n=0; pass_n=0; fail_n=0
for f in "$WORK"/req*.md; do
  case "$f" in *_review*.md) continue;; esac
  [ -e "$f" ] || { echo "req*.md が無い: $WORK"; exit 1; }
  all_done=1
  for k in $(seq 1 "$RUNS"); do [ -s "$(outname "$f" "$k")" ] || all_done=0; done
  if [ "$all_done" -eq 1 ]; then continue; fi
  if [ "$LIMIT" -gt 0 ] && [ "$done_n" -ge "$LIMIT" ]; then break; fi
  verdicts=""
  ng=0
  for k in $(seq 1 "$RUNS"); do
    out="$(outname "$f" "$k")"
    if [ ! -s "$out" ]; then
      start=$(date +%s)
      if gemini -p "$PROMPT" < "$f" > "$out.tmp" 2>>"$LOG" && grep -q '^## 判定' "$out.tmp"; then
        mv "$out.tmp" "$out"
        echo "$(date '+%F %T') OK  $(basename "$out") $(( $(date +%s) - start ))s" | tee -a "$LOG"
      else
        echo "$(date '+%F %T') NG  $(basename "$out") 判定が見つからない。$out.tmp を確認" | tee -a "$LOG"
        ng=1
        break
      fi
    fi
    verdicts="$verdicts${verdicts:+/}$(verdict_of "$out")"
  done
  if [ "$RUNS" -gt 1 ] && [ "$ng" -eq 0 ]; then
    case "$verdicts" in
      *要確認*|*不一致*) gate="不合格"; fail_n=$((fail_n + 1));;
      *) gate="合格"; pass_n=$((pass_n + 1));;
    esac
    echo "$(date '+%F %T') $(basename "$f") 判定 $verdicts → $gate（$RUNS 回とも合致で合格）" | tee -a "$LOG"
  fi
  done_n=$((done_n + 1))
done
remain=$(ls "$WORK"/req*.md 2>/dev/null | grep -v '_review' | while read -r r; do
  for k in $(seq 1 "$RUNS"); do [ -s "$(outname "$r" "$k")" ] || { echo x; break; }; done; done | wc -l)
echo "今回 $done_n 件。未処理: $remain 件"
if [ "$RUNS" -gt 1 ]; then echo "今回の合否: 合格 $pass_n 件、不合格 $fail_n 件（判定の内訳は aggregate.py の summary.md）"; fi
