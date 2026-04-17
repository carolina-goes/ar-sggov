"""
AR-SGGOV — Dashboard Streamlit.

Le db/ar.duckdb (read-only) e oferece quatro paginas:
  - Resumo: KPIs e distribuicao por GP/tipo
  - Iniciativas: filtros multiplos (GP autor, tipo, data, texto)
  - Intervencoes: filtros multiplos (GP, tipo, deputado, data, texto)
  - Perfil de deputado: agregados por DepCadId

Correr:
    python -m streamlit run app/app.py
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "ar.duckdb"
NORM = ROOT / "data" / "normalized"


def _build_duckdb_if_missing() -> None:
    """Reconstrói a DuckDB a partir dos parquet particionados, se o ficheiro
    não existir (cenário típico: container fresco no Streamlit Cloud).
    Corre em ~10s para o volume actual. Chamado uma vez por ciclo de vida
    do container, via `@st.cache_resource` em get_con()."""
    if DB.exists():
        return
    if not NORM.exists() or not any(NORM.iterdir()):
        raise RuntimeError(
            f"Não foi encontrada nem a BD ({DB}) nem os parquet em {NORM}. "
            "Correr `scripts/04_load_to_db.py` localmente primeiro."
        )
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    try:
        tables = sorted(
            p.name for p in NORM.iterdir()
            if p.is_dir() and any(p.rglob("*.parquet"))
        )
        for name in tables:
            glob = (NORM / name / "**" / "*.parquet").as_posix()
            con.execute(
                f'CREATE OR REPLACE TABLE "{name}" AS '
                f"SELECT * FROM read_parquet(?, hive_partitioning=1, union_by_name=true)",
                [glob],
            )
    finally:
        con.close()

st.set_page_config(page_title="AR-SGGOV", layout="wide", initial_sidebar_state="expanded")

# --- Estilo -------------------------------------------------------------
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1400px; }
    h1 { font-size: 1.6rem !important; font-weight: 600; letter-spacing: -0.02em; margin-bottom: 0.5rem; }
    h2 { font-size: 1.15rem !important; font-weight: 600; margin-top: 1.2rem; color: #2d3748; }
    h3 { font-size: 1rem !important; font-weight: 500; color: #4a5568; }
    [data-testid="stMetricValue"] { font-size: 1.4rem; font-weight: 600; color: #1a202c; }
    [data-testid="stMetricLabel"] { font-size: 0.78rem; color: #718096; text-transform: uppercase; letter-spacing: 0.05em; }
    [data-testid="stMetric"] {
        background: #f7fafc; border-radius: 10px; padding: 0.8rem 1rem;
        border: 1px solid #e2e8f0;
    }
    .stDataFrame { border-radius: 8px; overflow: hidden; }
    div[data-testid="stMultiSelect"] label, div[data-testid="stDateInput"] label,
    div[data-testid="stTextInput"] label, div[data-testid="stSlider"] label,
    div[data-testid="stSelectbox"] label {
        font-size: 0.78rem; color: #718096; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em;
    }
    section[data-testid="stSidebar"] { background: #fafbfc; border-right: 1px solid #e2e8f0; }
    section[data-testid="stSidebar"] h1 { font-size: 1.05rem !important; color: #2b6cb0; }
    .filter-bar { background: #f7fafc; padding: 1rem; border-radius: 10px; border: 1px solid #e2e8f0; margin-bottom: 1rem; }
    div[data-baseweb="tag"] { background: #2b6cb0 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Paleta de GPs ------------------------------------------------------
GP_COLORS = {
    "PS": "#e53e3e", "PSD": "#dd6b20", "CH": "#2b6cb0", "IL": "#319795",
    "BE": "#9f1239", "PCP": "#991b1b", "L": "#16a34a", "PAN": "#15803d",
    "CDS-PP": "#1e40af", "JPP": "#0d9488",
}


# --- DuckDB -------------------------------------------------------------
@st.cache_resource
def get_con():
    _build_duckdb_if_missing()
    return duckdb.connect(str(DB), read_only=True)


@st.cache_data(ttl=600, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return get_con().execute(sql, list(params)).fetchdf()


def s(v, default="—"):
    return default if v is None or pd.isna(v) else str(v)


def color_map(gps):
    return {g: GP_COLORS.get(g, "#a0aec0") for g in gps}


def download_button(df: pd.DataFrame, base_name: str, key: str | None = None) -> None:
    """Botão de descarga CSV para um DataFrame filtrado.
    Se o DataFrame for vazio, não mostra nada.
    """
    if df is None or df.empty:
        return
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")  # BOM para Excel abrir com UTF-8
    st.download_button(
        label=f"Descarregar CSV ({len(df):,} linhas)",
        data=csv_bytes,
        file_name=f"{base_name}.csv",
        mime="text/csv",
        key=key or f"dl_{base_name}",
    )


# --- Sidebar ------------------------------------------------------------
st.sidebar.markdown("# AR-SGGOV")
st.sidebar.caption("Plataforma de consulta da Assembleia da República")

pagina = st.sidebar.radio(
    "Navegação",
    [
        "Resumo",
        "Iniciativas",
        "Intervenções",
        "Perguntas e requerimentos",
        "Petições",
        "Diplomas aprovados",
        "Agenda parlamentar",
        "Atividades",
        "Órgãos e comissões",
        "Delegações e visitas",
        "Orçamento do Estado",
        "Perfil de deputado",
        "Descarregar dados",
    ],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")

legs = q("SELECT DISTINCT _legislatura l FROM iniciativas ORDER BY l")["l"].astype(str).tolist()
leg = st.sidebar.selectbox("Legislatura", legs, index=len(legs) - 1 if legs else 0)

# intervalo global de datas (usado em Iniciativas e Intervencoes)
date_bounds = q("SELECT MIN(data) min_d, MAX(data) max_d FROM dim_calendario")
min_d = pd.to_datetime(date_bounds["min_d"][0]).date() if pd.notna(date_bounds["min_d"][0]) else None
max_d = pd.to_datetime(date_bounds["max_d"][0]).date() if pd.notna(date_bounds["max_d"][0]) else None

if min_d and max_d:
    drange = st.sidebar.date_input("Intervalo", value=(min_d, max_d), min_value=min_d, max_value=max_d)
    if isinstance(drange, tuple) and len(drange) == 2:
        d_from, d_to = drange
    else:
        d_from, d_to = min_d, max_d
else:
    d_from = d_to = None

st.sidebar.markdown("---")
st.sidebar.caption(f"BD: `{DB.relative_to(ROOT).as_posix()}`")


# =======================================================================
# Resumo
# =======================================================================
if pagina == "Resumo":
    st.title(f"Resumo — Legislatura {leg}")
    st.caption("Visão agregada da legislatura selecionada.")

    n_ini = int(q("SELECT COUNT(*) n FROM iniciativas WHERE _legislatura=?", (leg,))["n"][0])
    n_int = int(q("SELECT COUNT(*) n FROM intervencoes WHERE _legislatura=?", (leg,))["n"][0])
    n_dep = int(q("SELECT COUNT(*) n FROM deputados WHERE _legislatura=?", (leg,))["n"][0])
    n_evt = int(q("SELECT COUNT(*) n FROM iniciativa_eventos WHERE _legislatura=?", (leg,))["n"][0])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Iniciativas", f"{n_ini:,}")
    c2.metric("Intervenções", f"{n_int:,}")
    c3.metric("Deputados", f"{n_dep:,}")
    c4.metric("Eventos", f"{n_evt:,}")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### Iniciativas por grupo parlamentar")
        df = q(
            """
            SELECT g.GP, COUNT(DISTINCT i.IniId) AS n
            FROM iniciativas i
            JOIN iniciativa_autores_gp g USING(IniId)
            WHERE i._legislatura = ?
            GROUP BY 1 ORDER BY n DESC
            """,
            (leg,),
        )
        fig = px.bar(df, x="GP", y="n", color="GP", color_discrete_map=color_map(df["GP"]))
        fig.update_layout(showlegend=False, height=320, margin=dict(t=10, b=10, l=10, r=10),
                          plot_bgcolor="white", xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.markdown("### Intervenções por grupo parlamentar")
        df = q(
            "SELECT dep_GP GP, COUNT(*) n FROM intervencoes WHERE _legislatura=? AND dep_GP IS NOT NULL GROUP BY 1 ORDER BY n DESC",
            (leg,),
        )
        fig = px.bar(df, x="GP", y="n", color="GP", color_discrete_map=color_map(df["GP"]))
        fig.update_layout(showlegend=False, height=320, margin=dict(t=10, b=10, l=10, r=10),
                          plot_bgcolor="white", xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Iniciativas por tipo")
    df = q(
        "SELECT IniDescTipo Tipo, COUNT(*) Total FROM iniciativas WHERE _legislatura=? AND IniDescTipo IS NOT NULL GROUP BY 1 ORDER BY Total DESC",
        (leg,),
    )
    st.dataframe(df, use_container_width=True, hide_index=True, height=260)


# =======================================================================
# Iniciativas
# =======================================================================
elif pagina == "Iniciativas":
    st.title(f"Iniciativas — Legislatura {leg}")
    st.caption("Filtros combináveis. Use a barra lateral para datas e legislatura.")

    gps_all = q("SELECT DISTINCT GP FROM iniciativa_autores_gp WHERE _legislatura=? AND GP IS NOT NULL ORDER BY 1", (leg,))["GP"].tolist()
    tipos_all = q("SELECT DISTINCT IniDescTipo t FROM iniciativas WHERE _legislatura=? AND IniDescTipo IS NOT NULL ORDER BY 1", (leg,))["t"].tolist()
    deps_all = q(
        """
        SELECT DISTINCT a.nome n FROM iniciativa_autores_deputados a
        JOIN iniciativas i USING(IniId)
        WHERE i._legislatura=? AND a.nome IS NOT NULL ORDER BY 1
        """,
        (leg,),
    )["n"].tolist()

    with st.container():
        f1, f2, f3 = st.columns([2, 2, 2])
        gp_sel = f1.multiselect("Grupo parlamentar autor", gps_all, placeholder="Todos")
        tipo_sel = f2.multiselect("Tipo", tipos_all, placeholder="Todos")
        dep_sel = f3.multiselect("Deputado autor", deps_all, placeholder="Todos")

        f4, f5, f6 = st.columns([3, 1, 1])
        texto = f4.text_input("Pesquisa no título", placeholder="palavra-chave…")
        top_n = f5.slider("Top N", 50, 1000, 200, step=50)
        ordem = f6.selectbox("Ordenar", ["Data desc", "Data asc", "Tipo", "GP"])

    where = ["i._legislatura = ?"]
    params: list = [leg]
    if d_from and d_to:
        where.append("(i.data_entrada IS NULL OR i.data_entrada BETWEEN ? AND ?)")
        params.extend([d_from, d_to])
    if gp_sel:
        where.append("EXISTS (SELECT 1 FROM iniciativa_autores_gp g WHERE g.IniId=i.IniId AND g.GP IN (" + ",".join(["?"] * len(gp_sel)) + "))")
        params.extend(gp_sel)
    if dep_sel:
        where.append("EXISTS (SELECT 1 FROM iniciativa_autores_deputados a WHERE a.IniId=i.IniId AND a.nome IN (" + ",".join(["?"] * len(dep_sel)) + "))")
        params.extend(dep_sel)
    if tipo_sel:
        where.append("i.IniDescTipo IN (" + ",".join(["?"] * len(tipo_sel)) + ")")
        params.extend(tipo_sel)
    if texto:
        where.append("i.IniTitulo ILIKE ?")
        params.append(f"%{texto}%")

    order_sql = {"Data desc": "i.data_entrada DESC NULLS LAST",
                 "Data asc":  "i.data_entrada ASC NULLS LAST",
                 "Tipo":      "i.IniDescTipo, i.data_entrada DESC",
                 "GP":        "i.IniNr"}[ordem]

    sql = f"""
    SELECT i.IniNr AS nr, i.IniDescTipo AS tipo, i.IniTitulo AS titulo,
           i.data_entrada AS data_ini, i.IniLinkTexto AS texto
    FROM iniciativas i
    WHERE {' AND '.join(where)}
    ORDER BY {order_sql}
    LIMIT ?
    """
    df = q(sql, tuple(params + [top_n]))

    k1, k2, k3 = st.columns(3)
    k1.metric("Resultados", f"{len(df):,}")
    k2.metric("Tipos distintos", df["tipo"].nunique() if not df.empty else 0)
    k3.metric("Com data", int(df["data_ini"].notna().sum()) if not df.empty else 0)

    if not df.empty and df["data_ini"].notna().any():
        ts = df.copy()
        ts["mes"] = pd.to_datetime(ts["data_ini"]).dt.to_period("M").astype(str)
        agg = ts.groupby("mes").size().reset_index(name="n")
        fig = px.bar(agg, x="mes", y="n")
        fig.update_layout(height=180, margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor="white",
                          xaxis_title=None, yaxis_title=None)
        fig.update_traces(marker_color="#2b6cb0")
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        df, use_container_width=True, hide_index=True, height=440,
        column_config={
            "nr": st.column_config.TextColumn("Nº"),
            "tipo": st.column_config.TextColumn("Tipo"),
            "titulo": st.column_config.TextColumn("Título", width="large"),
            "data_ini": st.column_config.DateColumn("Data", format="YYYY-MM-DD"),
            "texto": st.column_config.LinkColumn("Texto", display_text="abrir"),
        },
    )
    download_button(df, f"iniciativas_leg{leg}", key="dl_ini")


# =======================================================================
# Intervenções
# =======================================================================
elif pagina == "Intervenções":
    st.title(f"Intervenções — Legislatura {leg}")
    st.caption("Filtros combináveis. Sumários e ligações ao DAR.")

    gps_all = q("SELECT DISTINCT dep_GP g FROM intervencoes WHERE _legislatura=? AND dep_GP IS NOT NULL ORDER BY 1", (leg,))["g"].tolist()
    tipos_all = q("SELECT DISTINCT TipoIntervencao t FROM intervencoes WHERE _legislatura=? AND TipoIntervencao IS NOT NULL ORDER BY 1", (leg,))["t"].tolist()
    deps_all = q("SELECT DISTINCT dep_nome n FROM intervencoes WHERE _legislatura=? AND dep_nome IS NOT NULL ORDER BY 1", (leg,))["n"].tolist()
    qual_all = q("SELECT DISTINCT Qualidade q FROM intervencoes WHERE _legislatura=? AND Qualidade IS NOT NULL ORDER BY 1", (leg,))["q"].tolist()

    f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
    gp_sel = f1.multiselect("Grupo parlamentar", gps_all, placeholder="Todos")
    tipo_sel = f2.multiselect("Tipo", tipos_all, placeholder="Todos")
    dep_sel = f3.multiselect("Deputado", deps_all, placeholder="Todos")
    qual_sel = f4.multiselect("Qualidade", qual_all, placeholder="Todas")

    f5, f6, f7 = st.columns([3, 1, 1])
    texto = f5.text_input("Pesquisa no sumário/resumo", placeholder="palavra-chave…")
    top_n = f6.slider("Top N", 50, 2000, 300, step=50)
    ordem = f7.selectbox("Ordenar", ["Data desc", "Data asc", "Deputado", "GP"])

    where = ["_legislatura = ?"]
    params: list = [leg]
    if d_from and d_to:
        where.append("(DataReuniaoPlenaria IS NULL OR DataReuniaoPlenaria BETWEEN ? AND ?)")
        params.extend([d_from, d_to])
    if gp_sel:
        where.append("dep_GP IN (" + ",".join(["?"] * len(gp_sel)) + ")")
        params.extend(gp_sel)
    if tipo_sel:
        where.append("TipoIntervencao IN (" + ",".join(["?"] * len(tipo_sel)) + ")")
        params.extend(tipo_sel)
    if dep_sel:
        where.append("dep_nome IN (" + ",".join(["?"] * len(dep_sel)) + ")")
        params.extend(dep_sel)
    if qual_sel:
        where.append("Qualidade IN (" + ",".join(["?"] * len(qual_sel)) + ")")
        params.extend(qual_sel)
    if texto:
        where.append("(Sumario ILIKE ? OR Resumo ILIKE ?)")
        params.extend([f"%{texto}%", f"%{texto}%"])

    order_sql = {"Data desc": "DataReuniaoPlenaria DESC NULLS LAST",
                 "Data asc":  "DataReuniaoPlenaria ASC NULLS LAST",
                 "Deputado":  "dep_nome, DataReuniaoPlenaria DESC",
                 "GP":        "dep_GP, DataReuniaoPlenaria DESC"}[ordem]

    sql = f"""
    SELECT DataReuniaoPlenaria AS data_reu, dep_GP AS gp, dep_nome AS deputado,
           Qualidade AS qualidade, TipoIntervencao AS tipo, Sumario AS sumario,
           pub_URLDiario AS dar, av_url AS video
    FROM intervencoes
    WHERE {' AND '.join(where)}
    ORDER BY {order_sql}
    LIMIT ?
    """
    df = q(sql, tuple(params + [top_n]))

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Resultados", f"{len(df):,}")
    k2.metric("Deputados", df["deputado"].nunique() if not df.empty else 0)
    k3.metric("GPs", df["gp"].nunique() if not df.empty else 0)
    k4.metric("Tipos", df["tipo"].nunique() if not df.empty else 0)

    if not df.empty and df["data_reu"].notna().any():
        ts = df.copy()
        ts["dia"] = pd.to_datetime(ts["data_reu"]).dt.date
        agg = ts.groupby(["dia", "gp"]).size().reset_index(name="n")
        fig = px.bar(agg, x="dia", y="n", color="gp", color_discrete_map=color_map(df["gp"].dropna().unique()))
        fig.update_layout(height=220, margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor="white",
                          xaxis_title=None, yaxis_title=None, legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        df, use_container_width=True, hide_index=True, height=420,
        column_config={
            "data_reu": st.column_config.DateColumn("Data", format="YYYY-MM-DD"),
            "gp": st.column_config.TextColumn("GP"),
            "deputado": st.column_config.TextColumn("Deputado"),
            "qualidade": st.column_config.TextColumn("Qualidade"),
            "tipo": st.column_config.TextColumn("Tipo"),
            "sumario": st.column_config.TextColumn("Sumário", width="large"),
            "dar": st.column_config.LinkColumn("DAR", display_text="ler"),
            "video": st.column_config.LinkColumn("Vídeo", display_text="ver"),
        },
    )
    download_button(df, f"intervencoes_leg{leg}", key="dl_intervencoes")


# =======================================================================
# Perguntas e requerimentos
# =======================================================================
elif pagina == "Perguntas e requerimentos":
    st.title(f"Perguntas e requerimentos — Legislatura {leg}")
    st.caption("Perguntas ao Governo e requerimentos por deputados.")

    # nota: rótulos de IU em pt-PT com diacríticos; identificadores SQL mantêm-se ASCII.

    gps_all = q("SELECT DISTINCT GP g FROM pergunta_autores WHERE _legislatura=? AND GP IS NOT NULL ORDER BY 1", (leg,))["g"].tolist()
    tipos_all = q("SELECT DISTINCT Tipo t FROM perguntas_e_requerimentos WHERE _legislatura=? AND Tipo IS NOT NULL ORDER BY 1", (leg,))["t"].tolist()
    reqtipos_all = q("SELECT DISTINCT ReqTipo t FROM perguntas_e_requerimentos WHERE _legislatura=? AND ReqTipo IS NOT NULL ORDER BY 1", (leg,))["t"].tolist()
    deps_all = q("SELECT DISTINCT nome n FROM pergunta_autores WHERE _legislatura=? AND nome IS NOT NULL ORDER BY 1", (leg,))["n"].tolist()
    dest_all = q("SELECT DISTINCT nomeEntidade e FROM pergunta_destinatarios WHERE _legislatura=? AND nomeEntidade IS NOT NULL ORDER BY 1", (leg,))["e"].tolist()

    f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
    gp_sel = f1.multiselect("Grupo parlamentar autor", gps_all, placeholder="Todos")
    tipo_sel = f2.multiselect("Tipo", tipos_all, placeholder="Todos")
    req_sel = f3.multiselect("Tipo de requerimento", reqtipos_all, placeholder="Todos")
    dest_sel = f4.multiselect("Destinatário", dest_all, placeholder="Todos")

    f5, f6, f7, f8 = st.columns([3, 2, 1, 1])
    dep_sel = f5.multiselect("Deputado autor", deps_all, placeholder="Todos")
    texto = f6.text_input("Pesquisa no assunto", placeholder="palavra-chave…")
    top_n = f7.slider("Top N", 50, 2000, 300, step=50)
    ordem = f8.selectbox("Ordenar", ["Data desc", "Data asc", "Tipo"])

    where = ["p._legislatura = ?"]
    params: list = [leg]
    if d_from and d_to:
        where.append("(p.DataEnvio IS NULL OR p.DataEnvio BETWEEN ? AND ?)")
        params.extend([d_from, d_to])
    if tipo_sel:
        where.append("p.Tipo IN (" + ",".join(["?"] * len(tipo_sel)) + ")")
        params.extend(tipo_sel)
    if req_sel:
        where.append("p.ReqTipo IN (" + ",".join(["?"] * len(req_sel)) + ")")
        params.extend(req_sel)
    if gp_sel:
        where.append("EXISTS (SELECT 1 FROM pergunta_autores a WHERE a.Id=p.Id AND a.GP IN (" + ",".join(["?"] * len(gp_sel)) + "))")
        params.extend(gp_sel)
    if dep_sel:
        where.append("EXISTS (SELECT 1 FROM pergunta_autores a WHERE a.Id=p.Id AND a.nome IN (" + ",".join(["?"] * len(dep_sel)) + "))")
        params.extend(dep_sel)
    if dest_sel:
        where.append("EXISTS (SELECT 1 FROM pergunta_destinatarios d WHERE d.Id=p.Id AND d.nomeEntidade IN (" + ",".join(["?"] * len(dest_sel)) + "))")
        params.extend(dest_sel)
    if texto:
        where.append("p.Assunto ILIKE ?")
        params.append(f"%{texto}%")

    order_sql = {"Data desc": "p.DataEnvio DESC NULLS LAST",
                 "Data asc":  "p.DataEnvio ASC NULLS LAST",
                 "Tipo":      "p.Tipo, p.DataEnvio DESC"}[ordem]

    sql = f"""
    SELECT p.Id AS id_p, p.Nr AS nr, p.Tipo AS tipo, p.ReqTipo AS reqtipo,
           p.Assunto AS assunto, p.DataEnvio AS data_envio, p.Ficheiro AS ficheiro,
           (SELECT string_agg(DISTINCT a.GP, ', ') FROM pergunta_autores a WHERE a.Id=p.Id) AS gps,
           (SELECT string_agg(DISTINCT d.nomeEntidade, ', ') FROM pergunta_destinatarios d WHERE d.Id=p.Id) AS destinatarios
    FROM perguntas_e_requerimentos p
    WHERE {' AND '.join(where)}
    ORDER BY {order_sql}
    LIMIT ?
    """
    df = q(sql, tuple(params + [top_n]))

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Resultados", f"{len(df):,}")
    k2.metric("Tipos", df["tipo"].nunique() if not df.empty else 0)
    k3.metric("Tipos de requerimento", df["reqtipo"].nunique() if not df.empty else 0)
    k4.metric("Com resposta", "—")

    if not df.empty and df["data_envio"].notna().any():
        ts = df.copy()
        ts["mes"] = pd.to_datetime(ts["data_envio"]).dt.to_period("M").astype(str)
        agg = ts.groupby("mes").size().reset_index(name="n")
        fig = px.bar(agg, x="mes", y="n")
        fig.update_layout(height=200, margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor="white",
                          xaxis_title=None, yaxis_title=None)
        fig.update_traces(marker_color="#2b6cb0")
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        df.drop(columns=["id_p"]), use_container_width=True, hide_index=True, height=440,
        column_config={
            "nr": st.column_config.TextColumn("Nº"),
            "tipo": st.column_config.TextColumn("Tipo"),
            "reqtipo": st.column_config.TextColumn("Tipo de requerimento"),
            "assunto": st.column_config.TextColumn("Assunto", width="large"),
            "data_envio": st.column_config.DateColumn("Envio", format="YYYY-MM-DD"),
            "ficheiro": st.column_config.LinkColumn("Ficheiro", display_text="abrir"),
            "gps": st.column_config.TextColumn("Grupos parlamentares"),
            "destinatarios": st.column_config.TextColumn("Destinatários", width="medium"),
        },
    )
    download_button(df.drop(columns=["id_p"]), f"perguntas_e_requerimentos_leg{leg}", key="dl_perguntas")


# =======================================================================
# Petições
# =======================================================================
elif pagina == "Petições":
    st.title(f"Petições — Legislatura {leg}")
    st.caption("Petições dos cidadãos e respetivo estado de tramitação.")

    sit_all = q("SELECT DISTINCT PetSituacao s FROM peticoes WHERE _legislatura=? AND PetSituacao IS NOT NULL ORDER BY 1", (leg,))["s"].tolist()
    com_all = q("SELECT DISTINCT Nome n FROM peticao_dados_comissao WHERE _legislatura=? AND Nome IS NOT NULL ORDER BY 1", (leg,))["n"].tolist()

    f1, f2, f3 = st.columns([2, 3, 2])
    sit_sel = f1.multiselect("Situação", sit_all, placeholder="Todas")
    com_sel = f2.multiselect("Comissão", com_all, placeholder="Todas")
    min_assin = f3.number_input("Mín. assinaturas", min_value=0, value=0, step=100)

    f4, f5, f6 = st.columns([3, 1, 1])
    texto = f4.text_input("Pesquisa no assunto ou autor", placeholder="palavra-chave…")
    top_n = f5.slider("Top N", 20, 500, 200, step=20)
    ordem = f6.selectbox("Ordenar", ["Data desc", "Assinaturas desc", "Situação"])

    where = ["p._legislatura = ?"]
    params: list = [leg]
    if d_from and d_to:
        where.append("(p.PetDataEntrada IS NULL OR p.PetDataEntrada BETWEEN ? AND ?)")
        params.extend([d_from, d_to])
    if sit_sel:
        where.append("p.PetSituacao IN (" + ",".join(["?"] * len(sit_sel)) + ")")
        params.extend(sit_sel)
    if com_sel:
        where.append("EXISTS (SELECT 1 FROM peticao_dados_comissao c WHERE c.PetId=p.PetId AND c.Nome IN (" + ",".join(["?"] * len(com_sel)) + "))")
        params.extend(com_sel)
    if min_assin and int(min_assin) > 0:
        where.append("TRY_CAST(p.PetNrAssinaturas AS INTEGER) >= ?")
        params.append(int(min_assin))
    if texto:
        where.append("(p.PetAssunto ILIKE ? OR p.PetAutor ILIKE ?)")
        params.extend([f"%{texto}%", f"%{texto}%"])

    order_sql = {"Data desc": "p.PetDataEntrada DESC NULLS LAST",
                 "Assinaturas desc": "TRY_CAST(p.PetNrAssinaturas AS INTEGER) DESC NULLS LAST",
                 "Situação": "p.PetSituacao, p.PetDataEntrada DESC"}[ordem]

    sql = f"""
    SELECT p.PetNr AS nr, p.PetDataEntrada AS data_ent, p.PetAutor AS autor,
           p.PetAssunto AS assunto, p.PetSituacao AS situacao,
           TRY_CAST(p.PetNrAssinaturas AS INTEGER) AS assinaturas,
           p.PetUrlTexto AS texto,
           (SELECT string_agg(DISTINCT c.Nome, ', ') FROM peticao_dados_comissao c WHERE c.PetId=p.PetId) AS comissoes
    FROM peticoes p
    WHERE {' AND '.join(where)}
    ORDER BY {order_sql}
    LIMIT ?
    """
    df = q(sql, tuple(params + [top_n]))

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Resultados", f"{len(df):,}")
    k2.metric("Situações", df["situacao"].nunique() if not df.empty else 0)
    k3.metric("Total assinaturas", f"{int(df['assinaturas'].sum(skipna=True)):,}" if not df.empty else "0")
    k4.metric("Mediana assin.", f"{int(df['assinaturas'].median(skipna=True)):,}" if not df.empty and df["assinaturas"].notna().any() else "—")

    if not df.empty and df["data_ent"].notna().any():
        ts = df.copy()
        ts["mes"] = pd.to_datetime(ts["data_ent"]).dt.to_period("M").astype(str)
        agg = ts.groupby("mes").size().reset_index(name="n")
        fig = px.bar(agg, x="mes", y="n")
        fig.update_layout(height=200, margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor="white",
                          xaxis_title=None, yaxis_title=None)
        fig.update_traces(marker_color="#2b6cb0")
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        df, use_container_width=True, hide_index=True, height=440,
        column_config={
            "nr": st.column_config.TextColumn("Nº"),
            "data_ent": st.column_config.DateColumn("Entrada", format="YYYY-MM-DD"),
            "autor": st.column_config.TextColumn("Autor"),
            "assunto": st.column_config.TextColumn("Assunto", width="large"),
            "situacao": st.column_config.TextColumn("Situação"),
            "assinaturas": st.column_config.NumberColumn("Assinaturas", format="%d"),
            "texto": st.column_config.LinkColumn("Texto", display_text="abrir"),
            "comissoes": st.column_config.TextColumn("Comissões", width="medium"),
        },
    )
    download_button(df, f"peticoes_leg{leg}", key="dl_peticoes")


# =======================================================================
# Diplomas aprovados
# =======================================================================
elif pagina == "Diplomas aprovados":
    st.title(f"Diplomas aprovados — Legislatura {leg}")
    st.caption("Diplomas aprovados em plenário com a respetiva publicação no Diário da República.")

    tipos_all = q("SELECT DISTINCT Tipo t FROM diplomas_aprovados WHERE _legislatura=? AND Tipo IS NOT NULL ORDER BY 1", (leg,))["t"].tolist()
    anos_all = q("SELECT DISTINCT AnoCivil a FROM diplomas_aprovados WHERE _legislatura=? AND AnoCivil IS NOT NULL ORDER BY 1", (leg,))["a"].tolist()
    sessoes_all = q("SELECT DISTINCT Sessao s FROM diplomas_aprovados WHERE _legislatura=? AND Sessao IS NOT NULL ORDER BY 1", (leg,))["s"].tolist()

    f1, f2, f3 = st.columns([2, 2, 2])
    tipo_sel = f1.multiselect("Tipo", tipos_all, placeholder="Todos")
    ano_sel = f2.multiselect("Ano civil", anos_all, placeholder="Todos")
    sessao_sel = f3.multiselect("Sessão", sessoes_all, placeholder="Todas")

    f4, f5, f6 = st.columns([3, 1, 1])
    texto = f4.text_input("Pesquisa no título", placeholder="palavra-chave…")
    top_n = f5.slider("Top N", 50, 1000, 200, step=50)
    ordem = f6.selectbox("Ordenar", ["Publicação desc", "Número", "Tipo"])

    where = ["d._legislatura = ?"]
    params: list = [leg]
    if tipo_sel:
        where.append("d.Tipo IN (" + ",".join(["?"] * len(tipo_sel)) + ")")
        params.extend(tipo_sel)
    if ano_sel:
        where.append("d.AnoCivil IN (" + ",".join(["?"] * len(ano_sel)) + ")")
        params.extend(ano_sel)
    if sessao_sel:
        where.append("d.Sessao IN (" + ",".join(["?"] * len(sessao_sel)) + ")")
        params.extend(sessao_sel)
    if texto:
        where.append("d.Titulo ILIKE ?")
        params.append(f"%{texto}%")

    order_sql = {"Publicação desc": "pub.pubdt DESC NULLS LAST",
                 "Número": "TRY_CAST(d.Numero AS INTEGER) DESC NULLS LAST",
                 "Tipo": "d.Tipo, d.Numero"}[ordem]

    sql = f"""
    SELECT d.Tipo AS tipo, d.Numero AS numero, d.AnoCivil AS ano,
           d.Titulo AS titulo, d.LinkTexto AS texto,
           pub.pubdt AS data_pub, pub.URLDiario AS dar,
           (SELECT string_agg(DISTINCT i.IniTipo || ' ' || i.IniNr, ', ')
            FROM diploma_iniciativas i WHERE i.Id=d.Id) AS iniciativas_origem
    FROM diplomas_aprovados d
    LEFT JOIN (
      SELECT Id, MIN(pubdt) pubdt, ANY_VALUE(URLDiario) URLDiario
      FROM diploma_publicacao GROUP BY Id
    ) pub USING(Id)
    WHERE {' AND '.join(where)}
    ORDER BY {order_sql}
    LIMIT ?
    """
    df = q(sql, tuple(params + [top_n]))

    k1, k2, k3 = st.columns(3)
    k1.metric("Resultados", f"{len(df):,}")
    k2.metric("Tipos", df["tipo"].nunique() if not df.empty else 0)
    k3.metric("Anos", df["ano"].nunique() if not df.empty else 0)

    if not df.empty and df["data_pub"].notna().any():
        ts = df.copy()
        ts["mes"] = pd.to_datetime(ts["data_pub"]).dt.to_period("M").astype(str)
        agg = ts.groupby(["mes", "tipo"]).size().reset_index(name="n")
        fig = px.bar(agg, x="mes", y="n", color="tipo")
        fig.update_layout(height=220, margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor="white",
                          xaxis_title=None, yaxis_title=None, legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        df, use_container_width=True, hide_index=True, height=440,
        column_config={
            "tipo": st.column_config.TextColumn("Tipo"),
            "numero": st.column_config.TextColumn("Número"),
            "ano": st.column_config.TextColumn("Ano"),
            "titulo": st.column_config.TextColumn("Título", width="large"),
            "texto": st.column_config.LinkColumn("Texto", display_text="abrir"),
            "data_pub": st.column_config.DateColumn("DR (data)", format="YYYY-MM-DD"),
            "dar": st.column_config.LinkColumn("DR", display_text="abrir"),
            "iniciativas_origem": st.column_config.TextColumn("Iniciativa de origem"),
        },
    )
    download_button(df, f"diplomas_aprovados_leg{leg}", key="dl_diplomas")


# =======================================================================
# Agenda parlamentar
# =======================================================================
elif pagina == "Agenda parlamentar":
    st.title(f"Agenda parlamentar — Legislatura {leg}")
    st.caption("Eventos institucionais, reuniões plenárias e atividades agendadas.")

    sections_all = q("SELECT DISTINCT Section s FROM agenda_parlamentar WHERE _legislatura=? AND Section IS NOT NULL ORDER BY 1", (leg,))["s"].tolist()
    themes_all = q("SELECT DISTINCT Theme t FROM agenda_parlamentar WHERE _legislatura=? AND Theme IS NOT NULL ORDER BY 1", (leg,))["t"].tolist()
    locais_all = q("SELECT DISTINCT Local l FROM agenda_parlamentar WHERE _legislatura=? AND Local IS NOT NULL ORDER BY 1", (leg,))["l"].tolist()

    f1, f2, f3 = st.columns([2, 2, 2])
    sec_sel = f1.multiselect("Secção", sections_all, placeholder="Todas")
    tema_sel = f2.multiselect("Tema", themes_all, placeholder="Todos")
    local_sel = f3.multiselect("Local", locais_all, placeholder="Todos")

    f4, f5, f6 = st.columns([3, 1, 1])
    texto = f4.text_input("Pesquisa no título/subtítulo", placeholder="palavra-chave…")
    top_n = f5.slider("Top N", 20, 500, 200, step=20)
    ordem = f6.selectbox("Ordenar", ["Data desc", "Data asc"])

    where = ["_legislatura = ?"]
    params: list = [leg]
    if d_from and d_to:
        where.append("(data_inicio IS NULL OR CAST(data_inicio AS DATE) BETWEEN ? AND ?)")
        params.extend([d_from, d_to])
    if sec_sel:
        where.append("Section IN (" + ",".join(["?"] * len(sec_sel)) + ")")
        params.extend(sec_sel)
    if tema_sel:
        where.append("Theme IN (" + ",".join(["?"] * len(tema_sel)) + ")")
        params.extend(tema_sel)
    if local_sel:
        where.append("Local IN (" + ",".join(["?"] * len(local_sel)) + ")")
        params.extend(local_sel)
    if texto:
        where.append("(Title ILIKE ? OR Subtitle ILIKE ?)")
        params.extend([f"%{texto}%", f"%{texto}%"])

    order_sql = "data_inicio DESC NULLS LAST" if ordem == "Data desc" else "data_inicio ASC NULLS LAST"

    sql = f"""
    SELECT data_inicio AS inicio, data_fim AS fim, Section AS seccao,
           Theme AS tema, Title AS titulo, Subtitle AS subtitulo,
           Local AS local, Link AS link
    FROM agenda_parlamentar
    WHERE {' AND '.join(where)}
    ORDER BY {order_sql}
    LIMIT ?
    """
    df = q(sql, tuple(params + [top_n]))

    k1, k2, k3 = st.columns(3)
    k1.metric("Eventos", f"{len(df):,}")
    k2.metric("Secções", df["seccao"].nunique() if not df.empty else 0)
    k3.metric("Temas", df["tema"].nunique() if not df.empty else 0)

    if not df.empty and df["inicio"].notna().any():
        ts = df.copy()
        ts["dia"] = pd.to_datetime(ts["inicio"]).dt.date
        agg = ts.groupby(["dia", "seccao"]).size().reset_index(name="n")
        fig = px.bar(agg, x="dia", y="n", color="seccao")
        fig.update_layout(height=220, margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor="white",
                          xaxis_title=None, yaxis_title=None, legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        df, use_container_width=True, hide_index=True, height=440,
        column_config={
            "inicio": st.column_config.DatetimeColumn("Início", format="YYYY-MM-DD HH:mm"),
            "fim": st.column_config.DatetimeColumn("Fim", format="YYYY-MM-DD HH:mm"),
            "seccao": st.column_config.TextColumn("Secção"),
            "tema": st.column_config.TextColumn("Tema"),
            "titulo": st.column_config.TextColumn("Título", width="large"),
            "subtitulo": st.column_config.TextColumn("Subtítulo", width="medium"),
            "local": st.column_config.TextColumn("Local"),
            "link": st.column_config.LinkColumn("Link", display_text="abrir"),
        },
    )
    download_button(df, f"agenda_parlamentar_leg{leg}", key="dl_agenda")


# =======================================================================
# Atividades
# =======================================================================
elif pagina == "Atividades":
    st.title(f"Atividades — Legislatura {leg}")
    st.caption("Atividades globais da Assembleia da República agrupadas por tipo.")

    tab_audic, tab_audien, tab_deb, tab_desl, tab_evt, tab_ger, tab_rel = st.tabs(
        ["Audições", "Audiências", "Debates", "Deslocações", "Eventos", "Gerais", "Relatórios"]
    )

    def _atividade_view(tab, table_name, label):
        with tab:
            df = q(
                f"SELECT * FROM {table_name} WHERE _legislatura=? ORDER BY _data DESC NULLS LAST LIMIT 1000",
                (leg,),
            )
            cols_show = [c for c in df.columns if not c.startswith("_") and not c.endswith("_json")]
            st.metric(label, f"{len(df):,}")
            if not df.empty and "_data" in df.columns and df["_data"].notna().any():
                ts = df.copy()
                ts["mes"] = pd.to_datetime(ts["_data"]).dt.to_period("M").astype(str)
                agg = ts.groupby("mes").size().reset_index(name="n")
                fig = px.bar(agg, x="mes", y="n")
                fig.update_layout(height=180, margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor="white",
                                  xaxis_title=None, yaxis_title=None)
                fig.update_traces(marker_color="#2b6cb0")
                st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df[cols_show], use_container_width=True, hide_index=True, height=420)
            download_button(df[cols_show], f"{table_name}_leg{leg}", key=f"dl_{table_name}")

    _atividade_view(tab_audic, "atividades_audicoes", "Audições")
    _atividade_view(tab_audien, "atividades_audiencias", "Audiências")
    _atividade_view(tab_deb, "atividades_debates", "Debates")
    _atividade_view(tab_desl, "atividades_deslocacoes", "Deslocações")
    _atividade_view(tab_evt, "atividades_eventos", "Eventos")
    _atividade_view(tab_ger, "atividades_gerais", "Atividades gerais")
    _atividade_view(tab_rel, "atividades_relatorios", "Relatórios")


# =======================================================================
# Órgãos e comissões
# =======================================================================
elif pagina == "Órgãos e comissões":
    st.title(f"Órgãos e comissões — Legislatura {leg}")
    st.caption("Composição dos órgãos parlamentares: comissões permanentes, mesa, conferências, conselhos.")

    tipos_all = q("SELECT DISTINCT tipo_orgao t FROM orgaos_detalhe WHERE _legislatura=? ORDER BY 1", (leg,))["t"].tolist()
    f1, f2 = st.columns([2, 4])
    tipo_sel = f1.multiselect("Tipo de órgão", tipos_all, placeholder="Todos")
    texto = f2.text_input("Pesquisa por nome do órgão", placeholder="palavra-chave…")

    where = ["_legislatura = ?"]
    params: list = [leg]
    if tipo_sel:
        where.append("tipo_orgao IN (" + ",".join(["?"] * len(tipo_sel)) + ")")
        params.extend(tipo_sel)
    if texto:
        where.append("(COALESCE(oDes,'') ILIKE ? OR COALESCE(cargoDes,'') ILIKE ?)")
        params.extend([f"%{texto}%", f"%{texto}%"])

    sql_det = f"SELECT * FROM orgaos_detalhe WHERE {' AND '.join(where)} ORDER BY tipo_orgao"
    detalhe = q(sql_det, tuple(params))
    cols_det = [c for c in detalhe.columns if not c.startswith("_") and not c.endswith("_json")]

    k1, k2 = st.columns(2)
    k1.metric("Órgãos", f"{len(detalhe):,}")
    k2.metric("Tipos", detalhe["tipo_orgao"].nunique() if not detalhe.empty else 0)

    st.markdown("### Órgãos")
    st.dataframe(detalhe[cols_det], use_container_width=True, hide_index=True, height=300)
    download_button(detalhe[cols_det], f"orgaos_detalhe_leg{leg}", key="dl_orgaos_det")

    st.markdown("### Histórico de composição (membros)")
    where2 = ["_legislatura = ?"]
    params2: list = [leg]
    if tipo_sel:
        where2.append("tipo_orgao IN (" + ",".join(["?"] * len(tipo_sel)) + ")")
        params2.extend(tipo_sel)
    comp = q(
        f"SELECT * FROM orgaos_historico_composicao WHERE {' AND '.join(where2)} LIMIT 2000",
        tuple(params2),
    )
    cols_comp = [c for c in comp.columns if not c.startswith("_") and not c.endswith("_json")]
    st.caption(f"{len(comp):,} registos (máximo 2000)")
    st.dataframe(comp[cols_comp], use_container_width=True, hide_index=True, height=420)
    download_button(comp[cols_comp], f"orgaos_historico_composicao_leg{leg}", key="dl_orgaos_comp")


# =======================================================================
# Delegações e visitas
# =======================================================================
elif pagina == "Delegações e visitas":
    st.title(f"Delegações e visitas — Legislatura {leg}")
    st.caption("Delegações eventuais e permanentes, grupos de amizade, reuniões e visitas.")

    tab_dev, tab_dep, tab_amz, tab_rev = st.tabs(
        ["Delegações eventuais", "Delegações permanentes", "Grupos de amizade", "Reuniões e visitas"]
    )

    with tab_dev:
        df = q("SELECT Id, Nome, Local, data_inicio, data_fim, Sessao FROM delegacoes_eventuais WHERE _legislatura=? ORDER BY data_inicio DESC NULLS LAST", (leg,))
        st.metric("Delegações eventuais", f"{len(df):,}")
        st.dataframe(
            df, use_container_width=True, hide_index=True, height=400,
            column_config={
                "data_inicio": st.column_config.DateColumn("Início", format="YYYY-MM-DD"),
                "data_fim": st.column_config.DateColumn("Fim", format="YYYY-MM-DD"),
                "Nome": st.column_config.TextColumn("Nome", width="large"),
                "Local": st.column_config.TextColumn("Local"),
                "Sessao": st.column_config.TextColumn("Sessão"),
            },
        )
        download_button(df, f"delegacoes_eventuais_leg{leg}", key="dl_del_ev")
        sel_id = st.selectbox("Ver participantes da delegação", [""] + df["Id"].astype(str).tolist())
        if sel_id:
            parts = q("SELECT Nome, Gp, Tipo FROM delegacao_eventual_participantes WHERE _legislatura=? AND Id=?", (leg, sel_id))
            st.dataframe(parts, use_container_width=True, hide_index=True, height=240)

    with tab_dep:
        df = q("SELECT Id, Nome, data_inicio AS data_eleicao, Sessao FROM delegacoes_permanentes WHERE _legislatura=? ORDER BY Nome", (leg,))
        st.metric("Delegações permanentes", f"{len(df):,}")
        st.dataframe(
            df, use_container_width=True, hide_index=True, height=440,
            column_config={
                "data_eleicao": st.column_config.DateColumn("Data eleição", format="YYYY-MM-DD"),
                "Nome": st.column_config.TextColumn("Nome", width="large"),
                "Sessao": st.column_config.TextColumn("Sessão"),
            },
        )
        download_button(df, f"delegacoes_permanentes_leg{leg}", key="dl_del_perm")

    with tab_amz:
        df = q("SELECT Id, Nome, data_inicio AS data_criacao, Sessao FROM grupos_parlamentares_de_amizade WHERE _legislatura=? ORDER BY Nome", (leg,))
        st.metric("Grupos de amizade", f"{len(df):,}")
        st.dataframe(
            df, use_container_width=True, hide_index=True, height=400,
            column_config={
                "data_criacao": st.column_config.DateColumn("Data criação", format="YYYY-MM-DD"),
                "Nome": st.column_config.TextColumn("Nome", width="large"),
                "Sessao": st.column_config.TextColumn("Sessão"),
            },
        )
        download_button(df, f"grupos_amizade_leg{leg}", key="dl_amz")
        sel_id = st.selectbox("Ver composição do grupo", [""] + df["Id"].astype(str).tolist(), key="amz_sel")
        if sel_id:
            comp = q("SELECT Nome, Gp, Cargo, DataInicio, DataFim FROM grupo_amizade_composicao WHERE _legislatura=? AND Id=? ORDER BY Cargo", (leg, sel_id))
            st.dataframe(
                comp, use_container_width=True, hide_index=True, height=300,
                column_config={
                    "DataInicio": st.column_config.DateColumn("Início", format="YYYY-MM-DD"),
                    "DataFim": st.column_config.DateColumn("Fim", format="YYYY-MM-DD"),
                },
            )

    with tab_rev:
        df = q("SELECT Id, Nome, Tipo, Local, Promotor, data_inicio, data_fim FROM reunioes_e_visitas WHERE _legislatura=? ORDER BY data_inicio DESC NULLS LAST", (leg,))
        tipos = sorted(df["Tipo"].dropna().unique().tolist()) if not df.empty else []
        sel_tipo = st.multiselect("Tipo", tipos, placeholder="Todos", key="rev_tipo")
        df_view = df[df["Tipo"].isin(sel_tipo)] if sel_tipo else df
        st.metric("Reuniões/visitas", f"{len(df_view):,}")
        st.dataframe(
            df_view, use_container_width=True, hide_index=True, height=440,
            column_config={
                "data_inicio": st.column_config.DateColumn("Início", format="YYYY-MM-DD"),
                "data_fim": st.column_config.DateColumn("Fim", format="YYYY-MM-DD"),
                "Nome": st.column_config.TextColumn("Nome", width="large"),
                "Promotor": st.column_config.TextColumn("Promotor"),
                "Local": st.column_config.TextColumn("Local"),
            },
        )
        download_button(df_view, f"reunioes_e_visitas_leg{leg}", key="dl_rev")


# =======================================================================
# Orçamento do Estado
# =======================================================================
elif pagina == "Orçamento do Estado":
    st.title(f"Orçamento do Estado — Legislatura {leg}")
    st.caption("Estrutura hierárquica do articulado do OE em discussão. Hierarquia via ID_Pai.")

    tipos_all = q("SELECT DISTINCT Tipo t FROM orcamento_do_estado WHERE _legislatura=? AND Tipo IS NOT NULL ORDER BY 1", (leg,))["t"].tolist()
    estados_all = q("SELECT DISTINCT Estado e FROM orcamento_do_estado WHERE _legislatura=? AND Estado IS NOT NULL ORDER BY 1", (leg,))["e"].tolist()

    f1, f2, f3 = st.columns([2, 2, 4])
    tipo_sel = f1.multiselect("Tipo", tipos_all, placeholder="Todos")
    estado_sel = f2.multiselect("Estado", estados_all, placeholder="Todos")
    texto = f3.text_input("Pesquisa no título ou texto", placeholder="palavra-chave…")

    where = ["_legislatura = ?"]
    params: list = [leg]
    if tipo_sel:
        where.append("Tipo IN (" + ",".join(["?"] * len(tipo_sel)) + ")")
        params.extend(tipo_sel)
    if estado_sel:
        where.append("Estado IN (" + ",".join(["?"] * len(estado_sel)) + ")")
        params.extend(estado_sel)
    if texto:
        where.append("(Titulo ILIKE ? OR Texto ILIKE ?)")
        params.extend([f"%{texto}%", f"%{texto}%"])

    sql = f"""
    SELECT ID, ID_Pai, Tipo, Numero, Titulo, Estado, Texto
    FROM orcamento_do_estado
    WHERE {' AND '.join(where)}
    ORDER BY TRY_CAST(ID AS INTEGER)
    LIMIT 1000
    """
    df = q(sql, tuple(params))

    k1, k2, k3 = st.columns(3)
    k1.metric("Itens", f"{len(df):,}")
    k2.metric("Tipos", df["Tipo"].nunique() if not df.empty else 0)
    k3.metric("Estados", df["Estado"].nunique() if not df.empty else 0)

    st.dataframe(
        df, use_container_width=True, hide_index=True, height=480,
        column_config={
            "ID": st.column_config.TextColumn("ID"),
            "ID_Pai": st.column_config.TextColumn("ID pai"),
            "Tipo": st.column_config.TextColumn("Tipo"),
            "Numero": st.column_config.TextColumn("Nº"),
            "Titulo": st.column_config.TextColumn("Título", width="large"),
            "Estado": st.column_config.TextColumn("Estado"),
            "Texto": st.column_config.TextColumn("Texto", width="large"),
        },
    )
    download_button(df, f"orcamento_do_estado_leg{leg}", key="dl_oe")


# =======================================================================
# Perfil de deputado
# =======================================================================
elif pagina == "Perfil de deputado":
    st.title(f"Perfil de deputado — Legislatura {leg}")

    deps = q(
        "SELECT DepCadId, DepNomeParlamentar, DepNomeCompleto, DepCPDes FROM deputados WHERE _legislatura=? ORDER BY DepNomeParlamentar",
        (leg,),
    )
    deps["label"] = deps.apply(
        lambda r: f"{s(r['DepNomeParlamentar'], s(r['DepNomeCompleto'], '(s/n)'))} — {s(r['DepCPDes'])}",
        axis=1,
    )
    sel_label = st.selectbox("Deputado", deps["label"].tolist())
    if sel_label:
        cad_id = deps.loc[deps["label"] == sel_label, "DepCadId"].iloc[0]

        bio = q("SELECT * FROM deputados WHERE _legislatura=? AND DepCadId=?", (leg, float(cad_id)))
        if not bio.empty:
            r = bio.iloc[0]
            st.markdown(f"## {s(r['DepNomeParlamentar'], s(r['DepNomeCompleto'], '(sem nome)'))}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Círculo", s(r["DepCPDes"]))
            c2.metric("Cargo", s(r["DepCargo"]))
            c3.metric("ID deputado", str(int(cad_id)) if pd.notna(cad_id) else "—")

            n_ini = int(q(
                "SELECT COUNT(DISTINCT a.IniId) n FROM iniciativa_autores_deputados a JOIN iniciativas i USING(IniId) WHERE i._legislatura=? AND a.idCadastro=?",
                (leg, str(int(cad_id))),
            )["n"][0])
            n_int = int(q(
                "SELECT COUNT(*) n FROM intervencoes WHERE _legislatura=? AND dep_idCadastro=?",
                (leg, str(int(cad_id))),
            )["n"][0])
            c4.metric("Iniciativas / Intervenções", f"{n_ini} / {n_int}")

        tab1, tab2, tab3 = st.tabs(["Iniciativas", "Intervenções", "Atividade"])

        with tab1:
            ini = q(
                """
                SELECT i.IniNr AS nr, i.IniDescTipo AS tipo, i.IniTitulo AS titulo,
                       i.data_entrada AS data_ini, i.IniLinkTexto AS texto
                FROM iniciativas i
                JOIN iniciativa_autores_deputados a USING(IniId)
                WHERE i._legislatura=? AND a.idCadastro=?
                ORDER BY i.data_entrada DESC NULLS LAST
                """,
                (leg, str(int(cad_id))),
            )
            st.dataframe(
                ini, use_container_width=True, hide_index=True, height=440,
                column_config={
                    "nr": st.column_config.TextColumn("Nº"),
                    "tipo": st.column_config.TextColumn("Tipo"),
                    "titulo": st.column_config.TextColumn("Título", width="large"),
                    "data_ini": st.column_config.DateColumn("Data", format="YYYY-MM-DD"),
                    "texto": st.column_config.LinkColumn("Texto", display_text="abrir"),
                },
            )
            download_button(ini, f"deputado_{int(cad_id)}_iniciativas_leg{leg}", key="dl_prof_ini")

        with tab2:
            inte = q(
                """
                SELECT DataReuniaoPlenaria AS data_reu, TipoIntervencao AS tipo,
                       Sumario AS sumario, pub_URLDiario AS dar, av_url AS video
                FROM intervencoes
                WHERE _legislatura=? AND dep_idCadastro=?
                ORDER BY DataReuniaoPlenaria DESC NULLS LAST
                """,
                (leg, str(int(cad_id))),
            )
            st.dataframe(
                inte, use_container_width=True, hide_index=True, height=440,
                column_config={
                    "data_reu": st.column_config.DateColumn("Data", format="YYYY-MM-DD"),
                    "tipo": st.column_config.TextColumn("Tipo"),
                    "sumario": st.column_config.TextColumn("Sumário", width="large"),
                    "dar": st.column_config.LinkColumn("DAR", display_text="ler"),
                    "video": st.column_config.LinkColumn("Vídeo", display_text="ver"),
                },
            )
            download_button(inte, f"deputado_{int(cad_id)}_intervencoes_leg{leg}", key="dl_prof_inte")

        with tab3:
            cnt = q(
                "SELECT * FROM deputado_atividade_contadores WHERE _legislatura=? AND DepCadId=?",
                (leg, float(cad_id)),
            )
            if not cnt.empty:
                cnt_cols = [c for c in cnt.columns if c.startswith("n_")]
                melted = cnt[cnt_cols].T.reset_index()
                melted.columns = ["categoria", "n"]
                melted["categoria"] = melted["categoria"].str.removeprefix("n_")
                melted = melted.sort_values("n", ascending=False)
                fig = px.bar(melted, x="categoria", y="n", labels={"categoria": "Categoria"})
                fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10), plot_bgcolor="white",
                                  xaxis_title=None, yaxis_title=None)
                fig.update_traces(marker_color="#2b6cb0")
                st.plotly_chart(fig, use_container_width=True)


# =======================================================================
# Descarregar dados
# =======================================================================
elif pagina == "Descarregar dados":
    st.title("Descarregar dados")
    st.caption(
        "Acesso directo às 142 tabelas da base de dados. "
        "Cada tabela pode ser filtrada por legislatura e descarregada em CSV (UTF-8 com BOM, compatível com Excel)."
    )

    @st.cache_data(ttl=3600, show_spinner=False)
    def _tables_list() -> pd.DataFrame:
        return q(
            """
            SELECT t.table_name
            FROM information_schema.tables t
            WHERE t.table_schema = 'main'
            ORDER BY t.table_name
            """
        )

    tabelas = _tables_list()
    st.markdown(f"### {len(tabelas)} tabelas disponíveis")

    filtro_nome = st.text_input(
        "Filtrar tabelas por nome",
        placeholder="ex.: iniciativa, votacao, deputado…",
        key="dl_filter",
    )

    tab_view = tabelas.copy()
    if filtro_nome:
        tab_view = tab_view[tab_view["table_name"].str.contains(filtro_nome, case=False, na=False)]

    sel_tabela = st.selectbox("Tabela", tab_view["table_name"].tolist(), label_visibility="collapsed")

    if sel_tabela:
        cols_info = q(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
            (sel_tabela,),
        )
        tem_legislatura = "_legislatura" in cols_info["column_name"].values

        c1, c2 = st.columns([2, 3])
        legs_sel: list[str] = []
        if tem_legislatura:
            legs_disp = q(f'SELECT DISTINCT _legislatura l FROM "{sel_tabela}" ORDER BY l')["l"].astype(str).tolist()
            legs_sel = c1.multiselect("Legislaturas", legs_disp, default=legs_disp, key="dl_legs")

        where_sql = ""
        params_sql: list = []
        if legs_sel and tem_legislatura:
            where_sql = " WHERE _legislatura IN (" + ",".join(["?"] * len(legs_sel)) + ")"
            params_sql.extend(legs_sel)

        total = q(f'SELECT COUNT(*) n FROM "{sel_tabela}"{where_sql}', tuple(params_sql))["n"][0]
        c2.metric("Linhas", f"{int(total):,}")

        st.markdown("### Pré-visualização (primeiras 100 linhas)")
        preview = q(f'SELECT * FROM "{sel_tabela}"{where_sql} LIMIT 100', tuple(params_sql))
        st.dataframe(preview, use_container_width=True, hide_index=True, height=350)

        st.markdown("### Descarregar")
        full = q(f'SELECT * FROM "{sel_tabela}"{where_sql}', tuple(params_sql))
        suffix = "_" + "_".join(legs_sel) if legs_sel and tem_legislatura and len(legs_sel) < 17 else ""
        download_button(full, f"{sel_tabela}{suffix}", key="dl_full")
        st.caption(
            "O ficheiro é gerado em memória no browser. "
            "Para tabelas muito grandes (>500 000 linhas) o navegador pode demorar alguns segundos."
        )
