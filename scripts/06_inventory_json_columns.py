"""
Fase 6 — Inventário das colunas JSON em todas as tabelas normalizadas.

Read-only. Não toca em normalized/, db/ ou app/. Apenas produz um relatório.

Para cada tabela em `data/normalized/`, para cada coluna cujo nome termine
em `_json` (convenção) ou que contenha valores JSON (string começada por
`{` ou `[`), calcula por legislatura:
  - total de linhas
  - linhas com valor null
  - linhas com "" / [] / {} (vazias mas não-null)
  - linhas com conteúdo significativo (lista não-vazia ou dict não-vazio)
  - amostras (até 2)
  - chaves de topo observadas (quando é dict ou lista-de-dicts)

Output:
  data/schemas/_json_inventory.md  — relatório Markdown consolidado
  data/schemas/_json_inventory.json — mesmo dado em JSON para scripts

Uso:
    python scripts/06_inventory_json_columns.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
NORM = ROOT / "data" / "normalized"
OUT_MD = ROOT / "data" / "schemas" / "_json_inventory.md"
OUT_JSON = ROOT / "data" / "schemas" / "_json_inventory.json"

MAX_SAMPLES = 2
MAX_KEYS = 15


def _parse(v):
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str) and v:
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _is_empty(parsed) -> bool:
    if parsed is None:
        return True
    if isinstance(parsed, (list, dict, str)):
        return len(parsed) == 0
    return False


def _infer_keys(values, max_keys: int = MAX_KEYS) -> list[str]:
    """Para lista de dicts OU dict, devolve as chaves observadas mais frequentes."""
    counter: Counter = Counter()
    for v in values:
        p = _parse(v)
        if isinstance(p, dict):
            counter.update(p.keys())
        elif isinstance(p, list):
            for item in p[:50]:
                if isinstance(item, dict):
                    counter.update(item.keys())
    return [k for k, _ in counter.most_common(max_keys)]


def _samples(values, n: int = MAX_SAMPLES) -> list[str]:
    out = []
    for v in values:
        p = _parse(v)
        if not _is_empty(p):
            s = json.dumps(p, ensure_ascii=False)[:180]
            if s not in out:
                out.append(s)
                if len(out) >= n:
                    break
    return out


def _candidate_columns(con, glob: str) -> list[tuple[str, str]]:
    """Devolve lista de (coluna, tipo_dtype) candidatas a inventário."""
    info = con.execute(
        f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=1, union_by_name=true)) ORDER BY column_name",
        [glob],
    ).fetchdf()
    out = []
    for _, r in info.iterrows():
        name = r["column_name"]
        ctype = str(r["column_type"])
        if name.startswith("_") or ctype in ("DATE", "TIMESTAMP", "TIMESTAMP_NS", "DOUBLE", "FLOAT", "BIGINT", "INTEGER", "SMALLINT", "BOOLEAN"):
            continue
        if name.endswith("_json"):
            out.append((name, ctype))
    return out


def _table_names() -> list[str]:
    return sorted(
        p.name for p in NORM.iterdir()
        if p.is_dir() and any(p.rglob("*.parquet"))
    )


def inventory() -> dict:
    con = duckdb.connect(":memory:")
    result: dict = {"tables": {}}
    for tname in _table_names():
        glob = (NORM / tname / "**" / "*.parquet").as_posix()
        try:
            cols = _candidate_columns(con, glob)
        except duckdb.Error as e:
            result["tables"][tname] = {"error": str(e)}
            continue
        if not cols:
            continue
        tinfo: dict = {"json_columns": {}}
        # legislaturas presentes
        try:
            legs = [
                str(r[0]) for r in con.execute(
                    f"SELECT DISTINCT _legislatura FROM read_parquet(?, hive_partitioning=1, union_by_name=true) ORDER BY 1",
                    [glob],
                ).fetchall()
            ]
        except duckdb.Error:
            legs = []
        for col, ctype in cols:
            cinfo: dict = {"type": ctype, "by_legislatura": {}}
            for leg in legs:
                try:
                    total = con.execute(
                        f"SELECT COUNT(*) FROM read_parquet(?, hive_partitioning=1, union_by_name=true) WHERE _legislatura = ?",
                        [glob, leg],
                    ).fetchone()[0]
                    nulls = con.execute(
                        f'SELECT COUNT(*) FROM read_parquet(?, hive_partitioning=1, union_by_name=true) WHERE _legislatura = ? AND "{col}" IS NULL',
                        [glob, leg],
                    ).fetchone()[0]
                    vals = [
                        r[0] for r in con.execute(
                            f'SELECT "{col}" FROM read_parquet(?, hive_partitioning=1, union_by_name=true) WHERE _legislatura = ? AND "{col}" IS NOT NULL LIMIT 500',
                            [glob, leg],
                        ).fetchall()
                    ]
                except duckdb.Error as e:
                    cinfo["by_legislatura"][leg] = {"error": str(e)}
                    continue
                empty = sum(1 for v in vals if _is_empty(_parse(v)))
                significant = len(vals) - empty
                # extrapolação conservadora
                cinfo["by_legislatura"][leg] = {
                    "total": total,
                    "nulls": nulls,
                    "sampled_non_null": len(vals),
                    "sampled_empty": empty,
                    "sampled_significant": significant,
                    "pct_significant_in_sample": round(100.0 * significant / max(1, len(vals)), 1),
                    "keys_top": _infer_keys(vals),
                    "samples": _samples(vals),
                }
            tinfo["json_columns"][col] = cinfo
        if tinfo["json_columns"]:
            result["tables"][tname] = tinfo
    con.close()
    return result


def render_md(report: dict) -> str:
    lines = ["# Inventário de colunas JSON", ""]
    lines.append("Gerado por `scripts/06_inventory_json_columns.py`. **Read-only**.")
    lines.append("")
    lines.append("Para cada coluna `*_json`, para cada legislatura presente, vê:")
    lines.append("")
    lines.append("- **total**: linhas na partição.")
    lines.append("- **nulls**: linhas com NULL.")
    lines.append("- **% signif.**: percentagem das linhas não-null em amostra de 500 que tem conteúdo (lista não-vazia ou dict não-vazio).")
    lines.append("- **keys_top**: chaves mais frequentes observadas.")
    lines.append("- **samples**: exemplos reais (truncados a 180 chars).")
    lines.append("")

    tables = report.get("tables", {})
    if not tables:
        lines.append("_Nenhuma coluna JSON encontrada._")
        return "\n".join(lines)

    for tname in sorted(tables):
        tinfo = tables[tname]
        if "error" in tinfo:
            lines.append(f"## {tname}")
            lines.append(f"- _Erro_: {tinfo['error']}")
            lines.append("")
            continue
        lines.append(f"## `{tname}`")
        lines.append("")
        for col in sorted(tinfo["json_columns"]):
            cinfo = tinfo["json_columns"][col]
            lines.append(f"### `{col}` ({cinfo['type']})")
            lines.append("")
            lines.append("| leg | total | nulls | % signif. (amostra) | keys_top |")
            lines.append("|---|---:|---:|---:|---|")
            for leg in sorted(cinfo["by_legislatura"]):
                info = cinfo["by_legislatura"][leg]
                if "error" in info:
                    lines.append(f"| {leg} | — | — | _erro_ | _{info['error']}_ |")
                    continue
                keys_s = ", ".join(info["keys_top"][:8]) or "—"
                lines.append(
                    f"| {leg} | {info['total']:,} | {info['nulls']:,} | {info['pct_significant_in_sample']}% | {keys_s} |"
                )
            # samples agregadas
            sample_set: list[str] = []
            for info in cinfo["by_legislatura"].values():
                if isinstance(info, dict) and "samples" in info:
                    for s in info["samples"]:
                        if s not in sample_set:
                            sample_set.append(s)
                        if len(sample_set) >= 3:
                            break
                if len(sample_set) >= 3:
                    break
            if sample_set:
                lines.append("")
                lines.append("**Amostras**:")
                for s in sample_set[:3]:
                    lines.append(f"- `{s}`")
            lines.append("")
    return "\n".join(lines)


def main():
    print("A inventariar colunas JSON em todas as tabelas normalizadas...")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    report = inventory()
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_MD.write_text(render_md(report), encoding="utf-8")
    n_tables = len(report.get("tables", {}))
    n_cols = sum(len(t.get("json_columns", {})) for t in report.get("tables", {}).values() if isinstance(t, dict) and "json_columns" in t)
    print(f"Feito: {n_tables} tabelas com colunas JSON, {n_cols} colunas JSON inventariadas.")
    print(f"Relatório: {OUT_MD.relative_to(ROOT).as_posix()}")
    print(f"Dados: {OUT_JSON.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
