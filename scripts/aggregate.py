"""reqNNN_review.md（レビュー結果＋判定票）を集計し、「直す場所 → 件数 → 該当行」の形にまとめる。

    python ~/.gemini/skills/sql-requirement-review/scripts/aggregate.py work/ [--out work/summary.md]

出力: summary.md（人が読む）と rows.csv（1 行 1 レビュー。判定・該当した T・要確認の理由・D3 タグ・正誤判定との一致）。
--runs N で複数回レビューした行は、最も厳しい判定を代表にし、全回が合致なら「合格」、判定が回ごとに違えば「揺れ」と記す。
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
# 罠 ID → D3 タグ（摩擦原因の下書き。エージェント育成側の分類）。要確認の理由からも付く（下の reason_to_d3）
D3_TAGS = [
    ("①用語集不足", ["T08", "T09"]),
    ("②データ基盤側の不足・除外漏れ", ["T01", "T10", "T13", "T14"]),
    ("③質問の曖昧さ", []),  # 罠 ID ではなく、要確認の理由（指定なし・解釈複数）から付く
    ("④集計・計算誤り", ["T02", "T03", "T04", "T05", "T06", "T07", "T11", "T12", "T15"]),
]
# 要確認の理由の種別（verdict-sheet.md の 5 つ）→ D3 タグ
REASON_TYPES = ["定義なし", "指定なし", "解釈複数", "型不明", "定義表外"]
REASON_TO_D3 = {"定義なし": "①用語集不足", "指定なし": "③質問の曖昧さ", "解釈複数": "③質問の曖昧さ",
                "型不明": "②データ基盤側の不足・除外漏れ", "定義表外": "②データ基盤側の不足・除外漏れ"}
VERDICT_RANK = {"合致": 0, "": 1, "要確認": 2, "不一致": 3}
T_IDS = [f"T{i:02d}" for i in range(1, 16)]
CORRECT = {"○", "〇", "正", "正解", "ok", "true", "1", "合致", "正しい"}
INCORRECT = {"×", "✕", "誤", "不正解", "ng", "false", "0", "不一致", "間違い", "誤り"}


def parse_review(text: str) -> dict:
    d = {"verdict": "", "T": {}, "n_questions": 0, "undefined": None, "unknown": None,
         "high": None, "mid": None, "low": None, "parsed": False, "reasons": []}
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
    # 見出しの括弧の中にも「:」「／」があるので、括弧を読み飛ばしてから値を取る
    mr = re.search(r"要確認にした理由(?:（[^）\n]*）)?[ \t]*[:：][ \t]*(.*)", carry)
    if mr:
        d["reasons"] = parse_reasons(mr.group(1))
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


def parse_reasons(text: str) -> list[tuple[str, str]]:
    """「定義なし: 売上（税）／指定なし: 期間」→ [("定義なし", "売上（税）"), ("指定なし", "期間")]。種別外は「その他」"""
    out = []
    for part in re.split(r"[／/]", text.strip()):
        part = part.strip().strip("。")
        if not part:
            continue
        m = re.match(r"\s*(\S+?)\s*[:：]\s*(.*)", part)
        kind, target = (m.group(1), m.group(2).strip()) if m else (part, "")
        if kind not in REASON_TYPES:
            kind, target = "その他", part
        out.append((kind, target))
    return out


def d3_tags(hits: list[str], verdict: str, reasons: list[tuple[str, str]], unknown_elems) -> list[str]:
    tags = []
    for tag, ts in D3_TAGS:
        if any(t in hits for t in ts):
            tags.append(tag)
    if verdict == "要確認":
        for kind, _ in reasons:
            t = REASON_TO_D3.get(kind)
            if t and t not in tags:
                tags.append(t)
        # 理由が書かれていない要確認は、突き合わせ表の「不明」があれば質問の曖昧さとみなす
        if not reasons and (unknown_elems or 0) > 0 and "③質問の曖昧さ" not in tags:
            tags.append("③質問の曖昧さ")
    return [t for t, _ in D3_TAGS if t in tags]


def review_files(work: Path, rid: str) -> list[Path]:
    """reqNNN_review.md, reqNNN_review2.md, … を順に（--runs N の出力）。途切れたところまで"""
    files = []
    k = 1
    while True:
        f = work / (f"{rid}_review.md" if k == 1 else f"{rid}_review{k}.md")
        if not f.exists():
            break
        files.append(f)
        k += 1
    return files


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
    reason_pairs = {}  # id → [(種別, 対象)]
    for rid, m in sorted(meta.items()):
        files = review_files(work, rid)
        if not files:
            missing.append(rid)
            continue
        runs = [parse_review(f.read_text(encoding="utf-8")) for f in files]
        if any(not r["parsed"] or not r["verdict"] for r in runs):
            unparsed.append(rid)
        # 複数回レビュー（--runs N）は最も厳しい判定を代表にし、罠・理由は全回の和をとる
        d = max(runs, key=lambda r: VERDICT_RANK.get(r["verdict"], 1))
        verdict_runs = "/".join(r["verdict"] or "？" for r in runs)
        hit = sorted({t for r in runs for t, v in r["T"].items() if v == "該当"})
        unk = sorted({t for r in runs for t, v in r["T"].items() if v == "不明"} - set(hit))
        reasons = []
        for r in runs:
            for kv in r["reasons"]:
                if kv not in reasons:
                    reasons.append(kv)
        gate = "" if len(runs) == 1 else ("合格" if all(r["verdict"] == "合致" for r in runs) else "不合格")
        stable = "" if len(runs) == 1 else ("安定" if len({r["verdict"] for r in runs}) == 1 else "揺れ")
        label = norm_label(m.get("label", ""))
        pred = {"合致": "正", "不一致": "誤"}.get(d["verdict"], "要確認")
        agree = "" if not label or label == "その他" else ("一致" if pred == label else ("保留" if pred == "要確認" else "不一致"))
        tags = d3_tags(hit, d["verdict"], reasons, d["unknown"])
        reason_pairs[rid] = reasons
        rows.append({**m, "verdict": d["verdict"], "T_hit": " ".join(hit), "T_unknown": " ".join(unk),
                     "n_questions": d["n_questions"], "undefined": d["undefined"], "unknown_elems": d["unknown"],
                     "high": d["high"], "mid": d["mid"], "low": d["low"], "label_norm": label, "agreement": agree,
                     "reason_kinds": " ".join(k for k, _ in reasons),
                     "reasons": "／".join(f"{k}: {t}" if t else k for k, t in reasons),
                     "D3": " ".join(tags), "runs": len(runs), "verdict_runs": verdict_runs, "stable": stable, "gate": gate})

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

    L.append("\n## D3 タグ（摩擦原因の下書き。罠 ID と要確認の理由から機械で付けたもの。人が週次で確定する）")
    L.append("| D3 タグ | 元になる罠 ID・理由 | 行数 | 該当行 |\n|---|---|---|---|")
    d3_src = {"①用語集不足": "T08 T09・理由「定義なし」", "②データ基盤側の不足・除外漏れ": "T01 T10 T13 T14・理由「型不明」「定義表外」",
              "③質問の曖昧さ": "要確認の理由「指定なし」「解釈複数」（理由なしなら突き合わせの不明）", "④集計・計算誤り": "T02〜T07 T11 T12 T15"}
    for tag, _ in D3_TAGS:
        ids = [r["id"] for r in rows if tag in r["D3"].split()]
        L.append(f"| {tag} | {d3_src[tag]} | {len(ids)} | {' '.join(ids[:20])}{' …' if len(ids) > 20 else ''} |")
    none_ids = [r["id"] for r in rows if r["verdict"] in ("要確認", "不一致") and not r["D3"]]
    if none_ids:
        L.append(f"\nタグが付かなかった要確認・不一致（理由が定型外、または罠なし）: {' '.join(none_ids)}")

    L.append("\n## 要確認の理由（種別ごと。「定義なし」の対象は定義表に足す行、「指定なし」「解釈複数」は質問の書き方）")
    L.append("| 種別 | 行数 | 対象（多い順。件数） |\n|---|---|---|")
    for kind in REASON_TYPES + ["その他"]:
        rs = [r for r in rows if kind in r["reason_kinds"].split()]
        if not rs:
            continue
        tc = Counter(t for r in rs for k, t in reason_pairs[r["id"]] if k == kind and t)
        L.append(f"| {kind} | {len(rs)} | {'、'.join(f'{t}（{n}）' for t, n in tc.most_common(15))} |")
    if not any(r["reason_kinds"] for r in rows):
        L.append("| （理由が書かれた行なし） | | |")

    multi = [r for r in rows if r["runs"] > 1]
    if multi:
        L.append(f"\n## 複数回レビュー（--runs。{len(multi)} 件。合格＝全回が合致）")
        L.append("| 合否 | 件数 |\n|---|---|")
        for g in ["合格", "不合格"]:
            L.append(f"| {g} | {sum(1 for r in multi if r['gate'] == g)} |")
        sw = [r for r in multi if r["stable"] == "揺れ"]
        L.append(f"\n判定が揺れた行（{len(sw)} 件。要件の曖昧さか判定基準の境界。先に見る）: " +
                 (" ".join(f"{r['id']}（{r['verdict_runs']}）" for r in sw) or "なし"))

    def breakdown(title, key, fmt=lambda v: v):
        L.append(f"\n## {title}")
        L.append("| 区分 | 件数 | 合致 | 要確認 | 不一致 |\n|---|---|---|---|---|")
        g = defaultdict(Counter)
        for r in rows:
            g[fmt(r.get(key, ""))][r["verdict"]] += 1
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
