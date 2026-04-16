# AR-SGGOV — Plataforma de consulta da Assembleia da República

**App online**: <https://ar-sg-gov-dssd-upe-v01.streamlit.app>

Plataforma de consulta aberta sobre os dados oficiais da **Assembleia da República Portuguesa** (`app.parlamento.pt`), cobrindo **17 legislaturas** (I a XVII) e 16 categorias temáticas.

Pipeline: Python puro → Parquet particionado por legislatura → DuckDB → dashboard Streamlit.

## Arquitectura

```
ar-sggov/
├── catalog/                      # catálogo oficial dos 208 endpoints
├── scripts/                      # pipeline (download, profiling, normalização, load, calendário)
├── data/
│   ├── raw/{legislatura}/…       # JSONs originais (gitignored)
│   ├── schemas/                  # profiling dos schemas (gitignored)
│   └── normalized/
│       ├── <tabela>/_legislatura=<NN>/part.parquet   # Hive-partitioned
│       ├── dim_calendario/part.parquet               # dimensão de datas
│       └── _manifest.json                            # log de linhagem
├── db/ar.duckdb                  # BD analítica (gitignored, reconstruível)
├── app/app.py                    # dashboard Streamlit
└── .github/workflows/            # cron diário para refrescar legislatura XVII
```

## Correr localmente

```bash
pip install -r requirements.txt
python scripts/01_download.py --legislaturas 17     # ingestão
python scripts/02_profile_schemas.py                # profiling
python scripts/03_normalize_*.py --legislaturas 17  # normalização
python scripts/05_build_dim_calendario.py           # dimensão de calendário
python scripts/04_load_to_db.py                     # load DuckDB
python -m streamlit run app/app.py                  # app em http://localhost:8501
```

## Actualização automática

O workflow [`.github/workflows/refresh_xvii.yml`](.github/workflows/refresh_xvii.yml) corre diariamente às **05:00 UTC** e refresca os dados da legislatura XVII (a que está activa), comitando os parquet actualizados.

Accionamento manual disponível em *Actions → Refresh legislatura XVII → Run workflow*.

## Documentação

- [`SKILL.md`](SKILL.md) — arquitectura, princípios, convenções, modelo dimensional.
- [`WORKLOG.md`](WORKLOG.md) — diário de bordo do projeto.

## Referências

- Catálogo: [`catalog/ar_sggov_full.json`](catalog/ar_sggov_full.json)
- Fonte de dados: <https://app.parlamento.pt>
