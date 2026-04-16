"""
Fase 3 — Normalizacao de `composicao_de_orgaos`.

Root=dict com 9 sub-estruturas. Cada uma e um orgao (ou lista de orgaos) com
mesma forma: {DetalheOrgao, HistoricoComposicao, Reunioes, [HistoricoComposicaoCPC]}.

Produz 2 tabelas globais consolidadas:
  orgaos_detalhe.parquet        — 1 linha por orgao (tipo_orgao + DetalheOrgao
                                   achatado + JSON das coleccoes profundas)
  orgaos_historico_composicao.parquet — 1 linha por membro no historico
                                   de cada orgao (achatado)

Deste modo e facil filtrar por tipo_orgao ("Comissao Permanente", "Comissoes", etc.).
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

TOP_KEYS = [
    ("ComissaoPermanente", "ComissaoPermanente", False),
    ("Comissoes", "Comissao", True),
    ("SubComissoes", "SubComissao", True),
    ("GruposTrabalho", "GrupoTrabalho", True),
    ("ConferenciaLideres", "ConferenciaLideres", False),
    ("ConferenciaPresidentesComissoes", "ConferenciaPresidentesComissoes", False),
    ("ConselhoAdministracao", "ConselhoAdministracao", False),
    ("MesaAR", "MesaAR", False),
    ("Plenario", "Plenario", False),
]


def _json(v):
    return None if v is None else json.dumps(v, ensure_ascii=False)


def _parse(s):
    return pd.to_datetime(s, dayfirst=True, errors="coerce") if s else None


def _flatten_detalhe(det: dict, tipo_orgao: str) -> dict:
    if not isinstance(det, dict):
        return {"tipo_orgao": tipo_orgao}
    out = {"tipo_orgao": tipo_orgao}
    for k, v in det.items():
        if isinstance(v, (list, dict)):
            out[k + "_json"] = _json(v)
        else:
            out[k] = v
    return out


def _flatten_membro(m: dict, tipo_orgao: str, orgao_id) -> dict:
    if not isinstance(m, dict):
        return {}
    out = {"tipo_orgao": tipo_orgao, "orgao_id": orgao_id}
    for k, v in m.items():
        if isinstance(v, (list, dict)):
            out[k + "_json"] = _json(v)
        else:
            out[k] = v
    for dk in ("DataInicio", "DataFim", "DataInicioGP", "DataFimGP"):
        if dk in out:
            out[dk + "_ts"] = _parse(out[dk])
    return out


def process_orgao(o: dict, tipo_orgao: str, detalhe_acc: list, comp_acc: list):
    det = o.get("DetalheOrgao") or {}
    detalhe_acc.append(_flatten_detalhe(det, tipo_orgao))
    orgao_id = det.get("oId") or det.get("Id") or det.get("id") or det.get("cargoId")
    for m in (o.get("HistoricoComposicao") or []):
        comp_acc.append(_flatten_membro(m, tipo_orgao, orgao_id))
    # CPC tem HistoricoComposicaoCPC
    for m in (o.get("HistoricoComposicaoCPC") or []):
        comp_acc.append(_flatten_membro(m, tipo_orgao + ".CPC", orgao_id))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()
    legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()] or sorted(p.name for p in RAW.iterdir() if p.is_dir())
    for leg in legs:
        p = RAW / leg / "composicao_de_orgaos.json"
        if not p.exists():
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        d = json.loads(p.read_text(encoding="utf-8"))

        detalhe_rows, comp_rows = [], []
        for key, tipo, is_list in TOP_KEYS:
            node = d.get(key)
            if node is None:
                continue
            if is_list:
                for o in node:
                    if isinstance(o, dict):
                        process_orgao(o, tipo, detalhe_rows, comp_rows)
            elif isinstance(node, dict):
                process_orgao(node, tipo, detalhe_rows, comp_rows)

        finalize_table(pd.DataFrame(detalhe_rows), "orgaos_detalhe", leg, p, SCRIPT_NAME)
        finalize_table(pd.DataFrame(comp_rows), "orgaos_historico_composicao", leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
