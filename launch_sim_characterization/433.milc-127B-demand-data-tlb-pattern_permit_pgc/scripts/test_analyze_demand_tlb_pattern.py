#!/usr/bin/env python3

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_demand_tlb_pattern import (COMPACT_DROP_FIELDS, build_future_vpn_matches, choose_combined_local_window, classify_translation_outcomes,
                                        compress_vpn_stream, configure_address_space, deduplicate_vpn_frame, export_local_raster_records,
                                        first_touch_ids, global_page_deltas, per_pc_deltas, plot_per_pc, ranked_delta_coverage,
                                        validate_combined_pattern, write_raw_global_delta_topk)


def main() -> None:
    global_vpns = np.array([10, 10, 11, 11, 15, 14], dtype=np.int64)
    assert compress_vpn_stream(global_vpns).tolist() == [10, 11, 15, 14]
    assert first_touch_ids(np.array([10, 10, 11, 10, 15, 11], dtype=np.int64)).tolist() == [0, 0, 1, 0, 2, 1]
    deduplicated = deduplicate_vpn_frame(pd.DataFrame({"load_tlb_seq": np.arange(6), "vpn": global_vpns}))
    assert deduplicated["page_transition_seq"].tolist() == [0, 1, 2, 3]
    assert deduplicated["load_tlb_seq"].tolist() == [0, 2, 4, 5]
    assert deduplicated["vpn"].tolist() == [10, 11, 15, 14]
    assert deduplicated["first_touch_vpn_id"].tolist() == [0, 1, 2, 3]
    assert deduplicated["consecutive_run_length"].tolist() == [2, 2, 1, 1]
    assert global_page_deltas(global_vpns).tolist() == [1, 4, -1]

    pc_vpns = np.array([20, 20, 21, 21, 25], dtype=np.int64)
    pc_delta = per_pc_deltas(pc_vpns)
    assert pc_delta.tolist() == [0, 1, 0, 4]
    top1, top1_coverage = ranked_delta_coverage(pc_delta, 1)
    top2, top2_coverage = ranked_delta_coverage(pc_delta, 2)
    assert top1 == [0]
    assert top1_coverage == 0.5
    assert top2 == [0, 1]
    assert top2_coverage == 0.75

    outcome_rows = pd.DataFrame(
        {
            "completion_state": ["COMPLETE", "COMPLETE", "COMPLETE", "COMPLETE", "COMPLETE", "INCOMPLETE", "COMPLETE"],
            "l1dtlb_result": ["HIT", "MISS", "MISS", "HIT", "MISS", "HIT", "MISS"],
            "l1dtlb_merged": [0, 0, 0, 1, 0, 0, 0],
            "stlb_accessed": [0, 1, 1, 0, 1, 0, 0],
            "stlb_result": ["NOT_ACCESSED", "HIT", "MISS", "NOT_ACCESSED", "MISS", "NOT_ACCESSED", "NOT_ACCESSED"],
            "stlb_merged": [0, 0, 0, 0, 1, 0, 0],
        }
    )
    outcomes = classify_translation_outcomes(outcome_rows)
    assert {name: int(mask.sum()) for name, mask in outcomes.items()} == {
        "L1 DTLB hit": 1,
        "L1 miss + STLB hit": 1,
        "STLB miss": 1,
        "DTLB-side translation merge": 1,
        "STLB-side translation merge": 1,
        "Other / incomplete": 2,
    }
    assert all(sum(bool(mask.iloc[row]) for mask in outcomes.values()) == 1 for row in range(len(outcome_rows)))
    with tempfile.TemporaryDirectory() as directory:
        raster_rows = outcome_rows.copy()
        raster_rows.insert(0, "load_tlb_seq", np.arange(len(raster_rows), dtype=np.uint64))
        raster_rows["vberti_prefetch_seq"] = np.arange(len(raster_rows), dtype=np.uint64)
        raster_rows["prefetch_issue_cycle"] = np.arange(len(raster_rows), dtype=np.uint64) + 100
        raster_rows["pa"] = np.arange(len(raster_rows), dtype=np.uint64) * 4096
        raster_rows["ppn"] = np.arange(len(raster_rows), dtype=np.uint64)
        raster_rows["physical_region_2m"] = 0
        raster_rows["page_offset_in_physical_region"] = np.arange(len(raster_rows), dtype=np.uint64)
        raster_rows["physical_address_valid"] = 1
        raster_rows["pattern_seq"] = raster_rows["load_tlb_seq"]
        raster_path = export_local_raster_records(raster_rows, outcomes, Path(directory), "load_tlb_seq")
        exported_raster = pd.read_csv(raster_path)
        compact_raster = pd.read_csv(Path(directory) / "02_local_page_offset_raster_records_load_tlb_seq_compact.csv")
        assert len(exported_raster) == len(raster_rows)
        assert "pattern_seq" not in exported_raster.columns
        assert exported_raster.columns[-1] == "raster_outcome_category"
        assert exported_raster["raster_outcome_category"].value_counts().to_dict()["Other / incomplete"] == 2
        assert len(compact_raster) == len(exported_raster)
        assert not (COMPACT_DROP_FIELDS & set(compact_raster.columns))
        assert compact_raster["load_tlb_seq"].tolist() == exported_raster["load_tlb_seq"].tolist()

        write_raw_global_delta_topk(pd.DataFrame({"vpn": [10, 10, 11, 10, 10]}), Path(directory), k=3)
        raw_topk = pd.read_csv(Path(directory) / "03_raw_vpn_delta_global_top20.csv")
        assert raw_topk[["delta", "count"]].values.tolist() == [[0, 2], [-1, 1], [1, 1]]
        assert raw_topk["ratio"].tolist() == [0.5, 0.25, 0.25]
        configure_address_space("physical")
        ppn_frame = pd.DataFrame({"load_tlb_seq": np.arange(5), "ppn": [100, 100, 105, 105, 101]})
        deduplicated_ppn = deduplicate_vpn_frame(ppn_frame)
        assert deduplicated_ppn["ppn"].tolist() == [100, 105, 101]
        assert deduplicated_ppn["first_touch_ppn_id"].tolist() == [0, 1, 2]
        write_raw_global_delta_topk(ppn_frame, Path(directory), k=3)
        ppn_topk = pd.read_csv(Path(directory) / "03_raw_ppn_delta_global_top20.csv")
        assert ppn_topk[["delta", "count"]].values.tolist() == [[0, 2], [-4, 1], [5, 1]]
        configure_address_space("virtual")

        pc_rows = pd.DataFrame(
            {
                "pattern_seq": np.arange(64, dtype=np.uint64),
                "pc": np.repeat(np.array([0x10, 0x20], dtype=np.uint64), 32),
                "vpn": np.tile(np.arange(32, dtype=np.uint64), 2),
                "l1dtlb_result": ["MISS"] * 64,
                "stlb_accessed": [1] * 64,
                "stlb_result": ["MISS"] * 8 + ["HIT"] * 24 + ["MISS"] * 2 + ["HIT"] * 30,
            }
        )
        plot_per_pc(pc_rows, Path(directory), top_pcs=2, rank_by="stlb_miss", delta_limit=16)
        per_pc_path = Path(directory) / "04_per_pc_topk.csv"
        raw_per_pc = pd.read_csv(per_pc_path, nrows=2)
        dedup_per_pc = pd.read_csv(per_pc_path, skiprows=4)
        assert raw_per_pc.columns[-1] == "raw_stlb_miss_share_of_all_pct"
        assert dedup_per_pc.columns[-1] == "raw_stlb_miss_share_of_all_pct"
        assert raw_per_pc["raw_stlb_miss_share_of_all_pct"].tolist() == [80.0, 20.0]
        assert dedup_per_pc["raw_stlb_miss_share_of_all_pct"].tolist() == [80.0, 20.0]

    combined = pd.DataFrame(
        {
            "cpu": [0] * 6,
            "global_seq": np.arange(6, dtype=np.uint64),
            "dtlb_lookup_cycle": [100, 101, 103, 105, 107, 109],
            "event_type": ["DATA_DEMAND", "VBERTI_CP_PREFETCH", "DATA_DEMAND",
                           "VBERTI_CP_PREFETCH", "VBERTI_CP_PREFETCH", "DATA_DEMAND"],
            "load_tlb_seq": [0, np.nan, 1, np.nan, np.nan, 2],
            "cross_page_prefetch_seq": [np.nan, 0, np.nan, 1, 2, np.nan],
            "pc": [0x10, 0x20, 0x10, 0x20, 0x20, 0x10],
            "prefetch_issue_cycle": [np.nan, 101, np.nan, 105, 107, np.nan],
            "prefetch_trigger_pc": [np.nan, 0x20, np.nan, 0x20, 0x20, np.nan],
            "prefetch_trigger_va": [np.nan, 0x1000, np.nan, 0x3000, 0x5000, np.nan],
            "va": [0x2000, 0x4000, 0x4008, 0x6000, 0x7000, 0x6008],
            "vpn": [2, 4, 4, 6, 7, 6],
            "virtual_region_2m": [0] * 6,
            "page_offset_in_region": [2, 4, 4, 6, 7, 6],
        }
    )
    combined = validate_combined_pattern(combined, 4096)
    displayed = combined
    assert choose_combined_local_window(displayed, 4, None, None, None) == (0, 0, 4)
    matches = build_future_vpn_matches(
        combined[combined["event_type"].eq("DATA_DEMAND")],
        combined[combined["event_type"].eq("VBERTI_CP_PREFETCH")],
    )
    assert matches["future_demand_found"].tolist() == [1, 1, 0]
    assert matches["lead_global_events"].iloc[:2].tolist() == [1.0, 2.0]
    print("[PASS] Synthetic trajectory, global/per-PC delta, Top-k coverage, and common-sequence tests passed.")


if __name__ == "__main__":
    main()
