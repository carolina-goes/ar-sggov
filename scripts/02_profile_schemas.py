"""
Fase 2 — Profiling de schemas.

Le cada JSON em data/raw/, percorre recursivamente a arvore, e produz:
  - data/schemas/{legislatura}_{categoria}.json : schema inferido + estatisticas
  - data/schemas/_summary.md : relatorio humano-legivel

Objectivo: perceber a estrutura (profundidade, campos, tipos, variacoes)
ANTES de escrever os normalizadores.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "schemas"


def walk(node, path="$", stats=None, depth=0):
    if stats is None:
        stats = defaultdict(lambda: {"types": defaultdict(int), "count": 0, "max_depth": 0, "samples": []})
    s = stats[path]
    s["count"] += 1
    s["max_depth"] = max(s["max_depth"], depth)
    t = type(node).__name__
    s["types"][t] += 1

    if isinstance(node, dict):
        for k, v in node.items():
            walk(v, f"{path}.{k}", stats, depth + 1)
    elif isinstance(node, list):
        s["types"]["list_len_" + str(min(len(node), 10))] += 1
        for item in node[:50]:  # amostra
            walk(item, f"{path}[]", stats, depth + 1)
    else:
        if len(s["samples"]) < 3 and node is not None:
            val = str(node)[:80]
            if val not in s["samples"]:
                s["samples"].append(val)
    return stats


def profile_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    stats = walk(data)
    # converter defaultdicts
    result = {}
    for k, v in stats.items():
        result[k] = {
            "count": v["count"],
            "max_depth": v["max_depth"],
            "types": dict(v["types"]),
            "samples": v["samples"],
        }
    return {
        "root_type": type(data).__name__,
        "root_len": len(data) if isinstance(data, (list, dict)) else None,
        "num_paths": len(result),
        "max_depth": max((v["max_depth"] for v in result.values()), default=0),
        "paths": result,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(RAW.rglob("*.json"))
    if not files:
        print(f"Nenhum JSON em {RAW}. Corra 01_download.py primeiro.")
        return

    summary_lines = ["# Profiling de schemas\n"]
    for f in files:
        rel = f.relative_to(RAW)
        print(f"Profiling {rel}...")
        prof = profile_file(f)
        out_name = rel.as_posix().replace("/", "_").replace(".json", "") + ".json"
        (OUT / out_name).write_text(json.dumps(prof, indent=2, ensure_ascii=False), encoding="utf-8")

        summary_lines.append(f"## {rel}")
        summary_lines.append(f"- Tipo raiz: `{prof['root_type']}` (len={prof['root_len']})")
        summary_lines.append(f"- Numero de paths distintos: {prof['num_paths']}")
        summary_lines.append(f"- Profundidade maxima: {prof['max_depth']}")
        # top-level keys
        top_keys = [p for p in prof["paths"] if p.count(".") == 1 and "[]" not in p]
        if top_keys:
            summary_lines.append(f"- Campos top-level: {', '.join(k.split('.')[-1] for k in top_keys[:20])}")
        summary_lines.append("")

    (OUT / "_summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"\nRelatorios em {OUT}")
    print(f"Resumo: {OUT / '_summary.md'}")


if __name__ == "__main__":
    main()
