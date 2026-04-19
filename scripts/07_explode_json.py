"""
Fase 7 — Exploder genérico de colunas JSON.

Lê o inventário produzido por `06_inventory_json_columns.py` e, para cada par
(tabela, coluna_json), gera um satélite Hive-partitioned em
`data/normalized/<tabela>_<col_snake>/_legislatura=<NN>/part.parquet`.

Forma canónica de cada valor JSON:
  - null           -> nada (saltado)
  - primitivo      -> 1 linha com coluna `_value`
  - dict           -> 1 linha com chaves achatadas
  - lista de X     -> N linhas (uma por elemento) com `_json_idx`
  - dict/lista aninhada → mantém-se como string JSON em coluna com sufixo `_json`,
                          re-explodível num 2º passe.

Cada satélite preserva a PK da tabela-mãe (para joins), o `_legislatura`
(Hive partition), e linhagem técnica (`_source_table`, `_source_col`,
`_normalizer`, `_normalized_at`).

Uso:
    python scripts/07_explode_json.py --all           # tudo
    python scripts/07_explode_json.py --table intervencoes
    python scripts/07_explode_json.py --table iniciativa_eventos --col Votacao_json
    python scripts/07_explode_json.py --table iniciativa_eventos --col Votacao_json --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
NORM = ROOT / "data" / "normalized"
INVENTORY_JSON = ROOT / "data" / "schemas" / "_json_inventory.json"
SCRIPT_NAME = Path(__file__).name

# Mapa de PKs explícitas por tabela fonte (colunas a preservar no satélite).
# Fallback: primeiras 4 colunas não-técnicas e não-JSON.
PARENT_KEYS: dict[str, list[str]] = {
    "iniciativas": ["IniId"],
    "iniciativa_eventos": ["IniId", "EvtId"],
    "iniciativa_autores_deputados": ["IniId", "idCadastro"],
    "iniciativa_autores_gp": ["IniId", "GP"],
    "iniciativa_anexos": ["IniId"],
    "iniciativa_peticoes": ["IniId", "peticao_id"],
    "intervencoes": ["Id", "IdDebate"],
    "peticoes": ["PetId"],
    "peticao_documentos": ["PetId", "doc_idx"],
    "peticao_links": ["PetId", "doc_idx"],
    "peticao_dados_comissao": ["PetId", "comissao_idx"],
    "peticao_relatores": ["PetId", "comissao_idx", "relator_idx"],
    "peticao_audicoes": ["PetId", "comissao_idx", "audicao_idx"],
    "peticao_iniciativas_conjuntas": ["PetId", "IniId"],
    "peticao_iniciativas_originadas": ["PetId", "IniId"],
    "peticao_associadas": ["PetId", "OutraPetId"],
    "diplomas_aprovados": ["Id"],
    "diploma_iniciativas": ["Id", "IniId"],
    "diploma_publicacao": ["Id", "publicacao_idx"],
    "diploma_orcam_contas_gerencia": ["Id", "ocg_idx"],
    "perguntas_e_requerimentos": ["Id"],
    "pergunta_autores": ["Id", "idCadastro"],
    "pergunta_destinatarios": ["Id", "destinatario_idx"],
    "pergunta_respostas": ["Id", "destinatario_idx", "resposta_idx"],
    "deputados": ["DepCadId"],
    "deputado_atividade_contadores": ["DepCadId"],
    "informacao_base_deputados": ["DepCadId"],
    "informacao_base_grupos": ["sigla"],
    "informacao_base_circulos": ["cpId"],
    "informacao_base_sessoes": ["numSessao"],
    "informacao_base_detalhe": ["id"],
    "orgaos_detalhe": ["tipo_orgao", "oId", "id"],
    "orgaos_historico_composicao": ["tipo_orgao", "orgao_id", "depCadId", "DepCadId"],
    "agenda_parlamentar": ["Id"],
    "delegacoes_eventuais": ["Id"],
    "delegacoes_permanentes": ["Id"],
    "grupos_parlamentares_de_amizade": ["Id"],
    "cooperacao_parlamentar": ["Id"],
    "reunioes_e_visitas": ["Id"],
    "atividades_audicoes": ["IDAudicao"],
    "atividades_audiencias": ["IDAudiencia"],
    "atividades_debates": ["DebateId"],
    "atividades_deslocacoes": ["IDDeslocacao"],
    "atividades_eventos": ["IDEvento"],
    "atividades_gerais": [],
    "atividades_relatorios": [],
    "atividades_ocg": [],
    "orcamento_do_estado": ["ID"],
    "delegacao_eventual_participantes": ["Id", "participante_idx"],
    "delegacao_permanente_participantes": ["Id", "participante_idx"],
    "grupo_amizade_participantes": ["Id", "participante_idx"],
    "grupo_amizade_composicao": ["Id", "composicao_idx"],
    "cooperacao_parlamentar_participantes": ["Id", "participante_idx"],
    "reuniao_visita_participantes": ["Id", "participante_idx"],
    # Satélites de 1º passe (explodidos na sessão 13). PKs explícitos para preservar
    # linhagem no 2º passe quando o fallback (primeiras 4 colunas não-tec) escolhia
    # colunas sem valor de chave (colunas dict que ficaram todas a null).
    "iniciativa_eventos_votacao": ["IniId", "EvtId", "id"],
    "iniciativa_eventos_comissao": ["IniId", "EvtId", "AccId"],
    "iniciativa_eventos_publicacao_fase": ["IniId", "EvtId", "idPag"],
    "iniciativa_eventos_intervencoesdebates": ["IniId", "EvtId", "dataReuniaoPlenaria"],
    "iniciativa_eventos_anexos_fase": ["IniId", "EvtId"],
    "iniciativa_eventos_recurso_gp": ["IniId", "EvtId"],
    "iniciativa_eventos_recurso_deputados": ["IniId", "EvtId"],
    "iniciativa_eventos_iniciativas_conjuntas": ["IniId", "EvtId"],
    "iniciativa_eventos_peticoes_conjuntas": ["IniId", "EvtId"],
    "deputados_atividade": ["DepCadId"],
    "deputados_dep_gp": ["DepCadId"],
    "deputados_dep_situacao": ["DepCadId"],
    "informacao_base_deputados_dep_gp": ["DepCadId"],
    "informacao_base_deputados_dep_situacao": ["DepCadId"],
    "informacao_base_deputados_videos": ["DepCadId"],
    "intervencoes_pub_all": ["Id", "IdDebate"],
    "intervencoes_av_all": ["Id", "IdDebate"],
    "intervencoes_iniciativas": ["Id", "IdDebate"],
    "peticao_dados_comissao_documentos_peticao": ["PetId", "comissao_idx"],
    "peticao_dados_comissao_dados_relatorio_final": ["PetId", "comissao_idx"],
    "peticao_dados_comissao_dados_pedidos_informacao": ["PetId", "comissao_idx"],
    "peticao_dados_comissao_audiencias": ["PetId", "comissao_idx"],
    "peticao_dados_comissao_relatorio_final": ["PetId", "comissao_idx"],
    "orgaos_historico_composicao_pres_orgao": ["tipo_orgao", "orgao_id", "depCadId"],
    "orgaos_historico_composicao_dep_gp": ["tipo_orgao", "orgao_id", "depCadId"],
    "orgaos_historico_composicao_dep_situacao": ["tipo_orgao", "orgao_id", "depCadId"],
    "orgaos_historico_composicao_dep_cargo": ["tipo_orgao", "orgao_id", "depCadId"],
    "atividades_debates_intervencoes": ["DebateId"],
    "atividades_debates_publicacao": ["DebateId"],
    "atividades_debates_tipo_debate": ["DebateId"],
    "atividades_gerais_publicacao": [],
    "atividades_gerais_publicacao_debate": [],
    "atividades_gerais_votacao_debate": [],
    "atividades_gerais_autores_gp": [],
    "atividades_gerais_convidados": [],
    "atividades_gerais_eleitos": [],
    "atividades_gerais_outros_subscritores": [],
    "atividades_gerais_textos_aprovados": [],
    "atividades_relatorios_publicacao": [],
    "atividades_relatorios_publicacao_debate": [],
    "atividades_relatorios_parecer_comissao": [],
    "atividades_relatorios_votacao_debate": [],
    "atividades_relatorios_votacao_relatorio": [],
    "atividades_relatorios_audicoes": [],
    "atividades_relatorios_documentos": [],
    "atividades_relatorios_relatores": [],
    "atividades_audicoes_entidades": ["IDAudicao"],
    "atividades_audiencias_entidades": ["IDAudiencia"],
    "diploma_publicacao_pag_all": ["Id", "publicacao_idx"],
    "diplomas_aprovados_observacoes": ["Id"],
    "diplomas_aprovados_actividades": ["Id"],
    "diplomas_aprovados_anexos": ["Id"],
    "iniciativas_iniciativas_origem": ["IniId"],
    "iniciativas_iniciativas_originadas": ["IniId"],
    "iniciativas_propostas_alteracao": ["IniId"],
    "iniciativas_iniciativas_europeias": ["IniId"],
    "pergunta_respostas_ficheiro_com_tipo": ["Id", "destinatario_idx", "resposta_idx"],
    "pergunta_respostas_doc_remetida": ["Id", "destinatario_idx", "resposta_idx"],
    "pergunta_respostas_publicacao": ["Id", "destinatario_idx", "resposta_idx"],
    "perguntas_e_requerimentos_fundamentacao": ["Id"],
    "perguntas_e_requerimentos_observacoes": ["Id"],
    "perguntas_e_requerimentos_publicacao": ["Id"],
    "perguntas_e_requerimentos_respostas_sperguntas": ["Id"],
    "peticoes_intervencoes": ["PetId"],
    "peticoes_publicacao_peticao": ["PetId"],
    "peticoes_publicacao_debate": ["PetId"],
    "peticoes_pedidos_esclarecimento": ["PetId"],
    "grupos_parlamentares_de_amizade_reunioes": ["Id"],
    "grupos_parlamentares_de_amizade_visitas": ["Id"],
    "grupos_parlamentares_de_amizade_composicao": ["Id"],
    "grupos_parlamentares_de_amizade_comissoes": ["Id"],
    "grupos_parlamentares_de_amizade_atividades": ["Id"],
    "grupos_parlamentares_de_amizade_programas": ["Id"],
    "delegacoes_permanentes_comissoes": ["Id"],
    "delegacoes_permanentes_composicao": ["Id"],
    "delegacoes_permanentes_reunioes": ["Id"],
    "delegacoes_permanentes_visitas": ["Id"],
    "delegacoes_permanentes_atividades": ["Id"],
    "delegacoes_permanentes_programas": ["Id"],
    "delegacoes_eventuais_reunioes": ["Id"],
    "delegacoes_eventuais_visitas": ["Id"],
    "delegacoes_eventuais_composicao": ["Id"],
    "delegacoes_eventuais_atividades": ["Id"],
    "delegacoes_eventuais_comissoes": ["Id"],
    "delegacoes_eventuais_programas": ["Id"],
    "cooperacao_parlamentar_atividades": ["Id"],
    "cooperacao_parlamentar_programas": ["Id"],
    "cooperacao_parlamentar_reunioes": ["Id"],
    "cooperacao_parlamentar_visitas": ["Id"],
    "cooperacao_parlamentar_composicao": ["Id"],
    "cooperacao_parlamentar_comissoes": ["Id"],
    "orcamento_do_estado_artigos": ["ID"],
    "orcamento_do_estado_propostas_de_alteracao": ["ID"],
    "orcamento_do_estado_diplomasa_modificar": ["ID"],
    "orcamento_do_estado_iniciativas_mapas": ["ID"],
    "orcamento_do_estado_requerimentos_de_avocacao": ["ID"],
    "reunioes_e_visitas_reunioes": ["Id"],
    "reunioes_e_visitas_visitas": ["Id"],
    "reunioes_e_visitas_composicao": ["Id"],
    "agenda_parlamentar_anexos_plenario": ["Id"],
    "agenda_parlamentar_anexos_comissao_permanente": ["Id"],
    "diploma_orcam_contas_gerencia_votacao": ["Id", "ocg_idx"],
    "diploma_orcam_contas_gerencia_anexos": ["Id", "ocg_idx"],
    "diploma_orcam_contas_gerencia_textos_aprovados": ["Id", "ocg_idx"],
    "atividades_ocg_ano": [],
    "atividades_ocg_id": [],
    "atividades_ocg_sl": [],
    "atividades_ocg_votacao": [],
    "atividades_ocg_textos_aprovados": [],
    "atividades_ocg_anexos": [],
    "atividades_ocg_obs": [],
    "atividades_ocg_leg": [],
    "atividades_ocg_titulo": [],
    "atividades_ocg_tipo": [],
    "atividades_ocg_tp": [],
    "atividades_ocg_dt_agendamento": [],
    "atividades_ocg_dt_aprovacao_ca": [],
    "atividades_ocg_textos_aprovados": [],
}


def _snake(s: str) -> str:
    s = re.sub(r"_json$", "", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"[^a-zA-Z0-9_]", "_", s)
    return s.lower().strip("_")


def _sanitize_key(k) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", str(k))


def _parse_json(v):
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str) and v:
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return None
    return v


def _maybe_json(v):
    """Se v é dict/list aninhada, serializa como JSON string; senão passa tal qual."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False) if v else None
    return v


def _flatten_dict(d: dict) -> dict:
    out = {}
    for k, val in d.items():
        key = _sanitize_key(k)
        flat = _maybe_json(val)
        if isinstance(val, (dict, list)):
            key = key + "_json"
        out[key] = flat
    return out


def _canonicalize(parsed) -> list[dict]:
    if parsed is None:
        return []
    if isinstance(parsed, list):
        if not parsed:
            return []
        out = []
        for i, v in enumerate(parsed):
            if isinstance(v, dict):
                out.append({"_json_idx": i, **_flatten_dict(v)})
            else:
                out.append({"_json_idx": i, "_value": _maybe_json(v)})
        return out
    if isinstance(parsed, dict):
        if not parsed:
            return []
        return [{"_json_idx": 0, **_flatten_dict(parsed)}]
    return [{"_json_idx": 0, "_value": parsed}]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parent_cols(source_cols: list[str], source_table: str) -> list[str]:
    explicit = PARENT_KEYS.get(source_table)
    if explicit is not None:
        return [c for c in explicit if c in source_cols]
    return [c for c in source_cols if not c.startswith("_") and not c.endswith("_json")][:4]


def _explode(source_table: str, col: str, dry_run: bool = False) -> dict:
    source_glob = (NORM / source_table / "**" / "*.parquet").as_posix()
    sat_name = f"{source_table}_{_snake(col)}"
    sat_dir = NORM / sat_name

    con = duckdb.connect(":memory:")
    try:
        col_info = con.execute(
            f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=1, union_by_name=true))",
            [source_glob],
        ).fetchdf()["column_name"].tolist()
        if col not in col_info:
            return {"satellite": sat_name, "status": "skipped", "reason": f"coluna {col} não encontrada"}

        pk_cols = _parent_cols(col_info, source_table)
        cols_to_read = ["_legislatura"] + pk_cols + [col]
        cols_to_read = list(dict.fromkeys(cols_to_read))
        cols_sql = ", ".join([f'"{c}"' for c in cols_to_read])

        df = con.execute(
            f"SELECT {cols_sql} FROM read_parquet(?, hive_partitioning=1, union_by_name=true) "
            f'WHERE "{col}" IS NOT NULL',
            [source_glob],
        ).fetchdf()

        if df.empty:
            return {"satellite": sat_name, "status": "skipped", "reason": "sem valores não-null"}

        rows_per_leg: dict[str, list[dict]] = {}
        for _, row in df.iterrows():
            parent = {c: row[c] for c in pk_cols}
            leg = str(row["_legislatura"])
            parsed = _parse_json(row[col])
            items = _canonicalize(parsed)
            for item in items:
                merged = {**parent, **item}
                rows_per_leg.setdefault(leg, []).append(merged)

        if dry_run:
            all_rows = [r for rows in rows_per_leg.values() for r in rows]
            if not all_rows:
                return {"satellite": sat_name, "status": "empty"}
            schema_keys = sorted({k for r in all_rows for k in r.keys()})
            return {
                "satellite": sat_name,
                "status": "dry-run",
                "rows_total": len(all_rows),
                "legislaturas": sorted(rows_per_leg.keys()),
                "schema": schema_keys,
                "samples": all_rows[:3],
            }

        total_rows = 0
        for leg, rows in rows_per_leg.items():
            if not rows:
                continue
            part_dir = sat_dir / f"_legislatura={leg}"
            part_dir.mkdir(parents=True, exist_ok=True)
            df_leg = pd.DataFrame(rows)
            df_leg["_source_table"] = source_table
            df_leg["_source_col"] = col
            df_leg["_normalizer"] = SCRIPT_NAME
            df_leg["_normalized_at"] = _utcnow()
            pq.write_table(pa.Table.from_pandas(df_leg, preserve_index=False), part_dir / "part.parquet")
            total_rows += len(df_leg)

        return {
            "satellite": sat_name,
            "status": "written",
            "rows": total_rows,
            "legislaturas": sorted(rows_per_leg.keys()),
        }
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", help="Só explodir esta tabela fonte")
    ap.add_argument("--col", help="Só explodir esta coluna (usar com --table)")
    ap.add_argument("--dry-run", action="store_true", help="Não escreve; mostra schema e amostras")
    ap.add_argument("--all", action="store_true", help="Correr em todos os (tabela, coluna) do inventário")
    args = ap.parse_args()

    if not INVENTORY_JSON.exists():
        print(f"Inventário não encontrado em {INVENTORY_JSON}. Correr 06_inventory_json_columns.py primeiro.")
        sys.exit(1)

    report = json.loads(INVENTORY_JSON.read_text(encoding="utf-8"))
    pairs: list[tuple[str, str]] = []
    for tname, tinfo in report.get("tables", {}).items():
        if "json_columns" not in tinfo:
            continue
        for col in tinfo.get("json_columns", {}):
            pairs.append((tname, col))

    if args.table and args.col:
        pairs = [(args.table, args.col)]
    elif args.table:
        pairs = [p for p in pairs if p[0] == args.table]

    if not pairs:
        print("Nenhum par (tabela, coluna) a processar.")
        sys.exit(1)

    print(f"A processar {len(pairs)} colunas JSON{' (dry-run)' if args.dry_run else ''}...")
    written = skipped = errors = 0
    for i, (tname, col) in enumerate(pairs, 1):
        print(f"  [{i}/{len(pairs)}] {tname}.{col}", flush=True)
        try:
            r = _explode(tname, col, dry_run=args.dry_run)
        except Exception as e:
            r = {"satellite": f"{tname}_{_snake(col)}", "status": "error", "error": str(e)}
            errors += 1
        s = r.get("status")
        if args.dry_run and s == "dry-run":
            print(f"    -> {r['satellite']}: {r['rows_total']:,} linhas, legs={r['legislaturas']}")
            print(f"      schema: {r['schema']}")
            print(f"      sample: {r['samples'][0] if r['samples'] else '(vazio)'}")
        elif s == "written":
            print(f"    -> {r['satellite']}: {r['rows']:,} linhas em {len(r['legislaturas'])} leg(s)")
            written += 1
        elif s == "skipped":
            print(f"    -> saltado: {r['reason']}")
            skipped += 1
        elif s == "error":
            print(f"    -> ERRO: {r.get('error', '')}")

    if not args.dry_run:
        print(f"\nResumo: {written} satélites escritos, {skipped} saltados, {errors} erros.")


if __name__ == "__main__":
    main()
