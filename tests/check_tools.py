"""scripts/ の分解→集計を、架空ログと合成したレビュー結果で通しで確かめる（Gemini は呼ばない）。

    python tests/check_tools.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent


def carry(verdict, hits, unknown=(), q=1, high=0, mid=0, low=0, reason=""):
    rows = []
    for i in range(1, 16):
        t = f"T{i:02d}"
        v = "該当" if t in hits else ("不明" if t in unknown else "該当なし")
        rows.append(f"| {t} | {v} | 理由 |")
    return "\n".join([
        f"## 判定: {verdict}", "理由", "読解のみ（未実行）", "", "## ズレ一覧", "なし", "",
        "---VERDICT---", "## 判定票", f"- 判定: {verdict}", "- 実行確認: 読解のみ", "- テーブル定義の入手: 事前に渡した", "",
        "| T | 結果（該当／該当なし／不明） | 理由（構造の言葉で 1 行） |", "|---|---|---|", *rows, "",
        f"- 要確認にした理由（判定が要確認のときだけ。「種別: 対象」を「／」でつなぐ。種別は「書き方」の 5 つだけ）: {reason}",
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
            "req004": carry("要確認", ["T14"], unknown=["T13"], mid=1, reason="定義なし: 売上（税）／指定なし: 期間／自由文"),
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
        # D3 タグ: req002（T02）→④、req003（T11）→④、req004（T14＋定義なし＋指定なし）→①②③
        assert "| ④集計・計算誤り | T02〜T07 T11 T12 T15 | 2 | req002 req003 |" in s, s
        assert "| ①用語集不足 | T08 T09・理由「定義なし」 | 1 | req004 |" in s, s
        assert "| ②データ基盤側の不足・除外漏れ | T01 T10 T13 T14・理由「型不明」「定義表外」 | 1 | req004 |" in s, s
        assert "| ③質問の曖昧さ |" in s and "| 1 | req004 |" in s.split("③質問の曖昧さ")[1].split("\n")[0], s
        assert "| 定義なし | 1 | 売上（税）（1） |" in s and "| 指定なし | 1 | 期間（1） |" in s and "| その他 | 1 | 自由文（1） |" in s, s
        r4 = [ln for ln in rows.splitlines() if ln.startswith("req004,")][0]
        assert "定義なし 指定なし その他" in r4 and "①用語集不足 ②データ基盤側の不足・除外漏れ ③質問の曖昧さ" in r4, r4
        assert "複数回レビュー" not in s
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
        # --runs N: 偽の gemini（判定を順に返す）で run_reviews.sh を回し、揺れ・合否が集計に出ること
        rw = td / "rwork"
        rw.mkdir()
        for rid in ["req001", "req002"]:
            (rw / f"{rid}.md").write_text(f"# {rid}\n要件\nSQL", encoding="utf-8")
        with (rw / "meta.csv").open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["id", "label"])
            w.writerow(["req001", ""])
            w.writerow(["req002", ""])
        fake_bin = td / "bin"
        fake_bin.mkdir()
        # 呼び出し順に 合致,合致,合致（req001）→ 合致,要確認,合致（req002）。要確認の回は理由付き
        plan = td / "plan.txt"
        plan.write_text("合致\n合致\n合致\n合致\n要確認\n合致\n", encoding="utf-8")
        (td / "fake_review.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(HERE)!r})\n"
            "from check_tools import carry\n"
            f"plan = Path({str(plan)!r})\n"
            "lines = plan.read_text(encoding='utf-8').splitlines()\n"
            "v = lines.pop(0)\n"
            "plan.write_text('\\n'.join(lines) + '\\n', encoding='utf-8')\n"
            "sys.stdin.read()\n"
            "print(carry(v, [], reason='解釈複数: 期間' if v == '要確認' else ''))\n", encoding="utf-8")
        (fake_bin / "gemini").write_text(f"#!/usr/bin/env bash\nexec {sys.executable} {td / 'fake_review.py'}\n", encoding="utf-8")
        (fake_bin / "gemini").chmod(0o755)
        import os
        env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        r = subprocess.run(["bash", ROOT / "scripts/run_reviews.sh", rw, "--runs", "3"], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr + r.stdout
        assert "req001.md 判定 合致/合致/合致 → 合格" in r.stdout and "req002.md 判定 合致/要確認/合致 → 不合格" in r.stdout, r.stdout
        assert "合格 1 件、不合格 1 件" in r.stdout, r.stdout
        assert sorted(p.name for p in rw.glob("req*_review*.md")) == [
            "req001_review.md", "req001_review2.md", "req001_review3.md",
            "req002_review.md", "req002_review2.md", "req002_review3.md"]
        # 再実行は何もしない（済んだ件を飛ばす）
        r = subprocess.run(["bash", ROOT / "scripts/run_reviews.sh", rw, "--runs=3"], env=env, capture_output=True, text=True)
        assert "今回 0 件。未処理: 0 件" in r.stdout, r.stdout
        subprocess.run([sys.executable, ROOT / "scripts/aggregate.py", rw], check=True, capture_output=True)
        s2 = (rw / "summary.md").read_text(encoding="utf-8")
        assert "## 複数回レビュー（--runs。2 件。合格＝全回が合致）" in s2 and "| 合格 | 1 |" in s2 and "| 不合格 | 1 |" in s2, s2
        assert "判定が揺れた行（1 件" in s2 and "req002（合致/要確認/合致）" in s2, s2
        assert "| 要確認 | 1 |" in s2 and "| 解釈複数 | 1 | 期間（1） |" in s2, s2
        rows2 = (rw / "rows.csv").read_text(encoding="utf-8")
        assert "req002,,要確認," in rows2 and ",3,合致/要確認/合致,揺れ,不合格" in rows2 and ",3,合致/合致/合致,安定,合格" in rows2, rows2
    print("check_tools OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
