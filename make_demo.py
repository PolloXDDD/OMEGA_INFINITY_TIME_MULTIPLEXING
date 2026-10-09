#!/usr/bin/env python3
"""Generate reproducible CNFs that use every declared variable, with a model."""
import argparse
import json
from pathlib import Path
import random

from omega_core import write_assignment


def generate(out_dir, num_vars=300000, kind="3sat", seed=42):
    if num_vars < 1:
        raise ValueError("Se necesita al menos una variable.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    if kind == "chain":
        assignment = bytearray(num_vars + 1)
        assignment[num_vars] = 1
        count = 1
    elif kind == "3sat":
        assignment = bytearray([0] + [rng.randrange(2) for _ in range(num_vars)])
        count = (num_vars + 2) // 3
    else:
        raise ValueError("kind debe ser chain o 3sat.")
    path = out / "demo.cnf"
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("c Ejemplo funcional con modelo conocido; no es un benchmark de dificultad SAT.\n")
        stream.write(f"p cnf {num_vars} {count}\n")
        if kind == "chain":
            for start in range(1, num_vars + 1, 100):
                stream.write(" ".join(str(var) for var in range(start, min(start + 100, num_vars + 1))) + "\n")
            stream.write("0\n")
        else:
            for start in range(1, num_vars + 1, 3):
                variables = range(start, min(start + 3, num_vars + 1))
                literals = []
                for index, var in enumerate(variables):
                    sign = assignment[var] if index == 0 else rng.randrange(2)
                    literals.append(var if sign else -var)
                stream.write(" ".join(map(str, literals)) + " 0\n")
    write_assignment(out / "assignment.txt", assignment)
    manifest = {"variables": num_vars, "clauses": count, "kind": kind, "seed": seed,
                "purpose": "functional-example-with-known-satisfying-assignment"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("demo_300k"))
    parser.add_argument("--vars", type=int, default=300000)
    parser.add_argument("--kind", choices=("3sat", "chain"), default="3sat")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(generate(args.out, args.vars, args.kind, args.seed), indent=2))
