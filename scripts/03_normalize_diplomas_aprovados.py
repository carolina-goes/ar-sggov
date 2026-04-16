"""
Fase 3 — Normalizacao de `diplomas_aprovados`.

Le data/raw/{legislatura}/diplomas_aprovados.json e produz:
  diplomas_aprovados.parquet               — fact (Id PK)
  diploma_iniciativas.parquet              — Id x IniId (origem do diploma)
  diploma_publicacao.parquet               — Id x publicacao
  diploma_orcam_contas_gerencia.parquet    — Id x linha de OCG
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


def _first(v):
    return v[0] if isinstance(v, list) and v else None


def build_fact(d: dict) -> dict:
    return {
        "Id": d.get("Id"),
        "Tipo": d.get("Tipo"),
        "Tp": d.get("Tp"),
        "Numero": d.get("Numero"),
        "Numero2": d.get("Numero2"),
        "AnoCivil": d.get("AnoCivil"),
        "Sessao": d.get("Sessao"),
        "Legislatura": d.get("Legislatura"),
        "Titulo": d.get("Titulo"),
        "LinkTexto": d.get("LinkTexto"),
        "Versao": d.get("Versao"),
        "Observacoes_json": _json(d.get("Observacoes")),
        "Actividades_json": _json(d.get("Actividades")),
        "Anexos_json": _json(d.get("Anexos")),
    }


def build_iniciativas(d: dict) -> list[dict]:
    out = []
    for i in (d.get("Iniciativas") or []):
        if not isinstance(i, dict):
            continue
        out.append({
            "Id": d.get("Id"),
            "IniId": i.get("IniId"),
            "IniNr": i.get("IniNr"),
            "IniTipo": i.get("IniTipo"),
            "IniLinkTexto": i.get("IniLinkTexto"),
        })
    return out


def build_publicacao(d: dict) -> list[dict]:
    out = []
    for idx, p in enumerate(d.get("Publicacao") or []):
        if not isinstance(p, dict):
            continue
        pag_list = p.get("pag")
        out.append({
            "Id": d.get("Id"),
            "publicacao_idx": idx,
            "pubLeg": p.get("pubLeg"),
            "pubSL": p.get("pubSL"),
            "pubNr": p.get("pubNr"),
            "pubTp": p.get("pubTp"),
            "pubTipo": p.get("pubTipo"),
            "pubdt": p.get("pubdt"),
            "idPag": p.get("idPag"),
            "URLDiario": p.get("URLDiario"),
            "pag_first": _first(pag_list) if isinstance(pag_list, list) else None,
            "pag_all_json": _json(pag_list),
            "supl": p.get("supl"),
            "obs": p.get("obs"),
            "pagFinalDiarioSupl": p.get("pagFinalDiarioSupl"),
        })
    return out


def build_ocg(d: dict) -> list[dict]:
    out = []
    for idx, o in enumerate(d.get("OrcamContasGerencia") or []):
        if not isinstance(o, dict):
            continue
        out.append({
            "Id": d.get("Id"),
            "ocg_idx": idx,
            "ocg_id": o.get("id"),
            "leg": o.get("leg"),
            "SL": o.get("SL"),
            "ano": o.get("ano"),
            "tipo": o.get("tipo"),
            "tp": o.get("tp"),
            "titulo": o.get("titulo"),
            "dtAgendamento": o.get("dtAgendamento"),
            "dtAprovacaoCA": o.get("dtAprovacaoCA"),
            "votacao_json": _json(o.get("votacao")),
            "anexos_json": _json(o.get("anexos")),
            "textosAprovados_json": _json(o.get("textosAprovados")),
            "obs": o.get("obs"),
        })
    return out


def normalize_file(path: Path) -> dict[str, pd.DataFrame]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Esperava lista em {path}")
    facts, ini, pub, ocg = [], [], [], []
    for d in data:
        if not isinstance(d, dict):
            continue
        facts.append(build_fact(d))
        ini.extend(build_iniciativas(d))
        pub.extend(build_publicacao(d))
        ocg.extend(build_ocg(d))
    dfs = {
        "diplomas_aprovados": pd.DataFrame(facts),
        "diploma_iniciativas": pd.DataFrame(ini),
        "diploma_publicacao": pd.DataFrame(pub),
        "diploma_orcam_contas_gerencia": pd.DataFrame(ocg),
    }
    if "pubdt" in dfs["diploma_publicacao"]:
        dfs["diploma_publicacao"]["pubdt"] = pd.to_datetime(dfs["diploma_publicacao"]["pubdt"], errors="coerce")
    for c in ("dtAgendamento", "dtAprovacaoCA"):
        if c in dfs["diploma_orcam_contas_gerencia"]:
            dfs["diploma_orcam_contas_gerencia"][c] = pd.to_datetime(dfs["diploma_orcam_contas_gerencia"][c], errors="coerce")
    return dfs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()
    legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()] or sorted(p.name for p in RAW.iterdir() if p.is_dir())
    for leg in legs:
        p = RAW / leg / "diplomas_aprovados.json"
        if not p.exists():
            print(f"  SKIP {leg}")
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        for name, df in normalize_file(p).items():
            finalize_table(df, name, leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
