"""Fase 3 — Normalizacao de `agenda_parlamentar` (eventos institucionais da AR)."""
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


def _parse_dt(date_str, time_str):
    if not date_str:
        return None
    s = date_str + (f" {time_str}" if time_str else "")
    return pd.to_datetime(s, dayfirst=True, errors="coerce")


def build_fact(e: dict) -> dict:
    return {
        "Id": e.get("Id"),
        "LegDes": e.get("LegDes"),
        "Section": e.get("Section"),
        "SectionId": e.get("SectionId"),
        "Theme": e.get("Theme"),
        "ThemeId": e.get("ThemeId"),
        "Title": e.get("Title"),
        "Subtitle": e.get("Subtitle"),
        "Local": e.get("Local"),
        "Link": e.get("Link"),
        "OrderValue": e.get("OrderValue"),
        "ParlamentGroup": e.get("ParlamentGroup"),
        "OrgDes": e.get("OrgDes"),
        "ReuNumero": e.get("ReuNumero"),
        "SelNumero": e.get("SelNumero"),
        "AllDayEvent": e.get("AllDayEvent"),
        "PostPlenary": e.get("PostPlenary"),
        "EventStartDate": e.get("EventStartDate"),
        "EventStartTime": e.get("EventStartTime"),
        "EventEndDate": e.get("EventEndDate"),
        "EventEndTime": e.get("EventEndTime"),
        "data_inicio": _parse_dt(e.get("EventStartDate"), e.get("EventStartTime")),
        "data_fim": _parse_dt(e.get("EventEndDate"), e.get("EventEndTime")),
        "InternetText": e.get("InternetText"),
        "AnexosPlenario_json": None if e.get("AnexosPlenario") is None else json.dumps(e.get("AnexosPlenario"), ensure_ascii=False),
        "AnexosComissaoPermanente_json": None if e.get("AnexosComissaoPermanente") is None else json.dumps(e.get("AnexosComissaoPermanente"), ensure_ascii=False),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislaturas", default="")
    args = ap.parse_args()
    legs = [s.strip() for s in args.legislaturas.split(",") if s.strip()] or sorted(p.name for p in RAW.iterdir() if p.is_dir())
    for leg in legs:
        p = RAW / leg / "agenda_parlamentar.json"
        if not p.exists():
            continue
        print(f"  NORM {p.relative_to(ROOT)}")
        data = json.loads(p.read_text(encoding="utf-8"))
        df = pd.DataFrame([build_fact(e) for e in data if isinstance(e, dict)])
        finalize_table(df, "agenda_parlamentar", leg, p, SCRIPT_NAME)


if __name__ == "__main__":
    main()
