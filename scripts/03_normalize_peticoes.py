"""
Fase 3 — Normalizacao de `peticoes`.

Le data/raw/{legislatura}/peticoes.json e produz:
  peticoes.parquet                          — fact (PetId PK)
  peticao_documentos.parquet                — PetId x documento
  peticao_links.parquet                     — PetId x link
  peticao_iniciativas_conjuntas.parquet     — PetId x IniId
  peticao_iniciativas_originadas.parquet    — PetId x IniId
  peticao_associadas.parquet                — PetId x outra PetId
  peticao_dados_comissao.parquet            — PetId x comissao
  peticao_relatores.parquet                 — PetId x comissao_idx x relator
  peticao_audicoes.parquet                  — PetId x comissao_idx x audicao
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


def build_fact(p: dict) -> dict:
    return {
        "PetId": p.get("PetId"),
        "PetNr": p.get("PetNr"),
        "PetLeg": p.get("PetLeg"),
        "PetSel": p.get("PetSel"),
        "PetActividadeId": p.get("PetActividadeId"),
        "PetAssunto": p.get("PetAssunto"),
        "PetAutor": p.get("PetAutor"),
        "PetDataEntrada": p.get("PetDataEntrada"),
        "PetNrAssinaturas": p.get("PetNrAssinaturas"),
        "PetNrAssinaturasInicial": p.get("PetNrAssinaturasInicial"),
        "PetSituacao": p.get("PetSituacao"),
        "PetUrlTexto": p.get("PetUrlTexto"),
        "PetObs": p.get("PetObs"),
        "DataDebate": p.get("DataDebate"),
        "Intervencoes_json": _json(p.get("Intervencoes")),
        "PedidosEsclarecimento_json": _json(p.get("PedidosEsclarecimento")),
        "PublicacaoDebate_json": _json(p.get("PublicacaoDebate")),
        "PublicacaoPeticao_json": _json(p.get("PublicacaoPeticao")),
    }


def _build_doc_list(p: dict, key: str) -> list[dict]:
    out = []
    for idx, d in enumerate(p.get(key) or []):
        if not isinstance(d, dict):
            continue
        out.append({
            "PetId": p.get("PetId"),
            "doc_idx": idx,
            "TipoDocumento": d.get("TipoDocumento"),
            "TituloDocumento": d.get("TituloDocumento"),
            "DataDocumento": d.get("DataDocumento"),
            "Descricao": d.get("Descricao"),
            "URL": d.get("URL"),
        })
    return out


def _build_str_list(p: dict, key: str, ini_col: str = "IniId") -> list[dict]:
    out = []
    for v in (p.get(key) or []):
        if v is None:
            continue
        out.append({"PetId": p.get("PetId"), ini_col: str(v)})
    return out


def _build_associadas(p: dict) -> list[dict]:
    return [{"PetId": p.get("PetId"), "OutraPetId": str(v)} for v in (p.get("PeticoesAssociadas") or []) if v is not None]


def build_dados_comissao(p: dict) -> list[dict]:
    out = []
    for idx, c in enumerate(p.get("DadosComissao") or []):
        if not isinstance(c, dict):
            continue
        out.append({
            "PetId": p.get("PetId"),
            "comissao_idx": idx,
            "IdComissao": c.get("IdComissao"),
            "Nome": c.get("Nome"),
            "Numero": c.get("Numero"),
            "Sessao": c.get("Sessao"),
            "Legislatura": c.get("Legislatura"),
            "Codigo": c.get("Codigo"),
            "Situacao": c.get("Situacao"),
            "Transitada": c.get("Transitada"),
            "DataAdmissibilidade": c.get("DataAdmissibilidade"),
            "DataBaixaComissao": c.get("DataBaixaComissao"),
            "DataEnvioPAR": c.get("DataEnvioPAR"),
            "DataReaberta": c.get("DataReaberta"),
            "DataArquivo": c.get("DataArquivo"),
            "Admissibilidade_json": _json(c.get("Admissibilidade")),
            "NotasAdmissibilidade_json": _json(c.get("NotasAdmissibilidade")),
            "Audiencias_json": _json(c.get("Audiencias")),
            "AudienciasOutros_json": _json(c.get("AudienciasOutros")),
            "DadosPedidosInformacao_json": _json(c.get("DadosPedidosInformacao")),
            "DadosRelatorioFinal_json": _json(c.get("DadosRelatorioFinal")),
            "RelatorioFinal_json": _json(c.get("RelatorioFinal")),
            "Publicacao_json": _json(c.get("Publicacao")),
            "DocumentosPeticao_json": _json(c.get("DocumentosPeticao")),
        })
    return out


def build_relatores(p: dict) -> list[dict]:
    out = []
    for c_idx, c in enumerate(p.get("DadosComissao") or []):
        if not isinstance(c, dict):
            continue
        for r_idx, r in enumerate(c.get("Relatores") or []):
            if not isinstance(r, dict):
                continue
            out.append({
                "PetId": p.get("PetId"),
                "comissao_idx": c_idx,
                "relator_idx": r_idx,
                "id": r.get("id"),
                "nome": r.get("nome"),
                "gp": r.get("gp"),
                "dataNomeacao": r.get("dataNomeacao"),
                "dataCessacao": r.get("dataCessacao"),
                "motivoCessacao": r.get("motivoCessacao"),
            })
    return out


def build_audicoes(p: dict) -> list[dict]:
    out = []
    for c_idx, c in enumerate(p.get("DadosComissao") or []):
        if not isinstance(c, dict):
            continue
        for a_idx, a in enumerate(c.get("Audicoes") or []):
            if not isinstance(a, dict):
                continue
            out.append({
                "PetId": p.get("PetId"),
                "comissao_idx": c_idx,
                "audicao_idx": a_idx,
                "id": a.get("id"),
                "data": a.get("data"),
                "tipo": a.get("tipo"),
                "titulo": a.get("titulo"),
                "entidades_json": _json(a.get("entidades")),
            })
    return out


def normalize_file(path: Path) -> dict[str, pd.DataFrame]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Esperava lista em {path}")
    facts, docs, links, conj, orig, assoc, com, rel, aud = ([] for _ in range(9))
    for p in data:
        if not isinstance(p, dict):
            continue
        facts.append(build_fact(p))
        docs.extend(_build_doc_list(p, "Documentos"))
        links.extend(_build_doc_list(p, "Links"))
        conj.extend(_build_str_list(p, "IniciativasConjuntas"))
        orig.extend(_build_str_list(p, "Iniciativasoriginadas"))
        assoc.extend(_build_associadas(p))
        com.extend(build_dados_comissao(p))
        rel.extend(build_relatores(p))
        aud.extend(build_audicoes(p))
    dfs = {
        "peticoes": pd.DataFrame(facts),
        "peticao_documentos": pd.DataFrame(docs),
        "peticao_links": pd.DataFrame(links),
        "peticao_iniciativas_conjuntas": pd.DataFrame(conj),
        "peticao_iniciativas_originadas": pd.DataFrame(orig),
        "peticao_associadas": pd.DataFrame(assoc),
        "peticao_dados_comissao": pd.DataFrame(com),
        "peticao_relatores": pd.DataFrame(rel),
        "peticao_audicoes": pd.DataFrame(aud),
    }
    if "PetDataEntrada" in dfs["peticoes"]:
        dfs["peticoes"]["PetDataEntrada"] = pd.to_datetime(dfs["peticoes"]["PetDataEntrada"], errors="coerce")
    for c in ("DataDocumento",):
        for t in ("peticao_documentos", "peticao_links"):
            if c in dfs[t]:
                dfs[t][c] = pd.to_datetime(dfs[t][c], errors="coerce")
    for c in ("DataAdmissibilidade", "DataBaixaComissao", "DataEnvioPAR", "DataReaberta", "DataArquivo"):
        if c in dfs["peticao_dados_comissao"]:
            dfs["peticao_dados_comissao"][c] = pd.to_datetime(dfs["peticao_dados_comissao"][c], errors="coerce")
    for c in ("dataNomeacao", "dataCessacao"):
        if c in dfs["peticao_relatores"]:
            dfs["peticao_relatores"][c] = pd.to_datetime(dfs["peticao_relatores"][c], errors="coerce")
    if "data" in dfs["peticao_audicoes"]:
        dfs["peticao_audicoes"]["data"] = pd.to_datetime(dfs["peticao_audicoes"]["data"], errors="coerce")
    return dfs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()
    legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()] or sorted(p.name for p in RAW.iterdir() if p.is_dir())
    for leg in legs:
        p = RAW / leg / "peticoes.json"
        if not p.exists():
            print(f"  SKIP {leg}")
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        for name, df in normalize_file(p).items():
            finalize_table(df, name, leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
