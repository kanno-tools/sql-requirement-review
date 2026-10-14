"""reqNNN_review.md（レビュー結果＋判定票）を集計し、「直す場所 → 件数 → 該当行」の形にまとめる。

    python ~/.gemini/skills/sql-requirement-review/scripts/aggregate.py work/ [--out work/summary.md]

出力: summary.md（人が読む）と rows.csv（1 行 1 レビュー。判定・該当した T・正誤判定との一致）。
目的はエージェントの育成なので、集計は「どこを直せば何件減るか」に寄せる。
"""
import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

# 罠 ID → 直す場所。エージェント側で直せる場所ごとに束ねる
FIX_PLACES = [
    ("用語集・指標定義（税・返品・指標の計算式）", ["T09", "T08"]),
    ("スキーマの説明文・表と列の選択", ["T13"]),
    ("日付・時刻のルール（システムプロンプト）", ["T06", "T07"]),
    ("要件の解釈ルール（集計単位・件数・上位 N・比率）", ["T02", "T04", "T05", "T11", "T12"]),
    ("表の構造の知識（結合・重複・スナップショット）", ["T01", "T10", "T14"]),
    ("NULL・文字列の扱い", ["T03", "T15"]),
]
T_IDS = [f"T{i:02d}" for i in range(1, 16)]
CORRECT = {"○", "〇", "正", "正解", "ok", "true", "1", "合致", "正しい"}
INCORRECT = {"×", "✕", "誤", "不正解", "ng", "false", "0", "不一致", "間違い", "誤り"}


def parse_review(text: str) -> dict:
    d = {"verdict": "", "T": {}, "n_questions": 0, "undefined": None, "unknown": None,
         "high": None, "mid": None, "low": None, "parsed": False}
    m = re.search(r"^## 判定[:：]\s*(合致|要確認|不一致)", text, re.M)
    if m:
        d["verdict"] = m.group(1)
    marker = "---VERDICT---" if "---VERDICT---" in text else ("---CARRY---" if "---CARRY---" in text else None)
    carry = text.split(marker, 1)[1] if marker else text
    for t in T_IDS:
        mt = re.search(rf"^\|\s*{t}\s*\|\s*([^|]*)\|", carry, re.M)
        if mt:
            v = mt.group(1).strip()
            d["T"][t] = "該当" if v.startswith("該当") and not v.startswith("該当なし") else ("不明" if v.startswith("不明") else "該当なし")
    if d["T"]:
        d["parsed"] = True
    mq = re.search(r"確認質問の数[:：]\s*(\d+)", carry)
    if mq:
        d["n_questions"] = int(mq.group(1))
    mu = re.search(r"「定義なし」になった指標の数[:：]\s*(\d+)", carry)
    if mu:
        d["undefined"] = int(mu.group(1))
    mk = re.search(r"「不明」になった要素の数[:：]\s*(\d+)", carry)
    if mk:
        d["unknown"] = int(mk.group(1))
    ms = re.search(r"高／中／低）[:：]\s*(\d+)／(\d+)／(\d+)", carry)
    if ms:
        d["high"], d["mid"], d["low"] = (int(x) for x in ms.groups())
    return d


def norm_label(v: str) -> str:
    s = str(v).strip().lower()
    if not s:
        return ""
    if s in CORRECT:
        return "正"
    if s in INCORRECT:
        return "誤"
    return "その他"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--out")
    args = ap.parse_args()
    work = Path(args.work)
    out = Path(args.out) if args.out else work / "summary.md"

    meta = {r["id"]: r for r in csv.DictReader((work / "meta.csv").open(encoding="utf-8")) if r["id"]}
    rows, unparsed, missing = [], [], []
    for rid, m in sorted(meta.items()):
        f = work / f"{rid}_review.md"
        if not f.exists():
            missing.append(rid)
            continue
        d = parse_review(f.read_text(encoding="utf-8"))
        if not d["parsed"] or not d["verdict"]:
            unparsed.append(rid)
        hit = [t for t, v in d["T"].items() if v == "該当"]
        unk = [t for t, v in d["T"].items() if v == "不明"]
        label = norm_label(m["label"])
        pred = {"合致": "正", "不一致": "誤"}.get(d["verdict"], "要確認")
        agree = "" if not label or label == "その他" else ("一致" if pred == label else ("保留" if pred == "要確認" else "不一致"))
        rows.append({**m, "verdict": d["verdict"], "T_hit": " ".join(hit), "T_unknown": " ".join(unk),
                     "n_questions": d["n_questions"], "undefined": d["undefined"], "unknown_elems": d["unknown"],
                     "high": d["high"], "mid": d["mid"], "low": d["low"], "label_norm": label, "agreement": agree})

    with (work / "rows.csv").open("w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    L = []
    L.append(f"# 集計（{len(rows)} 件のレビュー、未実施 {len(missing)} 件、読めなかった {len(unparsed)} 件）\n")
    vc = Counter(r["verdict"] for r in rows)
    L.append("## 判定の分布")
    L.append("| 判定 | 件数 | 割合 |\n|---|---|---|")
    for k in ["合致", "要確認", "不一致", ""]:
        if vc.get(k):
            L.append(f"| {k or '（判定なし）'} | {vc[k]} | {vc[k] / len(rows):.0%} |")

    L.append("\n## 直す場所ごとの件数（該当した罠 ID）")
    L.append("| 直す場所 | 罠 ID | 該当した行数 | 不明の行数 | 該当行 |\n|---|---|---|---|---|")
    for place, ts in FIX_PLACES:
        hit_ids = [r["id"] for r in rows if any(t in r["T_hit"].split() for t in ts)]
        unk_ids = [r["id"] for r in rows if any(t in r["T_unknown"].split() for t in ts)]
        L.append(f"| {place} | {' '.join(ts)} | {len(hit_ids)} | {len(unk_ids)} | {' '.join(hit_ids[:20])}{' …' if len(hit_ids) > 20 else ''} |")

    L.append("\n## 罠 ID ごとの件数")
    L.append("| T | 該当 | 不明 |\n|---|---|---|")
    for t in T_IDS:
        h = sum(1 for r in rows if t in r["T_hit"].split())
        u = sum(1 for r in rows if t in r["T_unknown"].split())
        if h or u:
            L.append(f"| {t} | {h} | {u} |")

    def breakdown(title, key, fmt=lambda v: v):
        L.append(f"\n## {title}")
        L.append("| 区分 | 件数 | 合致 | 要確認 | 不一致 |\n|---|---|---|---|---|")
        g = defaultdict(Counter)
        for r in rows:
            g[fmt(r[key])][r["verdict"]] += 1
        for k in sorted(g):
            c = g[k]
            L.append(f"| {k} | {sum(c.values())} | {c['合致']} | {c['要確認']} | {c['不一致']} |")

    breakdown("部署別", "department")
    breakdown("ユーザー別", "user")
    breakdown("月別", "timestamp", lambda v: str(v)[:7])
    breakdown("SQL 本数別（1 本 ／ 複数＝書き直しの跡）", "n_sql", lambda v: "1 本" if str(v) == "1" else "複数")
    breakdown("ターン別（1＝会話の最初 ／ 2 以上＝引き継ぎあり）", "rally", lambda v: "1" if str(v) == "1" else "2 以上")
    breakdown("エラー言及の有無（生レスポンス）", "error_mention", lambda v: "あり" if str(v) == "True" else "なし")

    labeled = [r for r in rows if r["label_norm"] in ("正", "誤")]
    L.append(f"\n## 人の正誤判定との突き合わせ（判定あり {len(labeled)} 件）")
    if labeled:
        L.append("| 人の判定 ＼ Skill | 合致 | 要確認 | 不一致 |\n|---|---|---|---|")
        for lab in ["正", "誤"]:
            c = Counter(r["verdict"] for r in labeled if r["label_norm"] == lab)
            L.append(f"| {lab} | {c['合致']} | {c['要確認']} | {c['不一致']} |")
        dis = [r for r in labeled if r["agreement"] == "不一致"]
        L.append(f"\n**先に読む行（人と Skill が食い違う {len(dis)} 件）**: " + (" ".join(f"{r['id']}（人={r['label_norm']}, Skill={r['verdict']}）" for r in dis) or "なし"))
    else:
        L.append("正誤判定が付いた行が無い")

    q = sum(r["n_questions"] for r in rows)
    L.append(f"\n## その他\n- 確認質問の合計: {q} 問（1 件あたり {q / len(rows):.1f}）" if rows else "")
    if unparsed:
        L.append(f"- 読めなかったレビュー（形式が崩れている）: {' '.join(unparsed)}")
    if missing:
        L.append(f"- 未実施: {len(missing)} 件（run_reviews.sh を再実行）")
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{out} と {work / 'rows.csv'} を書いた（{len(rows)} 件）")


if __name__ == "__main__":
    main()
