"""
Fase 3 — Normalizacao de `iniciativas`.

Le data/raw/{legislatura}/iniciativas.json e produz varios parquet em data/normalized/:

  iniciativas.parquet                    — fact, 1 linha por IniId
  iniciativa_autores_deputados.parquet   — IniId x deputado
  iniciativa_autores_gp.parquet          — IniId x GP
  iniciativa_eventos.parquet             — IniId x EvtId (fase/votacao/comissao)
  iniciativa_anexos.parquet              — IniId x anexo
  iniciativa_peticoes.parquet            — IniId x peticao relacionada

Estrategia:
- Fact table achatada com os campos escalares directos da iniciativa e com
  IniAutorOutros (dict unico) achatado com prefixo `outros_`.
- Colecoes N:N extraidas para tabelas satelite ligadas por `IniId`.
- Em `iniciativa_eventos`, os sub-colecoes profundas (Votacao, Comissao,
  PublicacaoFase, IniciativasConjuntas, Intervencoesdebates, etc.) sao
  guardadas como colunas JSON — podem ser exploradas depois com DuckDB.

Uso:
    python 03_normalize_iniciativas.py                 # todas as legislaturas em raw/
    python 03_normalize_iniciativas.py --legislaturas 17
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
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)


def _event_dates(ini: dict) -> tuple:
    """Devolve (data_entrada, data_ultimo_evento) calculadas a partir dos eventos."""
    evts = ini.get("IniEventos") or []
    datas = []
    for e in evts:
        if isinstance(e, dict) and e.get("DataFase"):
            datas.append(e["DataFase"])
    if not datas:
        return (None, None)
    return (min(datas), max(datas))


def build_fact(ini: dict, legislatura: str) -> dict:
    outros = ini.get("IniAutorOutros") or {}
    data_entrada, data_ultimo_evt = _event_dates(ini)
    return {
        "legislatura_ingest": legislatura,
        "IniId": ini.get("IniId"),
        "data_entrada": data_entrada,
        "data_ultimo_evento": data_ultimo_evt,
        "IniLeg": ini.get("IniLeg"),
        "IniNr": ini.get("IniNr"),
        "IniSel": ini.get("IniSel"),
        "IniTipo": ini.get("IniTipo"),
        "IniDescTipo": ini.get("IniDescTipo"),
        "IniTitulo": ini.get("IniTitulo"),
        "IniEpigrafe": ini.get("IniEpigrafe"),
        "IniObs": ini.get("IniObs"),
        "IniTextoSubst": ini.get("IniTextoSubst"),
        "IniTextoSubstCampo": ini.get("IniTextoSubstCampo"),
        "IniLinkTexto": ini.get("IniLinkTexto"),
        "DataInicioleg": ini.get("DataInicioleg"),
        "DataFimleg": ini.get("DataFimleg"),
        "outros_nome": outros.get("nome"),
        "outros_sigla": outros.get("sigla"),
        "outros_iniAutorComissao": _json(outros.get("iniAutorComissao")),
        "IniciativasOrigem_json": _json(ini.get("IniciativasOrigem")),
        "IniciativasOriginadas_json": _json(ini.get("IniciativasOriginadas")),
        "IniciativasEuropeias_json": _json(ini.get("IniciativasEuropeias")),
        "PropostasAlteracao_json": _json(ini.get("PropostasAlteracao")),
        "Links_json": _json(ini.get("Links")),
    }


def build_autores_deputados(ini: dict) -> list[dict]:
    lst = ini.get("IniAutorDeputados") or []
    if not isinstance(lst, list):
        return []
    out = []
    for d in lst:
        if not isinstance(d, dict):
            continue
        out.append({
            "IniId": ini.get("IniId"),
            "idCadastro": d.get("idCadastro"),
            "nome": d.get("nome"),
            "GP": d.get("GP"),
        })
    return out


def build_autores_gp(ini: dict) -> list[dict]:
    lst = ini.get("IniAutorGruposParlamentares") or []
    if not isinstance(lst, list):
        return []
    return [
        {"IniId": ini.get("IniId"), "GP": d.get("GP")}
        for d in lst if isinstance(d, dict)
    ]


def build_eventos(ini: dict) -> list[dict]:
    lst = ini.get("IniEventos") or []
    if not isinstance(lst, list):
        return []
    out = []
    for e in lst:
        if not isinstance(e, dict):
            continue
        out.append({
            "IniId": ini.get("IniId"),
            "EvtId": e.get("EvtId"),
            "OevId": e.get("OevId"),
            "OevTextId": e.get("OevTextId"),
            "ActId": e.get("ActId"),
            "CodigoFase": e.get("CodigoFase"),
            "Fase": e.get("Fase"),
            "DataFase": e.get("DataFase"),
            "ObsFase": e.get("ObsFase"),
            "TextosAprovados": e.get("TextosAprovados"),
            "AnexosFase_json": _json(e.get("AnexosFase")),
            "Comissao_json": _json(e.get("Comissao")),
            "PublicacaoFase_json": _json(e.get("PublicacaoFase")),
            "Votacao_json": _json(e.get("Votacao")),
            "Intervencoesdebates_json": _json(e.get("Intervencoesdebates")),
            "IniciativasConjuntas_json": _json(e.get("IniciativasConjuntas")),
            "PeticoesConjuntas_json": _json(e.get("PeticoesConjuntas")),
            "ActividadesConjuntas_json": _json(e.get("ActividadesConjuntas")),
            "PcpublicasConjuntas_json": _json(e.get("PcpublicasConjuntas")),
            "RecursoDeputados_json": _json(e.get("RecursoDeputados")),
            "RecursoGP_json": _json(e.get("RecursoGP")),
            "Links_json": _json(e.get("Links")),
        })
    return out


def build_anexos(ini: dict) -> list[dict]:
    lst = ini.get("IniAnexos") or []
    if not isinstance(lst, list):
        return []
    return [
        {"IniId": ini.get("IniId"), "anexoNome": a.get("anexoNome"), "anexoFich": a.get("anexoFich")}
        for a in lst if isinstance(a, dict)
    ]


def build_peticoes(ini: dict) -> list[dict]:
    lst = ini.get("Peticoes") or []
    if not isinstance(lst, list):
        return []
    return [
        {
            "IniId": ini.get("IniId"),
            "peticao_id": p.get("id"),
            "numero": p.get("numero"),
            "legislatura": p.get("legislatura"),
            "sessao": p.get("sessao"),
            "tipo": p.get("tipo"),
            "descTipo": p.get("descTipo"),
            "assunto": p.get("assunto"),
            "dcl": p.get("dcl"),
        }
        for p in lst if isinstance(p, dict)
    ]


def normalize_file(path: Path, legislatura: str) -> dict[str, pd.DataFrame]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Esperava lista em {path}, obtive {type(data).__name__}")

    facts, ad, ag, evt, anx, pet = [], [], [], [], [], []
    for ini in data:
        if not isinstance(ini, dict):
            continue
        facts.append(build_fact(ini, legislatura))
        ad.extend(build_autores_deputados(ini))
        ag.extend(build_autores_gp(ini))
        evt.extend(build_eventos(ini))
        anx.extend(build_anexos(ini))
        pet.extend(build_peticoes(ini))

    dfs = {
        "iniciativas": pd.DataFrame(facts),
        "iniciativa_autores_deputados": pd.DataFrame(ad),
        "iniciativa_autores_gp": pd.DataFrame(ag),
        "iniciativa_eventos": pd.DataFrame(evt),
        "iniciativa_anexos": pd.DataFrame(anx),
        "iniciativa_peticoes": pd.DataFrame(pet),
    }

    # tipos de data
    for col in ("DataInicioleg", "DataFimleg", "data_entrada", "data_ultimo_evento"):
        if col in dfs["iniciativas"]:
            dfs["iniciativas"][col] = pd.to_datetime(dfs["iniciativas"][col], errors="coerce")
    if "DataFase" in dfs["iniciativa_eventos"]:
        dfs["iniciativa_eventos"]["DataFase"] = pd.to_datetime(dfs["iniciativa_eventos"]["DataFase"], errors="coerce")

    return dfs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()

    if args.legislaturas:
        legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()]
    else:
        legs = sorted([p.name for p in RAW.iterdir() if p.is_dir()])

    for leg in legs:
        p = RAW / leg / "iniciativas.json"
        if not p.exists():
            print(f"  SKIP legislatura {leg} (sem iniciativas.json)")
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        dfs = normalize_file(p, leg)
        for name, df in dfs.items():
            finalize_table(df, name, leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
