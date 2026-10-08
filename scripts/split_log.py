"""エージェントのログ（xlsx）を、1 行 1 レビューの入力ファイル（reqNNN.md）に分解する。

    python ~/.gemini/skills/sql-requirement-review/scripts/split_log.py --xlsx log.xlsx --out work/ [--schema schema.md]
        [--context session|turn] [--sql last|all] [--sheet rawdata]

- 出力先は git 管理下の外に置く（レビュー対象の SQL と要件が含まれるため）
- レビュー入力に入れるのは「要件（ユーザーの質問）」「SQL」「テーブル定義」だけ。
  エージェントの回答文は入れない（レビューが回答に引きずられるのを防ぐ）
- 行ごとの付帯情報（部署・ユーザー・セッション・ターン・SQL 本数・正誤判定など）は meta.csv に書く
"""
import argparse
import csv
import re
from pathlib import Path

import pandas as pd

DEFAULT_COLS = {
    "timestamp": "列1",
    "department": "department",
    "user": "user_name",
    "session": "conversation_group_id",
    "rally": "rally_number",
    "query": "user_query",
    "sql": "extracted_sql_queries",
    "answer": "suggestion_text",
    "raw": "raw_agent_response",
}
LABEL_COL = "正誤判定"
ERROR_RE = re.compile(r"error|エラー|exception|failed", re.IGNORECASE)
STMT_START = re.compile(r"^\s*(with|select|declare|create|insert|merge|update|delete)\b", re.IGNORECASE)


def split_sqls(text: str) -> list[str]:
    """セミコロン区切り、無ければ空行区切り（次の塊が SELECT/WITH で始まる時だけ）で分ける。"""
    if not isinstance(text, str) or not text.strip():
        return []
    parts = [p.strip() for p in text.split(";") if p.strip()]
    if len(parts) > 1:
        return parts
    chunks, cur = [], []
    for block in re.split(r"\n\s*\n", text.strip()):
        if cur and STMT_START.match(block):
            chunks.append("\n\n".join(cur))
            cur = [block]
        else:
            cur.append(block)
    if cur:
        chunks.append("\n\n".join(cur))
    return [c.strip() for c in chunks if c.strip()]


def load_labels(xlsx: Path, main_sheet: str, cols: dict) -> dict:
    """主シート以外にある「正誤判定」列を (session, rally) → 値 で集める。"""
    labels = {}
    for name, df in pd.read_excel(xlsx, sheet_name=None).items():
        if name == main_sheet or LABEL_COL not in df.columns:
            continue
        if cols["session"] not in df.columns or cols["rally"] not in df.columns:
            continue
        for _, r in df.iterrows():
            v = r[LABEL_COL]
            if pd.isna(v) or str(v).strip() == "":
                continue
            labels[(str(r[cols["session"]]), int(r[cols["rally"]]))] = str(v).strip()
    return labels


def build_requirement(session_rows: pd.DataFrame, current_rally: int, context: str, cols: dict) -> str:
    cur = session_rows[session_rows[cols["rally"]] == current_rally].iloc[0][cols["query"]]
    if context == "turn":
        return str(cur).strip()
    prior = session_rows[session_rows[cols["rally"]] < current_rally]
    lines = []
    if len(prior):
        lines.append("（同じ会話でこれより前に出た質問。対象・期間・指標の引き継ぎに使う。答えるべきはこれではない）")
        for _, r in prior.iterrows():
            lines.append(f"{int(r[cols['rally']])}. {str(r[cols['query']]).strip()}")
        lines.append("")
    lines.append("**今回の質問（この SQL が答えるべきもの）**")
    lines.append(str(cur).strip())
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sheet", default="rawdata")
    ap.add_argument("--schema", help="テーブル定義（md）。各 req に埋め込む")
    ap.add_argument("--context", choices=["session", "turn"], default="session")
    ap.add_argument("--sql", choices=["last", "all"], default="last")
    for k, v in DEFAULT_COLS.items():
        ap.add_argument(f"--col-{k}", default=v, help=f"{k} の列名（既定: {v}）")
    args = ap.parse_args()
    cols = {k: getattr(args, f"col_{k}") for k in DEFAULT_COLS}

    xlsx, out = Path(args.xlsx), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df = pd.read_excel(xlsx, sheet_name=args.sheet)
    missing = [c for c in cols.values() if c not in df.columns and c != cols["raw"]]
    if missing:
        raise SystemExit(f"列が見つからない: {missing}. --col-* で指定する。ある列: {list(df.columns)}")
    df[cols["rally"]] = df[cols["rally"]].astype(int)
    df = df.sort_values([cols["session"], cols["rally"]])
    labels = load_labels(xlsx, args.sheet, cols)
    schema = Path(args.schema).read_text(encoding="utf-8") if args.schema else None

    meta_rows, n = [], 0
    for session, srows in df.groupby(cols["session"], sort=False):
        for _, r in srows.iterrows():
            sqls = split_sqls(r[cols["sql"]])
            rally = int(r[cols["rally"]])
            raw = r[cols["raw"]] if cols["raw"] in df.columns else ""
            base = {
                "timestamp": r[cols["timestamp"]],
                "department": r[cols["department"]],
                "user": r[cols["user"]],
                "session": session,
                "rally": rally,
                "turns_in_session": len(srows),
                "n_sql": len(sqls),
                "label": labels.get((str(session), rally), ""),
                "error_mention": bool(isinstance(raw, str) and ERROR_RE.search(raw)),
                "query_chars": len(str(r[cols["query"]])),
            }
            if not sqls:
                meta_rows.append({"id": "", "sql_index": "", "sql_chars": 0, **base})
                continue
            targets = list(enumerate(sqls)) if args.sql == "all" else [(len(sqls) - 1, sqls[-1])]
            for idx, sql in targets:
                n += 1
                rid = f"req{n:03d}"
                req = build_requirement(srows, rally, args.context, cols)
                body = [f"# レビュー依頼 {rid}", "", "## 要件", req, "", "## SQL", "```sql", sql, "```", ""]
                if len(sqls) > 1:
                    body.insert(6, f"（この行には SQL が {len(sqls)} 本あり、{idx + 1} 本目をレビュー対象にしている）\n")
                if schema:
                    body += ["## テーブル定義", schema, ""]
                else:
                    body += ["## テーブル定義", "未提供。`bq show --schema` か INFORMATION_SCHEMA で取るか、SQL から推定して推定と明記する。", ""]
                (out / f"{rid}.md").write_text("\n".join(body), encoding="utf-8")
                meta_rows.append({"id": rid, "sql_index": idx + 1, "sql_chars": len(sql), **base})

    with (out / "meta.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(meta_rows[0].keys()))
        w.writeheader()
        w.writerows(meta_rows)
    n_rows = len(df)
    n_with = sum(1 for m in meta_rows if m["id"])
    print(f"行数 {n_rows}、レビュー入力 {n_with} 件、SQL なし {sum(1 for m in meta_rows if not m['id'])} 行、"
          f"正誤判定あり {sum(1 for m in meta_rows if m['label'])} 行 → {out}/")


if __name__ == "__main__":
    main()
