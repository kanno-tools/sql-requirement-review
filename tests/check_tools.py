"""scripts/ の分解→集計を、架空ログと合成したレビュー結果で通しで確かめる（Gemini は呼ばない）。

    python tests/check_tools.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent


def carry(verdict, hits, unknown=(), q=1, high=0, mid=0, low=0):
    rows = []
    for i in range(1, 16):
        t = f"T{i:02d}"
        v = "該当" if t in hits else ("不明" if t in unknown else "該当なし")
        rows.append(f"| {t} | {v} | 理由 |")
    return "\n".join([
        f"## 判定: {verdict}", "理由", "読解のみ（未実行）", "", "## ズレ一覧", "なし", "",
        "---VERDICT---", "## 判定票", f"- 判定: {verdict}", "- 実行確認: 読解のみ", "- テーブル定義の入手: 事前に渡した", "",
        "| T | 結果（該当／該当なし／不明） | 理由（構造の言葉で 1 行） |", "|---|---|---|", *rows, "",
        "- 要確認にした理由（判定が要確認のときだけ。構造の言葉で）:",
        "- 定義表が空で「定義なし」になった指標の数: 0 個",
        "- 突き合わせ表で「不明」になった要素の数: 1 個",
        f"- 確認質問の数: {q} 問",
        f"- ズレ一覧の行数（重大度 高／中／低）: {high}／{mid}／{low}", ""])


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        subprocess.run([sys.executable, HERE / "make_fake_log.py", td / "log.xlsx"], check=True, capture_output=True)
        subprocess.run([sys.executable, ROOT / "scripts/split_log.py", "--xlsx", td / "log.xlsx",
                        "--out", td / "work", "--schema", HERE / "schema.md",
                        "--definitions", HERE / "metric-definitions.md"], check=True, capture_output=True)
        work = td / "work"
        reqs = sorted(p.name for p in work.glob("req*.md"))
        assert reqs == ["req001.md", "req002.md", "req003.md", "req004.md", "req005.md"], reqs
        assert "これより前に出た質問" in (work / "req003.md").read_text(encoding="utf-8")
        assert "2 本あり、2 本目" in (work / "req004.md").read_text(encoding="utf-8")
        assert "回答文" not in (work / "req002.md").read_text(encoding="utf-8")
        # 合成したレビュー: 人の判定は req001=○ req002=× req005=×
        fake = {
            "req001": carry("合致", []),
            "req002": carry("不一致", ["T02"], q=2, high=1),
            "req003": carry("不一致", ["T11"], high=1),
            "req004": carry("要確認", ["T14"], unknown=["T13"], mid=1),
            # req005 は Skill が合致、人は × → 食い違い
            "req005": carry("合致", []),
        }
        for rid, txt in fake.items():
            (work / f"{rid}_review.md").write_text(txt, encoding="utf-8")
        subprocess.run([sys.executable, ROOT / "scripts/aggregate.py", work], check=True, capture_output=True)
        s = (work / "summary.md").read_text(encoding="utf-8")
        assert "| 合致 | 2 |" in s and "| 不一致 | 2 |" in s and "| 要確認 | 1 |" in s, s
        assert "| T14 | 1 | 0 |" in s and "| T13 | 0 | 1 |" in s, s
        assert "req005（人=誤, Skill=合致）" in s, s
        assert "表の構造の知識" in s
        rows = (work / "rows.csv").read_text(encoding="utf-8")
        assert "req004,2,138" in rows and "True" in rows
        print(s)
        # 絞り込み: req002（C02: sales/stores/targets）に customers は入らず、指標定義にある stock は入る
        r2 = (work / "req002.md").read_text(encoding="utf-8")
        assert "| stock |" in r2 and "| customers |" not in r2 and "絞ってある" in r2, r2[:400]
        assert "## 指標定義" in r2 and "references/metric-definitions.md より優先" in r2

        # eval_set アダプタ
        import yaml
        cases = {c["id"]: c for c in yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))}
        ev = td / "eval_set.csv"
        import csv as _csv
        with ev.open("w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=["id", "user_question", "prompt_intent", "expected_output_definition",
                                               "expected_sql", "source", "added_date", "definitions_version", "last_result"])
            w.writeheader()
            w.writerow({"id": "1", "user_question": cases["K01"]["requirement"], "prompt_intent": "店舗別の月次売上",
                        "expected_output_definition": "1 行 1 店舗、売上は実売金額の合計", "expected_sql": cases["K01"]["sql"],
                        "source": "test", "added_date": "2026-10-14", "definitions_version": "v1", "last_result": ""})
            w.writerow({"id": "2", "user_question": cases["C02"]["requirement"], "prompt_intent": "目標と実績の一覧",
                        "expected_output_definition": "目標がある得意先を全部出す", "expected_sql": cases["C02"]["reference"],
                        "source": "test", "added_date": "2026-10-14", "definitions_version": "v1", "last_result": ""})
        cand = td / "2.sql"
        cand.write_text(cases["C02"]["sql"], encoding="utf-8")
        ew = td / "ework"
        subprocess.run([sys.executable, ROOT / "scripts/split_eval.py", "--csv", ev, "--id", "1", "--review-expected",
                        "--out", ew, "--schema", HERE / "schema.md"], check=True, capture_output=True)
        subprocess.run([sys.executable, ROOT / "scripts/split_eval.py", "--csv", ev, "--id", "2", "--candidate", cand,
                        "--out", ew, "--schema", HERE / "schema.md", "--definitions", HERE / "metric-definitions.md"],
                       check=True, capture_output=True)
        e1 = (ew / "req001.md").read_text(encoding="utf-8")
        e2 = (ew / "req002.md").read_text(encoding="utf-8")
        assert "精度測定" in e1 and "**期待する答えの要点**" in e1
        assert "COALESCE" not in e2, "候補のレビューに期待 SQL が混ざっている"
        assert "JOIN act a ON" in e2 and "**意図**" in e2
        # meta.csv は 2 回目の実行で上書きされる（1 件）。aggregate が列不足で落ちないこと
        (ew / "req002_review.md").write_text(carry("不一致", ["T02"], high=1), encoding="utf-8")
        subprocess.run([sys.executable, ROOT / "scripts/aggregate.py", ew], check=True, capture_output=True)
        assert "| 不一致 | 1 |" in (ew / "summary.md").read_text(encoding="utf-8")
    print("check_tools OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
