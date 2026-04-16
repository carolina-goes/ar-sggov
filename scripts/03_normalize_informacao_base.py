"""
Fase 3 — Normalizacao de `informacao_base`.

Root=dict com 5 chaves:
  Deputados, GruposParlamentares, CirculosEleitorais, SessoesLegislativas, DetalheLegislatura

Produz:
  informacao_base_deputados.parquet
  informacao_base_grupos.parquet
  informacao_base_circulos.parquet
  informacao_base_sessoes.parquet
  informacao_base_detalhe.parquet
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


def _parse(s):
    return pd.to_datetime(s, dayfirst=True, errors="coerce") if s else None


def normalize(path: Path) -> dict[str, pd.DataFrame]:
    d = json.loads(path.read_text(encoding="utf-8"))

    deps = []
    for x in (d.get("Deputados") or []):
        if not isinstance(x, dict):
            continue
        deps.append({
            "DepId": x.get("DepId"),
            "DepCadId": x.get("DepCadId"),
            "DepNomeCompleto": x.get("DepNomeCompleto"),
            "DepNomeParlamentar": x.get("DepNomeParlamentar"),
            "DepCargo": x.get("DepCargo"),
            "DepCPId": x.get("DepCPId"),
            "DepCPDes": x.get("DepCPDes"),
            "LegDes": x.get("LegDes"),
            "DepGP_json": _json(x.get("DepGP")),
            "DepSituacao_json": _json(x.get("DepSituacao")),
            "Videos_json": _json(x.get("Videos")),
        })

    gps = []
    for x in (d.get("GruposParlamentares") or []):
        if not isinstance(x, dict):
            continue
        gps.append({"nome": x.get("nome"), "sigla": x.get("sigla")})

    circs = []
    for x in (d.get("CirculosEleitorais") or []):
        if not isinstance(x, dict):
            continue
        circs.append({"cpId": x.get("cpId"), "cpDes": x.get("cpDes"), "legDes": x.get("legDes")})

    sess = []
    for x in (d.get("SessoesLegislativas") or []):
        if not isinstance(x, dict):
            continue
        sess.append({
            "numSessao": x.get("numSessao"),
            "dataInicio": _parse(x.get("dataInicio")),
            "dataFim": _parse(x.get("dataFim")),
        })

    det = d.get("DetalheLegislatura") or {}
    detalhe = [{
        "id": det.get("id"),
        "sigla": det.get("sigla"),
        "siglaAntiga": det.get("siglaAntiga"),
        "dtini": _parse(det.get("dtini")),
        "dtfim": _parse(det.get("dtfim")),
    }]

    return {
        "informacao_base_deputados": pd.DataFrame(deps),
        "informacao_base_grupos": pd.DataFrame(gps),
        "informacao_base_circulos": pd.DataFrame(circs),
        "informacao_base_sessoes": pd.DataFrame(sess),
        "informacao_base_detalhe": pd.DataFrame(detalhe),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()
    legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()] or sorted(p.name for p in RAW.iterdir() if p.is_dir())
    for leg in legs:
        p = RAW / leg / "informacao_base.json"
        if not p.exists():
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        for name, df in normalize(p).items():
            finalize_table(df, name, leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
