"""
Fase 1 — Ingestao dos dados da Assembleia da Republica.

Le o catalogo ar_sggov_full.json, filtra por legislatura + categorias,
descarrega cada JSON para data/raw/{legislatura}/{categoria}.json e
grava um manifesto com timestamp, tamanho e hash.

Uso:
    python 01_download.py                      # default: legislatura 17, 3 categorias
    python 01_download.py --legislaturas 16,17
    python 01_download.py --all                # tudo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog" / "ar_sggov_full.json"
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "data" / "manifest.json"

DEFAULT_LEGISLATURAS = ["17"]
DEFAULT_CATEGORIAS = [
    "iniciativas",
    "atividade_dos_deputados",
    "intervencoes",
]


def build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "ar-sggov-ingestor/0.1 (local research)"})
    return s


def parse_filename(fn: str) -> tuple[str, str]:
    """'16_iniciativas' -> ('16', 'iniciativas')"""
    parts = fn.split("_", 1)
    if len(parts) != 2:
        return fn, ""
    return parts[0], parts[1]


def load_catalog() -> list[dict]:
    with CATALOG.open() as f:
        data = json.load(f)
    rows = []
    for r in data["rows"]:
        leg, cat = parse_filename(r["filename"])
        rows.append(
            {
                "legislatura": leg,
                "categoria": cat,
                "url": r["json"],
                "filename": r["filename"],
            }
        )
    return rows


def download_one(session: requests.Session, entry: dict, dest: Path) -> dict:
    t0 = time.time()
    r = session.get(entry["url"], timeout=120)
    r.raise_for_status()
    content = r.content
    # validar JSON
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Resposta nao e JSON valido: {e}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)

    return {
        "filename": entry["filename"],
        "legislatura": entry["legislatura"],
        "categoria": entry["categoria"],
        "path": str(dest.relative_to(ROOT)),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "elapsed_s": round(time.time() - t0, 2),
        "top_level_type": type(parsed).__name__,
        "top_level_len": len(parsed) if isinstance(parsed, (list, dict)) else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default=",".join(DEFAULT_LEGISLATURAS))
    ap.add_argument("--categorias", default=",".join(DEFAULT_CATEGORIAS))
    ap.add_argument("--all", action="store_true", help="descarrega tudo")
    ap.add_argument("--force", action="store_true", help="re-descarrega mesmo que o ficheiro local exista")
    args = ap.parse_args()
    args.skip_existing = not args.force

    catalog = load_catalog()
    if args.all:
        todo = catalog
    else:
        legs = set(args.legislaturas.split(","))
        cats = set(args.categorias.split(","))
        todo = [e for e in catalog if e["legislatura"] in legs and e["categoria"] in cats]

    print(f"Catalogo total: {len(catalog)} | A descarregar: {len(todo)}")
    session = build_session()

    manifest = []
    failures = []
    for i, entry in enumerate(todo, 1):
        dest = RAW / entry["legislatura"] / f"{entry['categoria']}.json"
        if args.skip_existing and dest.exists():
            print(f"  [{i}/{len(todo)}] SKIP (existe) {entry['filename']}")
            continue
        try:
            print(f"  [{i}/{len(todo)}] GET  {entry['filename']} ...", end=" ", flush=True)
            rec = download_one(session, entry, dest)
            manifest.append(rec)
            print(f"OK ({rec['bytes']:,} bytes, {rec['elapsed_s']}s)")
        except Exception as e:
            print(f"FAIL: {e}")
            failures.append({"entry": entry, "error": str(e)})
        time.sleep(0.3)  # rate-limit gentil

    # merge com manifesto existente
    existing = []
    if MANIFEST.exists():
        existing = json.loads(MANIFEST.read_text())
    by_file = {r["filename"]: r for r in existing}
    for r in manifest:
        by_file[r["filename"]] = r
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(list(by_file.values()), indent=2, ensure_ascii=False))

    print(f"\nDescarregados: {len(manifest)} | Falhas: {len(failures)}")
    if failures:
        print("Falhas:")
        for f in failures:
            print(f"  - {f['entry']['filename']}: {f['error']}")


if __name__ == "__main__":
    main()
