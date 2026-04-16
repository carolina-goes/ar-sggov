"""
Fase 5 — Construcao da dimensao `dim_calendario`.

Gera uma linha por dia entre uma data minima (inicio da legislatura mais antiga
presente nos dados) e hoje+365, com atributos de calendario uteis para filtros
e agregacoes no dashboard.

Output:
  data/normalized/dim_calendario/part.parquet   (sem particao — dimensao global)

Nota: nao usa o helper `finalize_table` porque nao e particionada por
legislatura e nao tem `_source_file` especifico. Escreve-se directamente em
parquet e junta-se ao `_manifest.json` com um registo proprio.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
NORM = ROOT / "data" / "normalized"
MANIFEST = NORM / "_manifest.json"
DEST = NORM / "dim_calendario" / "part.parquet"

DIAS_SEMANA = {0: "segunda-feira", 1: "terca-feira", 2: "quarta-feira",
               3: "quinta-feira", 4: "sexta-feira", 5: "sabado", 6: "domingo"}
MESES = {1: "janeiro", 2: "fevereiro", 3: "marco", 4: "abril", 5: "maio",
         6: "junho", 7: "julho", 8: "agosto", 9: "setembro", 10: "outubro",
         11: "novembro", 12: "dezembro"}


def discover_min_date() -> date:
    """Le o MIN de datas nos parquets factuais directamente (sem depender da DB).
    Usa uma conexao DuckDB em memoria sobre os parquets — evita ordem de pipeline."""
    candidatos = [
        ("iniciativas", "data_entrada"),
        ("iniciativa_eventos", "DataFase"),
        ("intervencoes", "DataReuniaoPlenaria"),
        ("perguntas_e_requerimentos", "DataEnvio"),
        ("peticoes", "PetDataEntrada"),
        ("diploma_publicacao", "pubdt"),
    ]
    con = duckdb.connect(":memory:")
    try:
        mins = []
        for t, c in candidatos:
            glob = (NORM / t / "**" / "*.parquet").as_posix()
            try:
                v = con.execute(
                    f'SELECT MIN("{c}") FROM read_parquet(?, hive_partitioning=1, union_by_name=true)',
                    [glob],
                ).fetchone()[0]
                if v is not None:
                    mins.append(v)
            except duckdb.Error:
                pass
        if not mins:
            return date(2024, 1, 1)
        m = min(mins)
        if isinstance(m, datetime):
            return m.date()
        return m
    finally:
        con.close()


def build() -> pd.DataFrame:
    start = discover_min_date()
    end = date.today() + timedelta(days=365)
    idx = pd.date_range(start=start, end=end, freq="D")
    df = pd.DataFrame({"data": idx.date})
    ts = pd.to_datetime(df["data"])
    df["ano"] = ts.dt.year.astype("int32")
    df["trimestre"] = ts.dt.quarter.astype("int8")
    df["mes"] = ts.dt.month.astype("int8")
    df["mes_nome"] = df["mes"].map(MESES)
    df["semana_iso"] = ts.dt.isocalendar().week.astype("int8")
    df["ano_mes"] = ts.dt.strftime("%Y-%m")
    df["ano_trimestre"] = df["ano"].astype(str) + "-T" + df["trimestre"].astype(str)
    df["dia"] = ts.dt.day.astype("int8")
    df["dia_ano"] = ts.dt.dayofyear.astype("int16")
    df["dia_semana_iso"] = (ts.dt.dayofweek + 1).astype("int8")
    df["dia_semana_nome"] = ts.dt.dayofweek.map(DIAS_SEMANA)
    df["fim_de_semana"] = ts.dt.dayofweek >= 5
    df["_generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return df


def update_manifest(rows: int):
    entries = []
    if MANIFEST.exists():
        try:
            entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            entries = []
    entries = [e for e in entries if e.get("table") != "dim_calendario"]
    entries.append({
        "table": "dim_calendario",
        "legislatura": None,
        "path": DEST.relative_to(ROOT).as_posix(),
        "rows": int(rows),
        "columns": 14,
        "source_file": None,
        "source_sha256": None,
        "normalizer": Path(__file__).name,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    entries.sort(key=lambda e: (e.get("table", ""), e.get("legislatura") or ""))
    MANIFEST.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    df = build()
    DEST.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), DEST)
    update_manifest(len(df))
    print(f"Escrito: {DEST.relative_to(ROOT)} ({len(df):,} linhas)")


if __name__ == "__main__":
    main()
