#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


DTYPES = {
    "cpu": "uint32",
    "global_seq": "uint64",
    "event_type": "category",
    "load_tlb_seq": "UInt64",
    "cross_page_prefetch_seq": "UInt64",
    "vberti_prefetch_seq": "UInt64",
    "instr_id": "UInt64",
    "operand_index": "UInt32",
    "pc": "uint64",
    "prefetch_issue_cycle": "UInt64",
    "prefetch_trigger_instr_id": "UInt64",
    "prefetch_trigger_pc": "UInt64",
    "prefetch_trigger_va": "UInt64",
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
    "dtlb_merge_detail": "category",
    "stlb_accessed": "uint8",
    "stlb_result": "category",
    "stlb_merged": "uint8",
    "stlb_merge_detail": "category",
    "completion_state": "category",
    "raster_outcome_category": "category",
}

PHYSICAL_FIELDS = {
    "pa",
    "ppn",
    "physical_region_2m",
    "page_offset_in_physical_region",
    "physical_address_valid",
}

DTLB_MERGE_DETAILS = {
    "NONE",
    "RQ_MERGE",
    "MSHR_TO_DATA_DEMAND",
    "MSHR_TO_INST_DEMAND",
    "MSHR_TO_L1D_PREFETCH",
    "MSHR_TO_CP_PREFETCH",
    "MSHR_TO_SP_PREFETCH",
    "MSHR_TO_L1I_PREFETCH",
    "MSHR_TO_OTHER",
    "PRELOOKUP_COALESCED",
}

RASTER_OUTCOME_CATEGORIES = {
    "L1 DTLB hit",
    "L1 miss + STLB hit",
    "STLB miss",
    "DTLB-side translation merge",
    "STLB-side translation merge",
    "Other / incomplete",
}


def validate_dtlb_merge_detail(frame: pd.DataFrame) -> None:
    """Validate the optional legacy-compatible, mutually exclusive merge explanation."""
    if "dtlb_merge_detail" not in frame.columns:
        return

    detail = frame["dtlb_merge_detail"].astype(str)
    unexpected = set(detail.unique()) - DTLB_MERGE_DETAILS
    if unexpected:
        raise AssertionError(f"Unexpected dtlb_merge_detail values: {sorted(unexpected)}")

    merged = frame["l1dtlb_merged"].astype(bool)
    detailed_merge = detail.ne("NONE")
    if not np.array_equal(merged.to_numpy(), detailed_merge.to_numpy()):
        raise AssertionError("l1dtlb_merged must be exactly equivalent to dtlb_merge_detail != NONE")

    miss_only = detail.str.startswith("MSHR_TO_") | detail.eq("PRELOOKUP_COALESCED")
    if (miss_only & frame["l1dtlb_result"].astype(str).ne("MISS")).any():
        raise AssertionError("MSHR/prelookup merge detail requires an L1 DTLB miss result")


def validate_stlb_merge_detail(frame: pd.DataFrame) -> None:
    """Validate the optional legacy-compatible STLB RQ/MSHR merge explanation."""
    if "stlb_merge_detail" not in frame.columns:
        return

    detail = frame["stlb_merge_detail"].astype(str)
    unexpected = set(detail.unique()) - (DTLB_MERGE_DETAILS - {"PRELOOKUP_COALESCED"})
    if unexpected:
        raise AssertionError(f"Unexpected stlb_merge_detail values: {sorted(unexpected)}")

    merged = frame["stlb_merged"].astype(bool)
    detailed_merge = detail.ne("NONE")
    if not np.array_equal(merged.to_numpy(), detailed_merge.to_numpy()):
        raise AssertionError("stlb_merged must be exactly equivalent to stlb_merge_detail != NONE")

    mshr_merge = detail.str.startswith("MSHR_TO_")
    stlb_accessed = frame["stlb_accessed"].astype(bool)
    stlb_miss = frame["stlb_result"].astype(str).eq("MISS")
    if (mshr_merge & (~stlb_accessed | ~stlb_miss)).any():
        raise AssertionError("STLB MSHR merge detail requires an executed STLB miss lookup")
    if (detail.eq("RQ_MERGE") & stlb_accessed).any():
        raise AssertionError("STLB RQ merge must not be counted as an independent STLB lookup")


def validate_raster_outcome_category(frame: pd.DataFrame) -> None:
    """Validate the optional legacy-compatible native coarse outcome field."""
    if "raster_outcome_category" not in frame.columns:
        return

    actual = frame["raster_outcome_category"].astype(str)
    unexpected = set(actual.unique()) - RASTER_OUTCOME_CATEGORIES
    if unexpected:
        raise AssertionError(f"Unexpected raster_outcome_category values: {sorted(unexpected)}")

    complete = frame["completion_state"].astype(str).eq("COMPLETE")
    l1_merged = frame["l1dtlb_merged"].astype(bool)
    stlb_merged = frame["stlb_merged"].astype(bool)
    l1_result = frame["l1dtlb_result"].astype(str)
    stlb_accessed = frame["stlb_accessed"].astype(bool)
    stlb_result = frame["stlb_result"].astype(str)
    ordinary = complete & ~l1_merged & ~stlb_merged

    expected = pd.Series("Other / incomplete", index=frame.index, dtype="object")
    expected.loc[ordinary & l1_result.eq("HIT")] = "L1 DTLB hit"
    expected.loc[ordinary & l1_result.eq("MISS") & stlb_accessed & stlb_result.eq("HIT")] = "L1 miss + STLB hit"
    expected.loc[ordinary & l1_result.eq("MISS") & stlb_accessed & stlb_result.eq("MISS")] = "STLB miss"
    expected.loc[complete & ~l1_merged & stlb_merged] = "STLB-side translation merge"
    expected.loc[complete & l1_merged] = "DTLB-side translation merge"
    if not actual.equals(expected):
        raise AssertionError("raster_outcome_category is inconsistent with the native lifecycle fields")


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
    validate_dtlb_merge_detail(frame)
    validate_stlb_merge_detail(frame)
    validate_raster_outcome_category(frame)

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


def validate_unified(input_path: Path, metadata_path: Path, summary_path: Path | None) -> pd.DataFrame:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    page_size = int(metadata["page_size"])
    region_size = int(metadata["region_size"])
    input_columns = set(pd.read_csv(input_path, nrows=0).columns)
    required = {
        "cpu", "global_seq", "event_type", "load_tlb_seq", "cross_page_prefetch_seq", "va", "vpn",
        "virtual_region_2m", "page_offset_in_region", "l1dtlb_result", "l1dtlb_merged", "dtlb_merge_detail", "stlb_accessed",
        "stlb_result", "stlb_merged", "stlb_merge_detail", "completion_state", "raster_outcome_category",
    }
    missing = sorted(required - input_columns)
    if missing:
        raise AssertionError(f"Unified pattern schema is missing: {', '.join(missing)}")
    present_physical_fields = PHYSICAL_FIELDS & input_columns
    if present_physical_fields and present_physical_fields != PHYSICAL_FIELDS:
        raise AssertionError(f"Partial physical-address schema; missing: {', '.join(sorted(PHYSICAL_FIELDS - present_physical_fields))}")
    has_physical_fields = present_physical_fields == PHYSICAL_FIELDS
    frame = pd.read_csv(input_path, dtype={name: dtype for name, dtype in DTYPES.items() if name in input_columns})
    if frame.empty:
        raise AssertionError("Unified pattern CSV contains no events")
    frame = frame.sort_values(["cpu", "global_seq"], kind="stable").reset_index(drop=True)

    allowed_types = {"DATA_DEMAND", "VBERTI_CP_PREFETCH"}
    actual_types = set(frame["event_type"].astype(str).unique())
    if not actual_types <= allowed_types:
        raise AssertionError(f"Unexpected event types: {sorted(actual_types - allowed_types)}")
    demand = frame["event_type"].astype(str).eq("DATA_DEMAND")
    prefetch = frame["event_type"].astype(str).eq("VBERTI_CP_PREFETCH")
    if not demand.any():
        raise AssertionError("Unified stream has no real-data demand")

    for cpu, rows in frame.groupby("cpu", sort=True):
        global_seq = rows["global_seq"].to_numpy(dtype=np.uint64)
        if not np.array_equal(global_seq, np.arange(len(rows), dtype=np.uint64)):
            raise AssertionError(f"Core {cpu}: global_seq is not contiguous from zero")
        cpu_demand = rows["event_type"].astype(str).eq("DATA_DEMAND")
        cpu_prefetch = rows["event_type"].astype(str).eq("VBERTI_CP_PREFETCH")
        demand_seq = rows.loc[cpu_demand, "load_tlb_seq"].dropna().to_numpy(dtype=np.uint64)
        prefetch_seq = rows.loc[cpu_prefetch, "cross_page_prefetch_seq"].dropna().to_numpy(dtype=np.uint64)
        if len(demand_seq) != int(cpu_demand.sum()) or not np.array_equal(demand_seq, np.arange(len(demand_seq), dtype=np.uint64)):
            raise AssertionError(f"Core {cpu}: load_tlb_seq is incomplete or non-contiguous")
        if len(prefetch_seq) != int(cpu_prefetch.sum()) or not np.array_equal(prefetch_seq, np.arange(len(prefetch_seq), dtype=np.uint64)):
            raise AssertionError(f"Core {cpu}: cross_page_prefetch_seq is incomplete or non-contiguous")
    if frame.loc[demand, "cross_page_prefetch_seq"].notna().any() or frame.loc[prefetch, "load_tlb_seq"].notna().any():
        raise AssertionError("An event has a sequence number belonging to the other event type")
    if frame.duplicated(["cpu", "global_seq"]).any():
        raise AssertionError("Duplicate (cpu, global_seq)")
    demand_identity = frame.loc[demand & frame["instr_id"].notna() & frame["operand_index"].notna()]
    if demand_identity.duplicated(["cpu", "instr_id", "operand_index"]).any():
        raise AssertionError("Duplicate real-demand dynamic identity")

    if not np.array_equal(frame["vpn"].to_numpy(), frame["va"].to_numpy() // page_size):
        raise AssertionError("vpn != va / page_size")
    if not np.array_equal(frame["virtual_region_2m"].to_numpy(), frame["va"].to_numpy() // region_size):
        raise AssertionError("virtual_region_2m != va / region_size")
    expected_offset = (frame["va"].to_numpy() % region_size) // page_size
    if not np.array_equal(frame["page_offset_in_region"].to_numpy(), expected_offset):
        raise AssertionError("page_offset_in_region is inconsistent with va")

    complete = frame["completion_state"].astype(str).eq("COMPLETE")
    if has_physical_fields:
        physical_valid = frame["physical_address_valid"].astype(bool)
        if not np.array_equal(physical_valid.to_numpy(), complete.to_numpy()):
            raise AssertionError("physical_address_valid must match completion_state")
        valid = frame.loc[physical_valid]
        if not np.array_equal(valid["pa"].to_numpy(), valid["ppn"].to_numpy() * page_size + valid["va"].to_numpy() % page_size):
            raise AssertionError("pa is inconsistent with ppn and virtual page offset")
        mapping = valid[["cpu", "vpn", "ppn"]].drop_duplicates()
        if mapping.duplicated(["cpu", "vpn"]).any():
            raise AssertionError("A VPN changed its PPN mapping within a core")

    l1_hit = frame["l1dtlb_result"].astype(str).eq("HIT")
    l1_miss = frame["l1dtlb_result"].astype(str).eq("MISS")
    stlb_accessed = frame["stlb_accessed"].astype(bool)
    stlb_named = frame["stlb_result"].astype(str).ne("NOT_ACCESSED")
    if (l1_hit & stlb_accessed).any() or (stlb_accessed & ~l1_miss).any() or (stlb_named & ~stlb_accessed).any():
        raise AssertionError("Inconsistent DTLB/STLB lifecycle fields")
    validate_dtlb_merge_detail(frame)
    validate_stlb_merge_detail(frame)
    validate_raster_outcome_category(frame)
    if (complete & frame["l1dtlb_result"].astype(str).eq("UNKNOWN")).any():
        raise AssertionError("Completed event has an unknown L1 DTLB result")
    if (complete & stlb_accessed & frame["stlb_result"].astype(str).eq("UNKNOWN")).any():
        raise AssertionError("Completed STLB-access event has an unknown STLB result")
    if (frame.loc[complete, "translation_complete_cycle"] < frame.loc[complete, "dtlb_lookup_cycle"]).any():
        raise AssertionError("Translation completed before its DTLB issue")

    if summary_path is not None:
        summaries = parse_logger_summary(summary_path)
        for cpu, rows in frame.groupby("cpu", sort=True):
            summary = summaries.get(int(cpu))
            if summary is None:
                raise AssertionError(f"Missing logger summary for core {cpu}")
            row_demand = rows["event_type"].astype(str).eq("DATA_DEMAND")
            row_prefetch = ~row_demand
            row_complete = rows["completion_state"].astype(str).eq("COMPLETE")
            expected_counts = {
                "demand_events": int(row_demand.sum()),
                "completed_demand_events": int((row_demand & row_complete).sum()),
                "incomplete_demand_events": int((row_demand & ~row_complete).sum()),
                "cross_page_prefetch_events": int(row_prefetch.sum()),
                "completed_cross_page_prefetch_events": int((row_prefetch & row_complete).sum()),
                "incomplete_cross_page_prefetch_events": int((row_prefetch & ~row_complete).sum()),
                "total_common_events": len(rows),
            }
            for key, expected_value in expected_counts.items():
                if summary.get(key) != expected_value:
                    raise AssertionError(f"Core {cpu}: {key} summary={summary.get(key)} CSV={expected_value}")

    prefetch_count = int(prefetch.sum())
    print(f"[PASS] Validated {len(frame):,} unified TLB events: real demand={int(demand.sum()):,}, cross-page vBerti={prefetch_count:,}")
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate demand-only or unified demand/prefetch TLB pattern output.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--logger-summary", type=Path)
    args = parser.parse_args()
    columns = set(pd.read_csv(args.input, nrows=0).columns)
    if {"global_seq", "event_type"} <= columns:
        validate_unified(args.input, args.metadata, args.logger_summary)
    else:
        validate(args.input, args.metadata, args.logger_summary)


if __name__ == "__main__":
    main()
