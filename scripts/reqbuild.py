"""レビュー依頼（reqNNN.md）を組み立てる共通部品。split_log.py と split_eval.py が使う。

- SQL に出てくる表名を拾い、テーブル定義をその表の分だけに絞る
- 指標定義に出てくる表（正本）は、SQL に無くても残す（表の選び違い T13 を見るため）
- 指標定義は件数が少ないので絞らず全量を埋め込む
"""
import re

CTE_RE = re.compile(r"(?:\bwith\b|,)\s*`?([A-Za-z_]\w*)`?\s+as\s*\(", re.IGNORECASE)
FROM_RE = re.compile(r"\b(?:from|join)\s+`?([\w.\-]+)`?", re.IGNORECASE)
DOTTED_RE = re.compile(r"`?([A-Za-z_]\w*)\.([A-Za-z_]\w*)`?")


def tables_in_sql(sql: str) -> set[str]:
    """FROM / JOIN の相手から表名（最後の要素）を集める。CTE 名は除く。"""
    ctes = {m.group(1).lower() for m in CTE_RE.finditer(sql)}
    names = set()
    for m in FROM_RE.finditer(sql):
        last = m.group(1).split(".")[-1].lower()
        if last and last not in ctes:
            names.add(last)
    return names


def tables_in_text(text: str) -> set[str]:
    """`表.列` の形で出てくる表名を集める（指標定義表から正本の表を拾う用）。"""
    return {m.group(1).lower() for m in DOTTED_RE.finditer(text or "")}


def filter_schema(schema: str, tables: set[str]) -> tuple[str, bool]:
    """Markdown 表（1 列目が表名、続く行は空欄）形式のテーブル定義を、tables にある表の行だけに絞る。
    その形式でない、または 1 行も残らない時は全量を返す。戻り値は (本文, 絞ったか)。"""
    lines = schema.splitlines()
    out, cur, kept_any, in_table, header_done = [], None, False, False, 0
    for ln in lines:
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if header_done < 2:  # 見出し行と区切り行
                out.append(ln)
                header_done += 1
                in_table = True
                continue
            if cells and cells[0]:
                cur = cells[0].strip("`").lower()
            if cur in tables:
                out.append(ln)
                kept_any = True
        else:
            if in_table and ln.strip() == "":
                in_table = False
            out.append(ln)
            if ln.strip():  # 表の外の文は残す
                pass
    if not kept_any:
        return schema, False
    return "\n".join(out), True


def build_body(rid: str, requirement: str, sql: str, schema: str | None, definitions: str | None,
               note: str | None = None, filter_tables: bool = True) -> str:
    body = [f"# レビュー依頼 {rid}", "", "## 要件", requirement, "", "## SQL"]
    if note:
        body += [f"（{note}）", ""]
    body += ["```sql", sql.strip(), "```", ""]
    if schema:
        if filter_tables:
            tables = tables_in_sql(sql) | tables_in_text(definitions or "")
            text, filtered = filter_schema(schema, tables)
            if filtered:
                text = f"（SQL と指標定義に出てくる表だけに絞ってある: {', '.join(sorted(tables))}）\n\n" + text
        else:
            text = schema
        body += ["## テーブル定義", text, ""]
    else:
        body += ["## テーブル定義", "未提供。`bq show --schema` か INFORMATION_SCHEMA で取るか、SQL から推定して推定と明記する。", ""]
    if definitions:
        body += ["## 指標定義", "（この節の定義を、スキル内の references/metric-definitions.md より優先する）", "", definitions, ""]
    return "\n".join(body)
