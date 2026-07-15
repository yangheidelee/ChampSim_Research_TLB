#!/usr/bin/env python3

import argparse
import re
from pathlib import Path


def normalized(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\(Simulation time: [^)]+\)", "(Simulation time: IGNORED)", text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare ChampSim logs while ignoring host simulation time.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("instrumented", type=Path)
    args = parser.parse_args()

    lhs = normalized(args.baseline)
    rhs = normalized(args.instrumented)
    if lhs != rhs:
        raise SystemExit("[ERROR] Baseline and logger-enabled ChampSim outputs differ after timing normalization.")
    print("[PASS] Baseline and logger-enabled architectural/statistical outputs are identical.")


if __name__ == "__main__":
    main()
