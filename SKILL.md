---
name: ar-sggov-platform
description: Plataforma de consulta dos dados da Assembleia da Republica. Use sempre que o utilizador falar em continuar este projeto, descarregar dados da AR, normalizar JSONs do parlamento.pt, construir o dashboard ou modificar o pipeline (ingestao -> normalizacao -> DuckDB -> Streamlit/static). Tambem cobre publicacao via GitHub Actions no estilo do projeto "expert-groups-dashboard".
---

# AR-SGGOV — Plataforma de consulta da Assembleia da Republica

## Contexto e objectivo

A utilizadora (Carolina) tem um catalogo oficial com **208 endpoints JSON** da Assembleia da Republica Portuguesa (`app.parlamento.pt`), cobrindo **17 legislaturas** e 16 categorias tematicas. O objectivo e construir uma plataforma **estatica, publica, auto-actualizavel** que permita consultar estes dados — semelhante ao repo `carolina-goes/expert-groups-dashboard` (GitHub Actions + dashboard estatico).

**Tentativas anteriores abandonadas**: Microsoft Fabric (Lakehouse + medallion). Razao: schemas demasiado aninhados e variaveis entre legislaturas tornaram o trabalho em Spark/notebooks demasiado lento. Abordagem actual e Python puro, local-first, com publicacao via GitHub Pages + Actions.

## Arquitectura (medallion simplificado em Python)

```
ar-sggov/
|- catalog/
|   `- ar_sggov_full.json         # catalogo oficial dos 208 endpoints
|- data/
|   |- raw/{legislatura}/{categoria}.json   # JSONs originais
|   |- schemas/                             # profiling dos schemas
|   |- normalized/*.parquet                 # tabelas achatadas
|   `- manifest.json                        # log de ingestao (hash, timestamp, bytes)
|- db/ar.duckdb                             # BD de consulta
|- scripts/
|   |- 01_download.py             # ingestao com retry/skip-existing/manifesto
|   |- 02_profile_schemas.py      # profiling recursivo de paths e tipos
|   |- 03_normalize_{categoria}.py  # um por categoria (a escrever)
|   `- 04_load_to_db.py           # normalized -> DuckDB
|- app/                            # Streamlit OU HTML/JS estatico
`- .github/workflows/update.yml    # agendamento (a criar)
```

## Categorias do catalogo (16)

`atividade_dos_deputados`, `atividades`, `iniciativas`, `intervencoes`, `diplomas_aprovados`, `perguntas_e_requerimentos`, `peticoes`, `composicao_de_orgaos`, `informacao_base`, `grupos_parlamentares_de_amizade`, `cooperacao_parlamentar`, `delegacoes_eventuais`, `delegacoes_permanentes`, `reunioes_e_visitas`, `orcamento_do_estado`, `agenda_parlamentar`.

Legislaturas cobertas: 01 a 17 (I a XVII). As recentes (XIII-XVII) sao as mais completas; as antigas podem ter poucas categorias.

## Decisoes ja tomadas

1. **Nao usar Fabric.** Python local + GitHub Actions.
2. **Comecar pequeno**: legislatura XVI + 3 categorias (`iniciativas`, `atividade_dos_deputados`, `intervencoes`). So depois alargar.
3. **DuckDB** como motor de query (zero-config, rapido em analytics, le parquet directamente).
4. **Streamlit** como UI inicial. Alternativa futura: frontend estatico (HTML/JS) consumindo JSONs/parquet, no estilo do `expert-groups-dashboard`.
5. **Nao normalizar a cegas**: correr primeiro `02_profile_schemas.py` para perceber o aninhamento antes de escrever cada normalizador.
6. **User-Agent** nos requests: `ar-sggov-ingestor/0.1 (local research)`. Rate-limit de 0.3s entre requests.

## Estrategia para schemas aninhados

Os JSON da AR tem aninhamento profundo e **variam entre legislaturas** (campos que as vezes sao objecto, as vezes array). A abordagem:

1. Profiling primeiro (`02_profile_schemas.py`) — mapeia todos os paths, tipos e profundidade.
2. Um normalizador **dedicado por categoria** (nao tentar generico). Cada normalizador:
   - Le o JSON raw
   - Identifica a "entidade principal" (ex.: iniciativa, deputado, intervencao)
   - Produz **tabela fact** (uma linha por entidade) + **tabelas satelite** (N:N — ex.: iniciativa_autores, iniciativa_votacoes)
   - Campos com estrutura irregular ficam em colunas JSON (DuckDB le JSON nativo)
3. Chaves estaveis para joins: `bid` do deputado, `id` da iniciativa, `legislatura`, `sessao`.

## Proximos passos (por ordem)

1. **[utilizadora]** Correr `scripts/01_download.py` localmente — o sandbox onde o Claude Cowork corre nao tem acesso a `app.parlamento.pt`, portanto a ingestao e obrigatoriamente local.
2. **[utilizadora]** Correr `scripts/02_profile_schemas.py` e partilhar `data/schemas/_summary.md`.
3. **[Claude]** Escrever `03_normalize_iniciativas.py` (e os outros) com base nos schemas reais.
4. **[Claude]** Escrever `04_load_to_db.py` (parquet -> DuckDB com indices nos campos chave).
5. **[Claude]** Construir `app/app.py` em Streamlit: filtros por legislatura/GP/deputado, tabelas, graficos com Plotly, pesquisa full-text nas intervencoes.
6. **[Claude]** Criar `.github/workflows/update.yml` (cron semanal) que re-corre a ingestao e publica o dashboard. Seguir o padrao do repo `expert-groups-dashboard`.
7. **[Claude + utilizadora]** Expandir para todas as legislaturas e categorias relevantes.

## Como continuar este projeto noutra sessao (ex.: VS Code + Claude Code)

Quando uma instancia do Claude abrir este repo:

1. Ler este `SKILL.md` primeiro.
2. Verificar o estado:
   - `ls data/raw/` — o que ja foi descarregado?
   - `cat data/manifest.json` — quando foi a ultima ingestao?
   - `ls scripts/` — que fases estao implementadas?
3. Se `data/raw/` estiver vazio, pedir a utilizadora para correr `python scripts/01_download.py`.
4. Se ha raws mas nao ha schemas, correr `python scripts/02_profile_schemas.py`.
5. Se ha schemas mas faltam normalizadores, escrever o proximo normalizador com base no schema correspondente.
6. Nunca tentar descarregar do `app.parlamento.pt` a partir do Cowork (403 no proxy) — correr sempre localmente.

## Convencao de particionamento e linhagem (obrigatorio)

Todos os dados normalizados sao escritos com particionamento Hive e colunas de linhagem:

**Estrutura fisica**:

```
data/normalized/
  <tabela>/_legislatura=<NN>/part.parquet
```

- Uma pasta por tabela; uma sub-pasta por legislatura. Re-ingerir uma legislatura substitui apenas a sua particao (idempotencia).
- O prefixo `_` em `_legislatura` evita colisao case-insensitive com colunas de origem (ex.: `Legislatura` em intervencoes).

**Colunas tecnicas em cada linha** (prefixo `_`):

- `_source_file` — caminho relativo do JSON raw
- `_source_sha256` — hash do raw (lido de `data/manifest.json`)
- `_normalizer` — nome do script que produziu a linha
- `_normalized_at` — timestamp UTC ISO 8601

**Manifesto de normalizacao**: `data/normalized/_manifest.json` contem uma entrada por (tabela, legislatura) com `path`, `rows`, `columns`, `source_file`, `source_sha256`, `normalizer`, `generated_at`. Actualizado a cada execucao de normalizador.

**Helpers**: todos os normalizadores devem usar `scripts/_lib.py::finalize_table(df, table_name, legislatura, source_path, script_name)` que aplica as tres regras acima de uma so vez.

**Leitura**: DuckDB reconhece Hive partitioning automaticamente:

```python
SELECT * FROM read_parquet('data/normalized/iniciativas/**/*.parquet', hive_partitioning=1)
```

## Regra obrigatoria de registo (WORKLOG.md)

Qualquer sessao que trabalhe neste projeto DEVE manter `WORKLOG.md` (na raiz de `ar-sggov/`) actualizado. Esta regra nao e opcional.

1. **No inicio da sessao**: ler `WORKLOG.md` logo a seguir ao `SKILL.md` e verificar se o estado descrito bate certo com o estado real dos ficheiros (`data/raw/`, `data/schemas/`, `data/normalized/`, `db/`, `manifest.json`). Se divergir, corrigir o worklog antes de avancar com qualquer outro trabalho.
2. **Durante a sessao**: registar decisoes relevantes e problemas encontrados a medida que ocorrem, para nao depender de memoria no fim.
3. **No fim da sessao (obrigatorio)**: acrescentar uma nova entrada em "Registo cronologico" com data, objectivo, feito, como, decisoes, problemas e proximo passo. Actualizar tambem a seccao "Estado actual" e a checklist global.
4. **Interrupcoes**: se o trabalho for interrompido (erro, limite de contexto, pedido da utilizadora), registar na mesma o que foi feito ate ao momento e qual o proximo passo para retomar.

Nenhuma sessao pode terminar sem esta actualizacao. Um diff que toque no projeto sem tocar em `WORKLOG.md` deve ser considerado incompleto.

## Modelo dimensional: `dim_calendario`

Existe uma **dimensao de calendario** global, nao particionada por legislatura, em `data/normalized/dim_calendario/part.parquet` e como tabela `dim_calendario` na DuckDB. E gerada por `scripts/05_build_dim_calendario.py`.

**Colunas**: `data` (DATE, chave), `ano`, `trimestre`, `mes`, `mes_nome`, `semana_iso`, `ano_mes`, `ano_trimestre`, `dia`, `dia_ano`, `dia_semana_iso`, `dia_semana_nome`, `fim_de_semana` (bool), `_generated_at`.

**Uso**:

- Os bounds do widget de intervalo de datas na app derivam de `MIN(data)/MAX(data)` de `dim_calendario` — garantem consistencia entre paginas.
- Factuais devem juntar-se por `data` quando for preciso agregar por semana/mes/trimestre, em vez de recalcular atributos de calendario em cada query.
- Cobertura: desde a data minima observada nas factuais ate hoje+365 dias. Re-executar o script quando chegam novos periodos.

**Avisos sobre datas nos dados da AR**:

- Em `iniciativas`, `DataInicioleg`/`DataFimleg` referem-se a **legislatura** (nao a iniciativa). A data real de entrada vem do **primeiro evento** em `iniciativa_eventos` (menor `DataFase`). Esta calculada no normalizador e guardada como coluna `data_entrada` no fact `iniciativas`. Tambem existe `data_ultimo_evento` (maior `DataFase`) para filtros de actividade recente.
- Em `intervencoes`, `DataReuniaoPlenaria` e fiavel (data real da sessao).
- Em `perguntas_e_requerimentos`, `DataEnvio` e fiavel; `DtEntrada` tambem esta disponivel.
- Em `peticoes`, `PetDataEntrada` e fiavel.
- Em `diplomas_aprovados`, a data de publicacao vem da satelite `diploma_publicacao.pubdt`.

## Regra obrigatoria de ortografia (pt-PT)

Todas as **strings apresentadas ao utilizador** — titulos, etiquetas, captions, cabecalhos de coluna visiveis, mensagens — devem ser escritas em portugues de Portugal com acordo ortografico de 2009, **com os diacriticos corretos** (a, a, e, e, i, o, o, u, c).

Exemplos (usar a coluna da direita):

| Evitar | Usar |
|---|---|
| Intervencoes | Intervenções |
| Peticoes | Petições |
| Comissao / Comissoes | Comissão / Comissões |
| Situacao | Situação |
| Publicacao | Publicação |
| Sessao | Sessão |
| Navegacao | Navegação |
| Filtros combinaveis | Filtros combináveis |
| Sumarios / Sumario | Sumários / Sumário |
| Ligacoes | Ligações |
| Destinatarios | Destinatários |
| Numero | Número |
| Titulo | Título |
| Assinaturas | Assinaturas (ja correcto) |
| Orcamento | Orçamento |

**Excepcoes (mantem-se em ASCII)**:

- Identificadores de codigo: nomes de variaveis, funcoes, classes, modulos, nomes de ficheiros e caminhos.
- Nomes de colunas em SQL / DataFrames / parquet (ex.: `intervencoes`, `peticao_documentos`, `DepCargo`) — aqui usam-se os nomes oficiais da fonte ou identificadores ASCII para evitar problemas de quoting e codificacao em DuckDB/Windows.
- Apenas o **label apresentado** (via `column_config`, `st.metric`, `st.selectbox`, etc.) e que deve ter a grafia correcta.

Esta regra aplica-se tambem a documentacao nova escrita em .md. Ficheiros existentes podem ser corrigidos incrementalmente quando forem editados por outra razao.

## Ambientes: branches `main` (producao) e `dev` (desenvolvimento)

O repo em <https://github.com/carolina-goes/ar-sggov> usa duas branches de longa duracao, correspondentes a dois ambientes:

| Branch | Ambiente | App Streamlit | Alteracoes |
|---|---|---|---|
| `main` | **Producao** | <https://ar-sg-gov-dssd-upe-v01.streamlit.app> | Apenas via Pull Request (ou bot do cron) |
| `dev` | **Desenvolvimento** | app de preview (a criar: `ar-sg-gov-dssd-upe-dev.streamlit.app`) | Commits directos OK |

**Regras de ouro**:

1. **Nunca fazer `git push origin main` manualmente**. A branch `main` so recebe:
   - Commits automaticos do workflow `refresh_xvii.yml` (refresh diario de dados).
   - Merges via Pull Request a partir de `dev`.
2. **Trabalhar sempre em `dev`**. Para experiencias de maior risco, criar branches de feature a partir de `dev` (`git checkout -b feat/nova-pagina`), e depois fundir em `dev` via PR ou merge local.
3. **Puxar dados novos de prod**: quando o cron diario adiciona commits a `main`, fazer `git checkout dev && git merge main` em `dev` para actualizar a referencia a parquet.
4. **Promover dev a prod**: quando o trabalho em `dev` estiver pronto, abrir PR `dev -> main` no GitHub. O merge do PR dispara redeploy automatico da app de producao. Usar "Squash and merge" ou "Merge commit" conforme preferencia.

**Comandos comuns**:

```bash
# Trabalhar em dev
git checkout dev
git pull
# ...edicoes...
git add -A && git commit -m "..."
git push

# Sincronizar dados frescos de main para dev
git checkout dev
git pull
git merge origin/main
git push

# Promover dev a producao (via PR)
gh pr create --base main --head dev --title "Promocao dev -> main" --body "..."
# revisar no browser, merge
```

**Porque nao ha protecao tecnica em main?**

Se configurarmos "Require PR" em main, o cron diario (que usa o GITHUB_TOKEN) tambem e bloqueado. Para manter o cron simples, optamos por **convencao + disciplina** em vez de ruleset com bypass actors. Se no futuro for preciso reforcar, adicionar um ruleset com bypass para `github-actions[bot]`.

## Convencoes de codigo

- Python 3.11+. Type hints e `from __future__ import annotations`.
- Dependencias: `requests`, `pandas`, `pyarrow`, `duckdb`, `streamlit`, `plotly`, `tenacity` (opcional — por enquanto uso `urllib3.Retry`).
- Caminhos sempre relativos ao `ROOT = Path(__file__).resolve().parent.parent`.
- Scripts sao idempotentes: `--skip-existing` por defeito na ingestao; normalizadores re-escrevem parquet.
- Logs no stdout com formato `[i/N] ACAO nome_ficheiro ... OK/FAIL`.
- Sem emojis no codigo.
- Preferencia por Portugues de Portugal nas mensagens, comentarios e UI.

## Referencias

- Catalogo: `catalog/ar_sggov_full.json` (fields: `json` URL, `filename` no formato `{NN}_{categoria}`)
- Projecto irmao: `carolina-goes/expert-groups-dashboard` — seguir o mesmo padrao de GitHub Actions + dashboard estatico.
- API base da AR: `https://app.parlamento.pt/webutils/docs/doc.txt?path=...&fich=...&Inline=true` (nao e REST, sao URLs pre-assinadas no catalogo).
