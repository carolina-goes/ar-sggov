"""
Fase 4 — Carregamento dos parquet normalizados para DuckDB.

Le data/normalized/<tabela>/_legislatura=*/part.parquet (Hive-partitioned) e
cria/actualiza db/ar.duckdb com uma tabela por pasta e indices nas chaves.

A coluna `_legislatura` e descoberta automaticamente via hive_partitioning=1.
O prefixo `_` evita colisao case-insensitive com colunas de origem.

Uso:
    python 04_load_to_db.py
    python 04_load_to_db.py --replace    # dropa e recria tudo
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
NORM = ROOT / "data" / "normalized"
DB = ROOT / "db" / "ar.duckdb"

INDICES = {
    "intervencoes": ["Id", "IdDebate", "dep_idCadastro", "DataReuniaoPlenaria", "Legislatura", "_legislatura"],
    "iniciativas": ["IniId", "IniLeg", "IniTipo", "_legislatura"],
    "iniciativa_autores_deputados": ["IniId", "idCadastro", "_legislatura"],
    "iniciativa_autores_gp": ["IniId", "GP", "_legislatura"],
    "iniciativa_eventos": ["IniId", "EvtId", "DataFase", "CodigoFase", "_legislatura"],
    "iniciativa_anexos": ["IniId", "_legislatura"],
    "iniciativa_peticoes": ["IniId", "peticao_id", "_legislatura"],
    "deputados": ["DepId", "DepCadId", "_legislatura"],
    "deputado_atividade_contadores": ["DepCadId", "_legislatura"],
    "dim_calendario": ["data", "ano", "ano_mes"],
}


def discover_tables() -> list[str]:
    if not NORM.exists():
        return []
    out = []
    for sub in sorted(NORM.iterdir()):
        if sub.is_dir() and any(sub.rglob("*.parquet")):
            out.append(sub.name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    DB.parent.mkdir(parents=True, exist_ok=True)
    tables = discover_tables()
    if not tables:
        print(f"Nenhuma tabela em {NORM}. Corra primeiro os normalizadores.")
        return

    con = duckdb.connect(str(DB))
    try:
        for name in tables:
            glob = (NORM / name / "**" / "*.parquet").as_posix()
            if args.replace:
                con.execute(f"DROP TABLE IF EXISTS {name}")
            print(f"  LOAD {name:<40} ...", end=" ", flush=True)
            con.execute(
                f"CREATE OR REPLACE TABLE {name} AS "
                f"SELECT * FROM read_parquet(?, hive_partitioning=1, union_by_name=true)",
                [glob],
            )
            n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"{n:,} linhas")

            for col in INDICES.get(name, []):
                exists = con.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name=?",
                    [name, col],
                ).fetchone()
                if not exists:
                    continue
                try:
                    con.execute(f'CREATE INDEX IF NOT EXISTS "idx_{name}_{col}" ON {name}("{col}")')
                except duckdb.Error as e:
                    print(f"    (sem indice em {col}: {e})")

        print("\nTabelas em ar.duckdb:")
        rows = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name").fetchall()
        for (t,) in rows:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:<40} {n:>8,}")
    finally:
        con.close()

    print(f"\nBD: {DB.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
