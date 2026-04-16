"""
Fase 3 — Normalizacao de `atividades` (actividade global da AR).

Root=dict com 7 coleccoes:
  AtividadesGerais (dict), Audicoes, Audiencias, Debates, Deslocacoes, Eventos,
  OrcamentoContasGerencia.

Para cada coleccao de tipo lista, cria uma tabela com os campos escalares +
JSON para sub-coleccoes. `AtividadesGerais` e dict com Atividades/Relatorios
(listas) — sao extraidas para tabelas separadas.
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


SCALAR_KEEP = {"Id", "IDAudicao", "IDAudiencia", "IDEvento", "IDDeslocacao", "DebateId",
               "Legislatura", "SessaoLegislativa", "Sessao", "NumeroAudicao",
               "NumeroAudiencia", "Assunto", "Concedida", "Data", "DataDebate",
               "DataEntrada", "DataIni", "DataFim", "LocalEvento", "Designacao",
               "Tipo", "TipoEvento", "Artigo", "Observacoes"}


def flatten_list(lst):
    out = []
    if not isinstance(lst, list):
        return out
    for x in lst:
        if not isinstance(x, dict):
            continue
        row = {}
        for k, v in x.items():
            if k in SCALAR_KEEP and not isinstance(v, (list, dict)):
                row[k] = v
            else:
                row[k + "_json"] = _json(v) if isinstance(v, (list, dict)) else v
        # parse data generica (primeira chave de data presente)
        for dk in ("Data", "DataDebate", "DataIni", "DataEntrada"):
            if dk in row and row[dk]:
                row["_data"] = _parse(row[dk])
                break
        out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()
    legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()] or sorted(p.name for p in RAW.iterdir() if p.is_dir())
    for leg in legs:
        p = RAW / leg / "atividades.json"
        if not p.exists():
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        d = json.loads(p.read_text(encoding="utf-8"))

        for key, tname in [
            ("Audicoes", "atividades_audicoes"),
            ("Audiencias", "atividades_audiencias"),
            ("Debates", "atividades_debates"),
            ("Deslocacoes", "atividades_deslocacoes"),
            ("Eventos", "atividades_eventos"),
            ("OrcamentoContasGerencia", "atividades_ocg"),
        ]:
            df = pd.DataFrame(flatten_list(d.get(key) or []))
            finalize_table(df, tname, leg, p, SCRIPT_NAME)

        ag = d.get("AtividadesGerais") or {}
        if isinstance(ag, dict):
            df_a = pd.DataFrame(flatten_list(ag.get("Atividades") or []))
            df_r = pd.DataFrame(flatten_list(ag.get("Relatorios") or []))
            finalize_table(df_a, "atividades_gerais", leg, p, SCRIPT_NAME)
            finalize_table(df_r, "atividades_relatorios", leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
