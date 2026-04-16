"""
Fase 3 — Normalizacao de `intervencoes`.

Le data/raw/{legislatura}/intervencoes.json e produz:
  data/normalized/intervencoes.parquet

Estrategia:
- Uma linha por intervencao (fact table). Chave primaria: Id.
- Campos escalares e objectos simples (Deputados, Convidados, MembrosGoverno) sao
  achatados com prefixo (dep_*, conv_*, gov_*).
- `DadosAudiovisual` e `Publicacao` sao listas: extraimos o primeiro elemento
  para colunas chave (data pub, URL diario, duracao video) e guardamos a lista
  completa em colunas JSON (DuckDB le JSON nativo).
- `Iniciativas` e `IntervencoesRelacionadas` sao geralmente null — mantemos
  como JSON para o caso raro de terem conteudo.

Uso:
    python 03_normalize_intervencoes.py                 # todas as legislaturas em raw/
    python 03_normalize_intervencoes.py --legislaturas 17
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


def _to_json(v) -> str | None:
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)


def _first(lst):
    if isinstance(lst, list) and lst:
        return lst[0]
    return None


def flatten(row: dict, legislatura: str) -> dict:
    dep = row.get("Deputados") or {}
    conv = row.get("Convidados") or {}
    gov = row.get("MembrosGoverno") or {}
    act_rel = row.get("ActividadesRelacionadas") or {}

    av_list = row.get("DadosAudiovisual") or []
    av0 = _first(av_list) or {}

    pub_list = row.get("Publicacao") or []
    pub0 = _first(pub_list) or {}

    pag_list = pub0.get("pag") if isinstance(pub0, dict) else None
    pag0 = _first(pag_list) if isinstance(pag_list, list) else None

    return {
        "legislatura_ingest": legislatura,
        "Id": row.get("Id"),
        "IdDebate": row.get("IdDebate"),
        "ActividadeId": row.get("ActividadeId"),
        "Legislatura": row.get("Legislatura"),
        "Sessao": row.get("Sessao"),
        "FaseSessao": row.get("FaseSessao"),
        "FaseDebate": row.get("FaseDebate"),
        "DataReuniaoPlenaria": row.get("DataReuniaoPlenaria"),
        "TipoDebate": row.get("TipoDebate"),
        "TipoIntervencao": row.get("TipoIntervencao"),
        "Debate": row.get("Debate"),
        "Sumario": row.get("Sumario"),
        "Sumario2": row.get("Sumario2"),
        "Resumo": row.get("Resumo"),
        "Qualidade": row.get("Qualidade"),
        "dep_idCadastro": dep.get("idCadastro"),
        "dep_nome": dep.get("nome"),
        "dep_GP": dep.get("GP"),
        "conv_nome": conv.get("nome"),
        "conv_cargo": conv.get("cargo"),
        "conv_pais": conv.get("pais"),
        "conv_honra": conv.get("honra"),
        "gov_nome": gov.get("nome"),
        "gov_cargo": gov.get("cargo"),
        "gov_governo": gov.get("governo"),
        "actRel_id": act_rel.get("id"),
        "actRel_tipo": act_rel.get("tipo"),
        "actRel_autoresDeputados_json": _to_json(act_rel.get("autoresDeputados")),
        "actRel_autoresGP_json": _to_json(act_rel.get("autoresGP")),
        "av_tipoIntervencao": av0.get("tipoIntervencao") if isinstance(av0, dict) else None,
        "av_assunto": av0.get("assunto") if isinstance(av0, dict) else None,
        "av_duracao": av0.get("duracao") if isinstance(av0, dict) else None,
        "av_url": av0.get("url") if isinstance(av0, dict) else None,
        "av_all_json": _to_json(av_list),
        "pub_dt": pub0.get("pubdt") if isinstance(pub0, dict) else None,
        "pub_leg": pub0.get("pubLeg") if isinstance(pub0, dict) else None,
        "pub_tipo": pub0.get("pubTipo") if isinstance(pub0, dict) else None,
        "pub_tp": pub0.get("pubTp") if isinstance(pub0, dict) else None,
        "pub_nr": pub0.get("pubNr") if isinstance(pub0, dict) else None,
        "pub_SL": pub0.get("pubSL") if isinstance(pub0, dict) else None,
        "pub_pag": pag0,
        "pub_URLDiario": pub0.get("URLDiario") if isinstance(pub0, dict) else None,
        "pub_all_json": _to_json(pub_list),
        "iniciativas_json": _to_json(row.get("Iniciativas")),
        "intervencoesRelacionadas_json": _to_json(row.get("IntervencoesRelacionadas")),
    }


def normalize_file(path: Path, legislatura: str) -> pd.DataFrame:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Esperava lista em {path}, obtive {type(data).__name__}")
    rows = [flatten(r, legislatura) for r in data]
    df = pd.DataFrame(rows)
    # tipos
    if "DataReuniaoPlenaria" in df:
        df["DataReuniaoPlenaria"] = pd.to_datetime(df["DataReuniaoPlenaria"], errors="coerce")
    if "pub_dt" in df:
        df["pub_dt"] = pd.to_datetime(df["pub_dt"], errors="coerce")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="", help="CSV de legislaturas; vazio = todas em data/raw/")
    args = ap.parse_args()

    if args.legislaturas:
        legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()]
    else:
        legs = sorted([p.name for p in RAW.iterdir() if p.is_dir()])

    for leg in legs:
        p = RAW / leg / "intervencoes.json"
        if not p.exists():
            print(f"  SKIP legislatura {leg} (sem intervencoes.json)")
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        df = normalize_file(p, leg)
        finalize_table(df, "intervencoes", leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
