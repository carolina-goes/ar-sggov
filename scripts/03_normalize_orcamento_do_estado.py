"""
Fase 3 — Normalizacao de `orcamento_do_estado`.

Root=dict com chave `Item` (lista hierarquica: ID_Pai -> ID).
Estrutura tipica: Titulos, Capitulos, Artigos, etc.

Produz:
  orcamento_do_estado.parquet  — um fact por Item, com campos escalares e
    as sub-coleccoes em colunas JSON (Artigos, PropostasDeAlteracao, etc.)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import finalize_table  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SCRIPT_NAME = Path(__file__).name


def _json(v):
    return None if v is None else json.dumps(v, ensure_ascii=False)


def build(item: dict) -> dict:
    return {
        "ID": item.get("ID"),
        "ID_Pai": item.get("ID_Pai"),
        "Tipo": item.get("Tipo"),
        "Numero": item.get("Numero"),
        "Titulo": item.get("Titulo"),
        "Texto": item.get("Texto"),
        "Estado": item.get("Estado"),
        "Artigos_json": _json(item.get("Artigos")),
        "DiplomasaModificar_json": _json(item.get("DiplomasaModificar")),
        "IniciativasMapas_json": _json(item.get("IniciativasMapas")),
        "PropostasDeAlteracao_json": _json(item.get("PropostasDeAlteracao")),
        "RequerimentosDeAvocacao_json": _json(item.get("RequerimentosDeAvocacao")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()
    legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()] or sorted(p.name for p in RAW.iterdir() if p.is_dir())
    for leg in legs:
        p = RAW / leg / "orcamento_do_estado.json"
        if not p.exists():
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.get("Item") if isinstance(data, dict) else None
        if not isinstance(items, list):
            print("    (sem Item list — skip)")
            continue
        df = pd.DataFrame([build(i) for i in items if isinstance(i, dict)])
        finalize_table(df, "orcamento_do_estado", leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
