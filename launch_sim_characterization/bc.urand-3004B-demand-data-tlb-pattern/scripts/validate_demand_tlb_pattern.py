#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


DTYPES = {
    "cpu": "uint32",
    "load_tlb_seq": "uint64",
    "instr_id": "uint64",
    "operand_index": "uint32",
    "pc": "uint64",
    "dtlb_lookup_cycle": "uint64",
    "translation_complete_cycle": "uint64",
    "va": "uint64",
    "vpn": "uint64",
    "virtual_region_2m": "uint64",
    "page_offset_in_region": "uint32",
    "pa": "uint64",
    "ppn": "uint64",
    "physical_region_2m": "uint64",
    "page_offset_in_physical_region": "uint32",
    "physical_address_valid": "uint8",
    "l1dtlb_result": "category",
    "l1dtlb_merged": "uint8",
    "stlb_accessed": "uint8",
    "stlb_result": "category",
    "stlb_merged": "uint8",
    "completion_state": "category",
}

PHYSICAL_FIELDS = {
    "pa",
    "ppn",
    "physical_region_2m",
    "page_offset_in_physical_region",
    "physical_address_valid",
}


def parse_logger_summary(path: Path) -> dict[int, dict[str, int]]:
    result: dict[int, dict[str, int]] = {}
    current_cpu: int | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        fields = raw_line.split()
        if not fields:
            continue
        if fields[0] == "core":
            current_cpu = int(fields[1])
            result[current_cpu] = {}
        elif current_cpu is not None and len(fields) == 2:
            result[current_cpu][fields[0]] = int(fields[1])
    return result


def validate(input_path: Path, metadata_path: Path, summary_path: Path | None) -> pd.DataFrame:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    page_size = int(metadata["page_size"])
    region_size = int(metadata["region_size"])
    if page_size <= 0 or region_size % page_size:
        raise AssertionError("Invalid page/region size in metadata")

    input_columns = set(pd.read_csv(input_path, nrows=0).columns)
    present_physical_fields = PHYSICAL_FIELDS & input_columns
    if present_physical_fields and present_physical_fields != PHYSICAL_FIELDS:
        missing = ", ".join(sorted(PHYSICAL_FIELDS - present_physical_fields))
        raise AssertionError(f"Partial physical-address schema; missing: {missing}")
    has_physical_fields = present_physical_fields == PHYSICAL_FIELDS
    input_dtypes = {name: dtype for name, dtype in DTYPES.items() if name in input_columns}
    frame = pd.read_csv(input_path, dtype=input_dtypes).sort_values(["cpu", "load_tlb_seq"], kind="stable")
    if frame.empty:
        raise AssertionError("Pattern CSV contains no demand-load events")

    for cpu, rows in frame.groupby("cpu", sort=True):
        sequence = rows["load_tlb_seq"].to_numpy(dtype=np.uint64)
        expected = np.arange(len(rows), dtype=np.uint64)
        if not np.array_equal(sequence, expected):
            raise AssertionError(f"Core {cpu}: load_tlb_seq is not contiguous from zero")

    if frame.duplicated(["cpu", "load_tlb_seq"]).any():
        raise AssertionError("Duplicate (cpu, load_tlb_seq)")
    if frame.duplicated(["cpu", "instr_id", "operand_index"]).any():
        raise AssertionError("Duplicate dynamic demand-load identity (cpu, instr_id, operand_index)")
    if not np.array_equal(frame["vpn"].to_numpy(), frame["va"].to_numpy() // page_size):
        raise AssertionError("vpn != va / page_size")
    if not np.array_equal(frame["virtual_region_2m"].to_numpy(), frame["va"].to_numpy() // region_size):
        raise AssertionError("virtual_region_2m != va / region_size")
    expected_offset = (frame["va"].to_numpy() % region_size) // page_size
    if not np.array_equal(frame["page_offset_in_region"].to_numpy(), expected_offset):
        raise AssertionError("page_offset_in_region is inconsistent with va")

    complete = frame["completion_state"].astype(str) == "COMPLETE"
    if has_physical_fields:
        physical_valid = frame["physical_address_valid"].astype(bool)
        if not np.array_equal(physical_valid.to_numpy(), complete.to_numpy()):
            raise AssertionError("physical_address_valid must match completion_state")
        valid = frame.loc[physical_valid]
        if not np.array_equal(valid["pa"].to_numpy(), valid["ppn"].to_numpy() * page_size + valid["va"].to_numpy() % page_size):
            raise AssertionError("pa is inconsistent with ppn and virtual page offset")
        if not np.array_equal(valid["physical_region_2m"].to_numpy(), valid["pa"].to_numpy() // region_size):
            raise AssertionError("physical_region_2m != pa / region_size")
        expected_physical_offset = (valid["pa"].to_numpy() % region_size) // page_size
        if not np.array_equal(valid["page_offset_in_physical_region"].to_numpy(), expected_physical_offset):
            raise AssertionError("page_offset_in_physical_region is inconsistent with pa")
        invalid_physical_fields = frame.loc[~physical_valid, ["pa", "ppn", "physical_region_2m", "page_offset_in_physical_region"]]
        if (invalid_physical_fields != 0).any().any():
            raise AssertionError("Incomplete events must use zero for unavailable physical-address fields")
        mapping = valid[["cpu", "vpn", "ppn"]].drop_duplicates()
        if mapping.duplicated(["cpu", "vpn"]).any():
            raise AssertionError("A VPN changed its PPN mapping within a core")

    l1_hit = frame["l1dtlb_result"].astype(str) == "HIT"
    l1_miss = frame["l1dtlb_result"].astype(str) == "MISS"
    stlb_accessed = frame["stlb_accessed"].astype(bool)
    stlb_named = frame["stlb_result"].astype(str) != "NOT_ACCESSED"
    if (l1_hit & stlb_accessed).any():
        raise AssertionError("L1 DTLB hit event accessed STLB")
    if (stlb_accessed & ~l1_miss).any():
        raise AssertionError("STLB access without L1 DTLB miss")
    if (stlb_named & ~stlb_accessed).any():
        raise AssertionError("Named STLB result without an STLB access")

    if (complete & (frame["l1dtlb_result"].astype(str) == "UNKNOWN")).any():
        raise AssertionError("Completed event has an unknown L1 DTLB result")
    if (complete & stlb_accessed & (frame["stlb_result"].astype(str) == "UNKNOWN")).any():
        raise AssertionError("Completed STLB-access event has an unknown STLB result")
    if (frame.loc[complete, "translation_complete_cycle"] < frame.loc[complete, "dtlb_lookup_cycle"]).any():
        raise AssertionError("Translation completed before its accepted DTLB request")
    if (frame.loc[~complete, "translation_complete_cycle"] != 0).any():
        raise AssertionError("Incomplete event has a nonzero completion cycle")

    if summary_path is not None:
        summaries = parse_logger_summary(summary_path)
        for cpu, rows in frame.groupby("cpu", sort=True):
            summary = summaries.get(int(cpu))
            if summary is None:
                raise AssertionError(f"Missing logger summary for core {cpu}")
            completed = int((rows["completion_state"].astype(str) == "COMPLETE").sum())
            incomplete = len(rows) - completed
            expected_counts = {
                "created_events": len(rows),
                "completed_events": completed,
                "incomplete_events": incomplete,
                "l1dtlb_hits": int((rows["l1dtlb_result"].astype(str) == "HIT").sum()),
                "l1dtlb_misses": int((rows["l1dtlb_result"].astype(str) == "MISS").sum()),
                "l1dtlb_merges": int(rows["l1dtlb_merged"].sum()),
                "stlb_accesses": int(rows["stlb_accessed"].sum()),
                "stlb_hits": int((rows["stlb_result"].astype(str) == "HIT").sum()),
                "stlb_misses": int((rows["stlb_result"].astype(str) == "MISS").sum()),
                "stlb_merges": int(rows["stlb_merged"].sum()),
            }
            for key, expected_value in expected_counts.items():
                if summary.get(key) != expected_value:
                    raise AssertionError(f"Core {cpu}: {key} summary={summary.get(key)} CSV={expected_value}")

    address_scope = "VPN+PPN" if has_physical_fields else "VPN-only (legacy stream without physical-address fields)"
    print(f"[PASS] Validated {len(frame):,} demand-load TLB pattern events [{address_scope}] from {input_path}")
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate demand-load TLB pattern logger output.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--logger-summary", type=Path)
    args = parser.parse_args()
    validate(args.input, args.metadata, args.logger_summary)


if __name__ == "__main__":
    main()
