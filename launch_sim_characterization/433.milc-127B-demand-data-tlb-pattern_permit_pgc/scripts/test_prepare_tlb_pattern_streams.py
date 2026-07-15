#!/usr/bin/env python3

import csv
import tempfile
from pathlib import Path

from prepare_tlb_pattern_streams import (COMPACT_DROP_FIELDS, derive_streams, write_compact_copy,
                                         write_global_seq_ordered_copy)


FIELDS = [
    "cpu", "global_seq", "load_tlb_seq", "vberti_prefetch_seq", "instr_id", "operand_index", "pc",
    "prefetch_issue_cycle", "prefetch_trigger_instr_id", "prefetch_trigger_pc", "prefetch_trigger_va",
    "dtlb_lookup_cycle", "translation_complete_cycle", "va", "vpn",
    "virtual_region_2m", "page_offset_in_region", "l1dtlb_result", "l1dtlb_merged", "stlb_accessed", "stlb_result", "stlb_merged",
    "pa", "ppn", "physical_region_2m", "page_offset_in_physical_region", "physical_address_valid", "completion_state",
]


def row(seq: int, accessed: int, result: str, merged: int = 0) -> dict[str, object]:
    return {
        "cpu": 0,
        "global_seq": seq,
        "load_tlb_seq": seq,
        "vberti_prefetch_seq": 1000 + seq,
        "instr_id": 100 + seq,
        "operand_index": 0,
        "pc": 0x1000,
        "prefetch_issue_cycle": 5 + seq,
        "prefetch_trigger_instr_id": 50 + seq,
        "prefetch_trigger_pc": 0x2000,
        "prefetch_trigger_va": 0x3000,
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
        ordered = root / "source_global_seq_ordered.csv"
        ordered_compact = root / "source_global_seq_ordered_compact.csv"
        copied_compact = root / "source_copied_compact.csv"
        access = root / "access.csv"
        access_compact = root / "access_compact.csv"
        miss = root / "miss.csv"
        miss_compact = root / "miss_compact.csv"
        with source.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows([row(2, 1, "MISS", 1), row(0, 0, "NOT_ACCESSED"), row(3, 1, "MISS"), row(1, 1, "HIT")])

        assert write_global_seq_ordered_copy(source, ordered, chunk_size=2, compact_output_csv=ordered_compact) == 4
        source_rows = read_rows(source)
        ordered_rows = read_rows(ordered)
        assert [item["global_seq"] for item in ordered_rows] == ["0", "1", "2", "3"]
        assert {tuple(item.items()) for item in ordered_rows} == {tuple(item.items()) for item in source_rows}
        assert write_compact_copy(ordered, copied_compact) == 4
        assert read_rows(ordered_compact) == read_rows(copied_compact)
        assert not (COMPACT_DROP_FIELDS & set(read_rows(ordered_compact)[0]))
        counts = derive_streams(ordered, access, miss, access_compact, miss_compact)
        access_rows = read_rows(access)
        miss_rows = read_rows(miss)
        access_compact_rows = read_rows(access_compact)
        miss_compact_rows = read_rows(miss_compact)
        assert counts == {"dtlb_access": 4, "stlb_access": 3, "stlb_miss": 2, "stlb_merge": 1}
        assert [item["load_tlb_seq"] for item in access_rows] == ["1", "2", "3"]
        assert [item["stlb_access_seq"] for item in access_rows] == ["0", "1", "2"]
        assert [item["stlb_miss_seq"] for item in miss_rows] == ["0", "1"]
        assert all(item["stlb_result"] == "MISS" for item in miss_rows)
        assert len(access_compact_rows) == len(access_rows)
        assert len(miss_compact_rows) == len(miss_rows)
        assert not (COMPACT_DROP_FIELDS & set(access_compact_rows[0]))
        assert not (COMPACT_DROP_FIELDS & set(miss_compact_rows[0]))
        assert access_compact_rows[0]["vpn"] == access_rows[0]["vpn"]

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
