"""答え合わせリスト（eval_set.csv）から、レビュー依頼（reqNNN.md）を作る入力アダプタ。

    # 改修した候補 SQL を id 105 の要件に対してレビューする
    python split_eval.py --csv eval_set.csv --id 105 --candidate fixed.sql --out work/ [--schema schema.md] [--definitions definitions.md]
    # 候補を id ごとのファイル（<id>.sql）から取る
    python split_eval.py --csv eval_set.csv --id all --candidate-dir fixes/ --out work/
    # 精度測定: 期待 SQL そのものをレビューさせる（すべて「合致」になるべき）
    python split_eval.py --csv eval_set.csv --id all --review-expected --out work/

要件は user_question ＋ prompt_intent ＋ expected_output_definition から組み立てる。
期待 SQL は（--review-expected 以外では）依頼に入れない。入れるとレビューが期待 SQL に引きずられる。
あとは run_reviews.sh と aggregate.py がそのまま使える。
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reqbuild import build_body  # noqa: E402

COLS = {"id": "id", "question": "user_question", "intent": "prompt_intent",
        "expected_def": "expected_output_definition", "expected_sql": "expected_sql",
        "version": "definitions_version", "source": "source", "added": "added_date", "last": "last_result"}


def requirement_text(row: dict) -> str:
    parts = ["**質問**", row.get(COLS["question"], "").strip()]
    intent = row.get(COLS["intent"], "").strip()
    if intent:
        parts += ["", "**意図**", intent]
    exp = row.get(COLS["expected_def"], "").strip()
    if exp:
        parts += ["", "**期待する答えの要点**（粒度・指標・絞り込みの指定として扱う）", exp]
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--id", required=True, help="eval_set の id。複数はカンマ区切り。all で全件")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--candidate", help="レビューする SQL ファイル（--id が 1 件の時）")
    g.add_argument("--candidate-dir", help="<id>.sql を置いたディレクトリ")
    g.add_argument("--review-expected", action="store_true", help="期待 SQL そのものをレビューする（精度測定用）")
    ap.add_argument("--schema")
    ap.add_argument("--definitions")
    ap.add_argument("--no-filter", action="store_true")
    args = ap.parse_args()

    rows = {r[COLS["id"]].strip(): r for r in csv.DictReader(Path(args.csv).open(encoding="utf-8"))}
    ids = list(rows) if args.id == "all" else [i.strip() for i in args.id.split(",")]
    if args.candidate and len(ids) != 1:
        raise SystemExit("--candidate は --id が 1 件の時だけ。複数なら --candidate-dir")
    schema = Path(args.schema).read_text(encoding="utf-8") if args.schema else None
    definitions = Path(args.definitions).read_text(encoding="utf-8") if args.definitions else None
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    meta, n = [], 0
    for eid in ids:
        if eid not in rows:
            print(f"id {eid} が無い。飛ばす")
            continue
        r = rows[eid]
        if args.review_expected:
            sql, mode = r.get(COLS["expected_sql"], ""), "expected"
        elif args.candidate:
            sql, mode = Path(args.candidate).read_text(encoding="utf-8"), "candidate"
        else:
            f = Path(args.candidate_dir) / f"{eid}.sql"
            if not f.exists():
                print(f"id {eid}: {f} が無い。飛ばす")
                continue
            sql, mode = f.read_text(encoding="utf-8"), "candidate"
        if not sql.strip():
            print(f"id {eid}: SQL が空。飛ばす")
            continue
        rid = f"req{int(eid):03d}" if eid.isdigit() else f"req_{eid}"
        note = "精度測定: 期待 SQL そのものをレビューしている" if mode == "expected" else None
        (out / f"{rid}.md").write_text(
            build_body(rid, requirement_text(r), sql, schema, definitions, note=note, filter_tables=not args.no_filter),
            encoding="utf-8")
        meta.append({"id": rid, "eval_id": eid, "mode": mode, "sql_chars": len(sql),
                     "definitions_version": r.get(COLS["version"], ""), "source": r.get(COLS["source"], ""),
                     "added_date": r.get(COLS["added"], ""), "last_result": r.get(COLS["last"], ""),
                     "label": "", "timestamp": r.get(COLS["added"], "")})
        n += 1
    with (out / "meta.csv").open("w", newline="", encoding="utf-8") as f:
        if meta:
            w = csv.DictWriter(f, fieldnames=list(meta[0].keys()))
            w.writeheader()
            w.writerows(meta)
    print(f"レビュー入力 {n} 件 → {out}/")


if __name__ == "__main__":
    main()
