"""
Fase 3 — Normalizacao de `perguntas_e_requerimentos`.

Le data/raw/{legislatura}/perguntas_e_requerimentos.json e produz:
  perguntas_e_requerimentos.parquet   — fact (Id PK)
  pergunta_autores.parquet            — Id x deputado autor
  pergunta_destinatarios.parquet      — Id x entidade destinataria
  pergunta_respostas.parquet          — Id x destinatario x resposta

Usa scripts/_lib.py:finalize_table.
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
        "Id": p.get("Id"),
        "Nr": p.get("Nr"),
        "Tipo": p.get("Tipo"),
        "ReqTipo": p.get("ReqTipo"),
        "Sessao": p.get("Sessao"),
        "Legislatura": p.get("Legislatura"),
        "Assunto": p.get("Assunto"),
        "DataEnvio": p.get("DataEnvio"),
        "DtEntrada": p.get("DtEntrada"),
        "Ficheiro": p.get("Ficheiro"),
        "Fundamentacao_json": _json(p.get("Fundamentacao")),
        "Observacoes_json": _json(p.get("Observacoes")),
        "Publicacao_json": _json(p.get("Publicacao")),
        "RespostasSPerguntas_json": _json(p.get("RespostasSPerguntas")),
    }


def build_autores(p: dict) -> list[dict]:
    out = []
    for a in (p.get("Autores") or []):
        if not isinstance(a, dict):
            continue
        out.append({
            "Id": p.get("Id"),
            "idCadastro": a.get("idCadastro"),
            "nome": a.get("nome"),
            "GP": a.get("GP"),
        })
    return out


def build_destinatarios(p: dict) -> list[dict]:
    out = []
    for idx, d in enumerate(p.get("Destinatarios") or []):
        if not isinstance(d, dict):
            continue
        out.append({
            "Id": p.get("Id"),
            "destinatario_idx": idx,
            "nomeEntidade": d.get("nomeEntidade"),
            "dataEnvio": d.get("dataEnvio"),
            "dataReenvio": d.get("dataReenvio"),
            "reenviado": d.get("reenviado"),
            "prorrogado": d.get("prorrogado"),
            "dataProrrogacao": d.get("dataProrrogacao"),
            "prazoProrrogacao": d.get("prazoProrrogacao"),
            "devolvido": d.get("devolvido"),
            "retirado": d.get("retirado"),
        })
    return out


def build_respostas(p: dict) -> list[dict]:
    out = []
    for d_idx, d in enumerate(p.get("Destinatarios") or []):
        if not isinstance(d, dict):
            continue
        for r_idx, r in enumerate(d.get("respostas") or []):
            if not isinstance(r, dict):
                continue
            out.append({
                "Id": p.get("Id"),
                "destinatario_idx": d_idx,
                "resposta_idx": r_idx,
                "entidade": r.get("entidade"),
                "dataResposta": r.get("dataResposta"),
                "ficheiro": r.get("ficheiro"),
                "ficheiroComTipo_json": _json(r.get("ficheiroComTipo")),
                "publicacao_json": _json(r.get("publicacao")),
                "docRemetida_json": _json(r.get("docRemetida")),
            })
    return out


def normalize_file(path: Path) -> dict[str, pd.DataFrame]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"Esperava lista em {path}")
    facts, aut, dest, resp = [], [], [], []
    for p in data:
        if not isinstance(p, dict):
            continue
        facts.append(build_fact(p))
        aut.extend(build_autores(p))
        dest.extend(build_destinatarios(p))
        resp.extend(build_respostas(p))
    dfs = {
        "perguntas_e_requerimentos": pd.DataFrame(facts),
        "pergunta_autores": pd.DataFrame(aut),
        "pergunta_destinatarios": pd.DataFrame(dest),
        "pergunta_respostas": pd.DataFrame(resp),
    }
    for col in ("DataEnvio", "DtEntrada"):
        if col in dfs["perguntas_e_requerimentos"]:
            dfs["perguntas_e_requerimentos"][col] = pd.to_datetime(dfs["perguntas_e_requerimentos"][col], errors="coerce")
    for col in ("dataEnvio", "dataReenvio", "dataProrrogacao"):
        if col in dfs["pergunta_destinatarios"]:
            dfs["pergunta_destinatarios"][col] = pd.to_datetime(dfs["pergunta_destinatarios"][col], errors="coerce")
    if "dataResposta" in dfs["pergunta_respostas"]:
        dfs["pergunta_respostas"]["dataResposta"] = pd.to_datetime(dfs["pergunta_respostas"]["dataResposta"], errors="coerce")
    return dfs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()
    legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()] or sorted(p.name for p in RAW.iterdir() if p.is_dir())
    for leg in legs:
        p = RAW / leg / "perguntas_e_requerimentos.json"
        if not p.exists():
            print(f"  SKIP {leg}")
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        for name, df in normalize_file(p).items():
            finalize_table(df, name, leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
