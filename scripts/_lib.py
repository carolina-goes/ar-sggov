"""
Helpers partilhados pelos normalizadores.

- add_technical_columns: adiciona colunas tecnicas de linhagem a um DataFrame.
- write_partitioned: escreve um parquet particionado por legislatura.
- update_norm_manifest: actualiza data/normalized/_manifest.json com entrada
  por (tabela, legislatura).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
NORM = ROOT / "data" / "normalized"
NORM_MANIFEST = NORM / "_manifest.json"
RAW_MANIFEST = ROOT / "data" / "manifest.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _raw_sha256(source_path: Path) -> str | None:
    """Le SHA256 do raw a partir do manifesto de ingestao, se existir."""
    if not RAW_MANIFEST.exists():
        return None
    try:
        entries = json.loads(RAW_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    rel = source_path.resolve().as_posix()
    for e in entries:
        p = (ROOT / e["path"]).resolve().as_posix()
        if p == rel:
            return e.get("sha256")
    return None


def add_technical_columns(df: pd.DataFrame, legislatura: str, source_path: Path, normalizer_script: str) -> pd.DataFrame:
    """Adiciona colunas tecnicas de linhagem. Todas prefixadas com `_`.
    Aplica-se mesmo a DataFrames vazios — garante que o parquet tem pelo menos
    estas colunas (DuckDB rejeita parquets sem colunas)."""
    df = df.copy()
    n = len(df)
    df["_legislatura"] = [str(legislatura)] * n
    df["_source_file"] = [source_path.relative_to(ROOT).as_posix()] * n
    df["_source_sha256"] = [_raw_sha256(source_path)] * n
    df["_normalizer"] = [normalizer_script] * n
    df["_normalized_at"] = [_utcnow()] * n
    return df


def write_partitioned(df: pd.DataFrame, table_name: str, legislatura: str) -> Path:
    """
    Escreve um parquet particionado em:
        data/normalized/{table_name}/_legislatura={leg}/part.parquet

    O prefixo `_` evita colisao case-insensitive com colunas de origem
    (ex.: `Legislatura` em intervencoes). Sobrescreve a particao existente.
    """
    part_dir = NORM / table_name / f"_legislatura={legislatura}"
    part_dir.mkdir(parents=True, exist_ok=True)
    dest = part_dir / "part.parquet"
    # remover a coluna tecnica duplicada — o valor ja vem do caminho via Hive
    to_write = df.drop(columns=[c for c in ("_legislatura",) if c in df.columns])
    table = pa.Table.from_pandas(to_write, preserve_index=False)
    pq.write_table(table, dest)
    return dest


def update_norm_manifest(entry: dict) -> None:
    """
    Actualiza data/normalized/_manifest.json: uma entrada por
    (table_name, legislatura). Substitui a existente se ja la esta.
    """
    NORM.mkdir(parents=True, exist_ok=True)
    data: list[dict] = []
    if NORM_MANIFEST.exists():
        try:
            data = json.loads(NORM_MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = []
    key = (entry["table"], entry["legislatura"])
    data = [e for e in data if (e.get("table"), e.get("legislatura")) != key]
    data.append(entry)
    data.sort(key=lambda e: (e.get("table", ""), e.get("legislatura", "")))
    NORM_MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def finalize_table(
    df: pd.DataFrame,
    table_name: str,
    legislatura: str,
    source_path: Path,
    normalizer_script: str,
) -> None:
    """Conveniencia: adiciona colunas tecnicas, escreve particionado e actualiza manifesto."""
    df = add_technical_columns(df, legislatura, source_path, normalizer_script)
    dest = write_partitioned(df, table_name, legislatura)
    update_norm_manifest({
        "table": table_name,
        "legislatura": legislatura,
        "path": dest.relative_to(ROOT).as_posix(),
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "source_file": source_path.relative_to(ROOT).as_posix(),
        "source_sha256": _raw_sha256(source_path),
        "normalizer": normalizer_script,
        "generated_at": _utcnow(),
    })
    print(f"    {table_name:<40} legislatura={legislatura}  {len(df):>6,} linhas  -> {dest.relative_to(ROOT).as_posix()}")
