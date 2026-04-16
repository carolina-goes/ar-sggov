"""
Fase 3 — Normalizacao de `atividade_dos_deputados`.

Le data/raw/{legislatura}/atividade_dos_deputados.json e produz:

  deputados.parquet                        — fact, 1 linha por deputado
  deputado_atividade_contadores.parquet    — nr de registos em cada coleccao de actividade

Estrategia:
- O JSON raiz e uma lista em que cada elemento tem:
    - Deputado: bloco biografico escalar (achatado no fact)
    - AtividadeDeputadoList: lista tipicamente de 1 elemento que agrega
      coleccoes de actividade (Ini, Intev, Req, Audiencias, etc.)
- Para este primeiro passe guardamos apenas contadores dessas coleccoes no
  satelite `deputado_atividade_contadores`, mais uma coluna JSON agregando
  tudo em `deputados.atividade_json` para exploracoes futuras.
- Normalizadores especificos por coleccao (ex.: uma tabela Ini por deputado
  cruzando com `iniciativas`) ficam para um passe posterior.

Uso:
    python 03_normalize_atividade_dos_deputados.py
    python 03_normalize_atividade_dos_deputados.py --legislaturas 17
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

ATIV_KEYS = [
    "ActP", "Audicoes", "Audiencias", "Cms", "DadosLegisDeputado",
    "Deslocacoes", "DlE", "DlP", "Eventos", "Gpa", "Ini", "Intev",
    "ParlamentoJovens", "Rel", "Req", "Scgt",
]


def _json(v):
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)


def _first(v):
    if isinstance(v, list) and v:
        return v[0]
    return None


def build_dep_fact(item: dict, legislatura: str) -> dict:
    dep = item.get("Deputado") or {}
    atv_list = item.get("AtividadeDeputadoList") or []
    atv0 = _first(atv_list) or {}
    return {
        "legislatura_ingest": legislatura,
        "DepId": dep.get("DepId"),
        "DepCadId": dep.get("DepCadId"),
        "DepNomeCompleto": dep.get("DepNomeCompleto"),
        "DepNomeParlamentar": dep.get("DepNomeParlamentar"),
        "DepCargo": dep.get("DepCargo"),
        "DepCPId": dep.get("DepCPId"),
        "DepCPDes": dep.get("DepCPDes"),
        "LegDes": dep.get("LegDes"),
        "DepGP_json": _json(dep.get("DepGP")),
        "DepSituacao_json": _json(dep.get("DepSituacao")),
        "atividade_json": _json(atv0) if atv0 else None,
    }


def build_contadores(item: dict) -> dict:
    dep = item.get("Deputado") or {}
    atv = _first(item.get("AtividadeDeputadoList")) or {}
    row = {"DepCadId": dep.get("DepCadId"), "DepNomeParlamentar": dep.get("DepNomeParlamentar")}
    for k in ATIV_KEYS:
        v = atv.get(k)
        if isinstance(v, list):
            row[f"n_{k}"] = len(v)
        elif isinstance(v, dict):
            row[f"n_{k}"] = 1
        else:
            row[f"n_{k}"] = 0
    return row


def normalize_file(path: Path, legislatura: str) -> dict[str, pd.DataFrame]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Esperava lista em {path}, obtive {type(data).__name__}")

    facts, cnts = [], []
    for item in data:
        if not isinstance(item, dict):
            continue
        facts.append(build_dep_fact(item, legislatura))
        cnts.append(build_contadores(item))

    return {
        "deputados": pd.DataFrame(facts),
        "deputado_atividade_contadores": pd.DataFrame(cnts),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()

    if args.legislaturas:
        legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()]
    else:
        legs = sorted([p.name for p in RAW.iterdir() if p.is_dir()])

    for leg in legs:
        p = RAW / leg / "atividade_dos_deputados.json"
        if not p.exists():
            print(f"  SKIP legislatura {leg}")
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        dfs = normalize_file(p, leg)
        for name, df in dfs.items():
            finalize_table(df, name, leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
