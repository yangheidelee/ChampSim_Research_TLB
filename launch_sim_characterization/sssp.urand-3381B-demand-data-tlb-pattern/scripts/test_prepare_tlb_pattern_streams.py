#!/usr/bin/env python3

import csv
import tempfile
from pathlib import Path

from prepare_tlb_pattern_streams import derive_streams


FIELDS = [
    "cpu", "load_tlb_seq", "instr_id", "operand_index", "pc", "dtlb_lookup_cycle", "translation_complete_cycle", "va", "vpn",
    "virtual_region_2m", "page_offset_in_region", "l1dtlb_result", "l1dtlb_merged", "stlb_accessed", "stlb_result", "stlb_merged",
    "pa", "ppn", "physical_region_2m", "page_offset_in_physical_region", "physical_address_valid", "completion_state",
]


def row(seq: int, accessed: int, result: str, merged: int = 0) -> dict[str, object]:
    return {
        "cpu": 0,
        "load_tlb_seq": seq,
        "instr_id": 100 + seq,
        "operand_index": 0,
        "pc": 0x1000,
        "dtlb_lookup_cycle": 10 + seq,
        "translation_complete_cycle": 20 + seq,
        "va": (10 + seq) * 4096,
        "vpn": 10 + seq,
        "virtual_region_2m": 0,
        "page_offset_in_region": 10 + seq,
        "pa": (100 + seq) * 4096,
        "ppn": 100 + seq,
        "physical_region_2m": 0,
        "page_offset_in_physical_region": 100 + seq,
        "physical_address_valid": 1,
        "l1dtlb_result": "MISS" if accessed else "HIT",
        "l1dtlb_merged": 0,
        "stlb_accessed": accessed,
        "stlb_result": result,
        "stlb_merged": merged,
        "completion_state": "COMPLETE",
    }


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.csv"
        access = root / "access.csv"
        miss = root / "miss.csv"
        with source.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows([row(0, 0, "NOT_ACCESSED"), row(1, 1, "HIT"), row(2, 1, "MISS", 1), row(3, 1, "MISS")])

        counts = derive_streams(source, access, miss)
        access_rows = read_rows(access)
        miss_rows = read_rows(miss)
        assert counts == {"dtlb_access": 4, "stlb_access": 3, "stlb_miss": 2, "stlb_merge": 1}
        assert [item["load_tlb_seq"] for item in access_rows] == ["1", "2", "3"]
        assert [item["stlb_access_seq"] for item in access_rows] == ["0", "1", "2"]
        assert [item["stlb_miss_seq"] for item in miss_rows] == ["0", "1"]
        assert all(item["stlb_result"] == "MISS" for item in miss_rows)

        legacy_source = root / "legacy_source.csv"
        legacy_access = root / "legacy_access.csv"
        legacy_miss = root / "legacy_miss.csv"
        legacy_fields = [field for field in FIELDS if field not in {
            "pa", "ppn", "physical_region_2m", "page_offset_in_physical_region", "physical_address_valid"
        }]
        with legacy_source.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=legacy_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows([row(0, 0, "NOT_ACCESSED"), row(1, 1, "HIT"), row(2, 1, "MISS")])
        legacy_counts = derive_streams(legacy_source, legacy_access, legacy_miss)
        legacy_access_rows = read_rows(legacy_access)
        assert legacy_counts["stlb_access"] == 2
        assert "ppn" not in legacy_access_rows[0]
    print("[PASS] Synthetic STLB access/miss stream derivation test passed.")


if __name__ == "__main__":
    main()
