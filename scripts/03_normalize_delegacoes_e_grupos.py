"""
Fase 3 — Normalizacao de categorias com estrutura uniforme (root=list):
  - delegacoes_eventuais
  - delegacoes_permanentes
  - grupos_parlamentares_de_amizade
  - reunioes_e_visitas
  - cooperacao_parlamentar (so existe em algumas legislaturas, ex.: XVI)

Padrao: 1 fact + satelite `participantes` (ou `composicao` / `visitas`).
Sub-coleccoes (Atividades, Programas, etc.) ficam em colunas JSON.
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


def _participantes(entity_id, lst, entity_id_name):
    out = []
    for idx, p in enumerate(lst or []):
        if not isinstance(p, dict):
            continue
        out.append({
            entity_id_name: entity_id,
            "participante_idx": idx,
            "Id": p.get("Id"),
            "Nome": p.get("Nome"),
            "Gp": p.get("Gp"),
            "Tipo": p.get("Tipo"),
            "Leg": p.get("Leg"),
        })
    return out


def normalize_generic(path: Path, table_name: str, id_field: str, sat_name: str, sat_list_key: str = "Participantes") -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    facts, sat = [], []
    for e in data:
        if not isinstance(e, dict):
            continue
        facts.append({
            id_field: e.get(id_field) or e.get("Id"),
            "Nome": e.get("Nome"),
            "Legislatura": e.get("Legislatura"),
            "Sessao": e.get("Sessao"),
            "Local": e.get("Local"),
            "DataInicio": e.get("DataInicio"),
            "DataFim": e.get("DataFim"),
            "DataCriacao": e.get("DataCriacao"),
            "DataEleicao": e.get("DataEleicao"),
            "Tipo": e.get("Tipo"),
            "Promotor": e.get("Promotor"),
            "data_inicio": _parse(e.get("DataInicio") or e.get("DataCriacao") or e.get("DataEleicao")),
            "data_fim": _parse(e.get("DataFim")),
            "Reunioes_json": _json(e.get("Reunioes")),
            "Visitas_json": _json(e.get("Visitas")),
            "Composicao_json": _json(e.get("Composicao")),
            "Comissoes_json": _json(e.get("Comissoes")),
            "Atividades_json": _json(e.get("Atividades")),
            "Programas_json": _json(e.get("Programas")),
            "Data": e.get("Data"),
        })
        entity_id = e.get(id_field) or e.get("Id")
        sat.extend(_participantes(entity_id, e.get(sat_list_key), id_field))

    df_fact = pd.DataFrame(facts)
    df_sat = pd.DataFrame(sat)
    return {table_name: df_fact, sat_name: df_sat}


def build_composicao_amizade(path: Path) -> list[dict]:
    """Extrai composicao dos grupos de amizade (Cargo, DataInicio, DataFim, Gp, Nome)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for g in data:
        if not isinstance(g, dict):
            continue
        gid = g.get("Id")
        for idx, c in enumerate(g.get("Composicao") or []):
            if not isinstance(c, dict):
                continue
            out.append({
                "Id": gid,
                "composicao_idx": idx,
                "Nome": c.get("Nome"),
                "Gp": c.get("Gp"),
                "Cargo": c.get("Cargo"),
                "DataInicio": _parse(c.get("DataInicio")),
                "DataFim": _parse(c.get("DataFim")),
                "IdDeputado": c.get("Id"),
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()
    legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()] or sorted(p.name for p in RAW.iterdir() if p.is_dir())

    JOBS = [
        ("delegacoes_eventuais.json", "delegacoes_eventuais", "Id", "delegacao_eventual_participantes", "Participantes"),
        ("delegacoes_permanentes.json", "delegacoes_permanentes", "Id", "delegacao_permanente_participantes", "Participantes"),
        ("grupos_parlamentares_de_amizade.json", "grupos_parlamentares_de_amizade", "Id", "grupo_amizade_participantes", "Participantes"),
        ("reunioes_e_visitas.json", "reunioes_e_visitas", "Id", "reuniao_visita_participantes", "Participantes"),
        ("cooperacao_parlamentar.json", "cooperacao_parlamentar", "Id", "cooperacao_parlamentar_participantes", "Participantes"),
    ]

    for leg in legs:
        for fname, tname, idf, satn, satk in JOBS:
            p = RAW / leg / fname
            if not p.exists():
                continue
            print(f"  NORM {p.relative_to(ROOT)}")
            dfs = normalize_generic(p, tname, idf, satn, satk)
            # satelite especifico para grupos de amizade: composicao (roles no grupo)
            if tname == "grupos_parlamentares_de_amizade":
                dfs["grupo_amizade_composicao"] = pd.DataFrame(build_composicao_amizade(p))
            for name, df in dfs.items():
                finalize_table(df, name, leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
