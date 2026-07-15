#!/usr/bin/env python3

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

from validate_demand_tlb_pattern import DTYPES


COLORS = {
    "l1_hit": "#b8b8b8",
    "stlb_hit": "#e69f45",
    "stlb_miss": "#c84b4b",
    "dtlb_merge": "#7b5aa6",
    "stlb_merge": "#2a9d8f",
    "other": "#3f3f3f",
    "selected": "#2878b5",
    "bar": "#4c78a8",
}

STREAM_SPECS = {
    "dtlb_access": {"sequence_column": "load_tlb_seq", "sequence_label": "load_tlb_seq", "title": "Demand-data L1 DTLB access"},
    "stlb_access": {"sequence_column": "stlb_access_seq", "sequence_label": "stlb_access_seq", "title": "Demand-data STLB access"},
    "stlb_miss": {"sequence_column": "stlb_miss_seq", "sequence_label": "stlb_miss_seq", "title": "Demand-data STLB miss"},
}

PAGE_NUMBER_COLUMN = "vpn"
REGION_COLUMN = "virtual_region_2m"
REGION_OFFSET_COLUMN = "page_offset_in_region"
PAGE_TOKEN = "vpn"
PAGE_ACRONYM = "VPN"
ADDRESS_SPACE_ADJECTIVE = "virtual"


def configure_address_space(address_space: str) -> None:
    global PAGE_NUMBER_COLUMN, REGION_COLUMN, REGION_OFFSET_COLUMN, PAGE_TOKEN, PAGE_ACRONYM, ADDRESS_SPACE_ADJECTIVE
    if address_space == "physical":
        PAGE_NUMBER_COLUMN = "ppn"
        REGION_COLUMN = "physical_region_2m"
        REGION_OFFSET_COLUMN = "page_offset_in_physical_region"
        PAGE_TOKEN = "ppn"
        PAGE_ACRONYM = "PPN"
        ADDRESS_SPACE_ADJECTIVE = "physical"
    else:
        PAGE_NUMBER_COLUMN = "vpn"
        REGION_COLUMN = "virtual_region_2m"
        REGION_OFFSET_COLUMN = "page_offset_in_region"
        PAGE_TOKEN = "vpn"
        PAGE_ACRONYM = "VPN"
        ADDRESS_SPACE_ADJECTIVE = "virtual"


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.png", dpi=320, bbox_inches="tight")
    plt.close(fig)


def parse_integer(value: str) -> int:
    return int(value, 0)


def compress_vpn_stream(vpns: np.ndarray) -> np.ndarray:
    vpns = np.asarray(vpns, dtype=np.int64)
    if vpns.size == 0:
        return vpns
    return vpns[np.r_[True, vpns[1:] != vpns[:-1]]]


def first_touch_ids(vpns: np.ndarray) -> np.ndarray:
    codes, _ = pd.factorize(np.asarray(vpns, dtype=np.int64), sort=False)
    return codes.astype(np.int64, copy=False)


def deduplicate_vpn_frame(frame: pd.DataFrame) -> pd.DataFrame:
    vpns = frame[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)
    first_touch_column = f"first_touch_{PAGE_TOKEN}_id"
    if len(vpns) == 0:
        result = frame.copy()
        result.insert(0, "page_transition_seq", np.array([], dtype=np.int64))
        result.insert(1, first_touch_column, np.array([], dtype=np.int64))
        result.insert(2, "consecutive_run_length", np.array([], dtype=np.int64))
        return result

    run_starts = np.flatnonzero(np.r_[True, vpns[1:] != vpns[:-1]])
    run_ends = np.r_[run_starts[1:], len(vpns)]
    result = frame.iloc[run_starts].copy().reset_index(drop=True)
    result.insert(0, "page_transition_seq", np.arange(len(result), dtype=np.int64))
    result.insert(1, first_touch_column, first_touch_ids(result[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)))
    result.insert(2, "consecutive_run_length", run_ends - run_starts)
    return result


def global_page_deltas(vpns: np.ndarray) -> np.ndarray:
    compressed = compress_vpn_stream(vpns)
    return np.diff(compressed)


def write_raw_global_delta_topk(frame: pd.DataFrame, output_dir: Path, k: int = 20) -> None:
    """Write Top-K deltas from the original stream, including consecutive same-page delta-zero pairs."""
    vpns = frame[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)
    deltas = np.diff(vpns)
    total = len(deltas)
    ranked = sorted(Counter(int(value) for value in deltas).items(), key=lambda item: (-item[1], item[0]))[:k]
    rows = [
        {"rank": rank, "delta": delta, "count": count, "ratio": count / total if total else 0.0}
        for rank, (delta, count) in enumerate(ranked, start=1)
    ]
    pd.DataFrame(rows, columns=["rank", "delta", "count", "ratio"]).to_csv(
        output_dir / f"03_raw_{PAGE_TOKEN}_delta_global_top20.csv", index=False
    )


def per_pc_deltas(vpns: np.ndarray) -> np.ndarray:
    return np.diff(np.asarray(vpns, dtype=np.int64))


def ranked_delta_coverage(deltas: np.ndarray, k: int) -> tuple[list[int], float]:
    if len(deltas) == 0:
        return [], 0.0
    ranked = sorted(Counter(int(value) for value in deltas).items(), key=lambda item: (-item[1], item[0]))
    selected = ranked[:k]
    return [value for value, _ in selected], sum(count for _, count in selected) / len(deltas)


def delta_bucket_labels(limit: int, include_zero: bool) -> list[str]:
    middle = list(range(-limit, limit + 1)) if include_zero else list(range(-limit, 0)) + list(range(1, limit + 1))
    return [f"<-{limit}"] + [f"{value:+d}" for value in middle] + [f">+{limit}"]


def bucket_deltas(deltas: np.ndarray, limit: int, include_zero: bool) -> np.ndarray:
    middle = list(range(-limit, limit + 1)) if include_zero else list(range(-limit, 0)) + list(range(1, limit + 1))
    index = {value: idx + 1 for idx, value in enumerate(middle)}
    counts = np.zeros(len(middle) + 2, dtype=np.int64)
    for raw in deltas:
        value = int(raw)
        if value < -limit:
            counts[0] += 1
        elif value > limit:
            counts[-1] += 1
        elif value in index:
            counts[index[value]] += 1
    return counts


def save_trajectory(
    x: np.ndarray,
    y: np.ndarray,
    output_dir: Path,
    stem: str,
    xlabel: str,
    ylabel: str,
    title: str,
    secondary_x: np.ndarray | None = None,
    secondary_xlabel: str = "load_tlb_seq",
) -> None:
    column_count = 2 if secondary_x is not None else 1
    fig, axes = plt.subplots(1, column_count, figsize=(12.0 * column_count, 4.8), squeeze=False)
    views = [(x, xlabel, f"{title} ({xlabel})")]
    if secondary_x is not None:
        views.append((secondary_x, secondary_xlabel, f"{title} ({secondary_xlabel})"))
    for ax, (view_x, view_xlabel, view_title) in zip(axes.flat, views):
        ax.scatter(view_x, y, s=0.25, color=COLORS["bar"], alpha=0.7, linewidths=0, rasterized=True)
        ax.set_xlabel(view_xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(view_title)
        ax.grid(linestyle=":", linewidth=0.45, alpha=0.35)
    save_figure(fig, output_dir, stem)


def plot_vpn_trajectories(frame: pd.DataFrame, output_dir: Path, sequence_label: str, stream_title: str, dual_load_sequence: bool) -> None:
    raw_seq = frame["pattern_seq"].to_numpy(dtype=np.int64)
    raw_vpns = frame[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)
    raw_first_touch = first_touch_ids(raw_vpns)
    raw_load_seq = frame["load_tlb_seq"].to_numpy(dtype=np.int64) if dual_load_sequence else None

    save_trajectory(
        raw_seq,
        raw_vpns,
        output_dir,
        f"05a_raw_{PAGE_TOKEN}_trajectory",
        sequence_label,
        f"Raw {ADDRESS_SPACE_ADJECTIVE} page number",
        f"Raw ROI {stream_title} {PAGE_ACRONYM} trajectory",
        secondary_x=raw_load_seq,
    )
    save_trajectory(
        raw_seq,
        raw_first_touch,
        output_dir,
        f"05b_raw_first_touch_{PAGE_TOKEN}_id_trajectory",
        sequence_label,
        f"First-touch {PAGE_ACRONYM} id",
        f"Raw ROI {stream_title} first-touch {PAGE_ACRONYM}-id trajectory",
        secondary_x=raw_load_seq,
    )

    transition_frame = deduplicate_vpn_frame(frame)
    transition_frame.to_csv(output_dir / f"05_deduplicated_{PAGE_TOKEN}_access_stream.csv", index=False)
    transition_vpns = transition_frame[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)
    transition_seq = transition_frame["page_transition_seq"].to_numpy(dtype=np.int64)
    transition_first_touch = transition_frame[f"first_touch_{PAGE_TOKEN}_id"].to_numpy(dtype=np.int64)
    transition_load_seq = transition_frame["load_tlb_seq"].to_numpy(dtype=np.int64) if dual_load_sequence else None
    save_trajectory(
        transition_seq,
        transition_vpns,
        output_dir,
        f"05c_deduplicated_{PAGE_TOKEN}_trajectory",
        f"{stream_title.lower().replace(' ', '_')}_page_transition_seq",
        f"{ADDRESS_SPACE_ADJECTIVE.title()} page number",
        f"{PAGE_ACRONYM} trajectory after removing consecutive repeated {PAGE_ACRONYM}s",
        secondary_x=transition_load_seq,
    )
    save_trajectory(
        transition_seq,
        transition_first_touch,
        output_dir,
        f"05d_deduplicated_first_touch_{PAGE_TOKEN}_id_trajectory",
        f"{stream_title.lower().replace(' ', '_')}_page_transition_seq",
        f"First-touch {PAGE_ACRONYM} id",
        f"First-touch {PAGE_ACRONYM}-id trajectory after removing consecutive repeated {PAGE_ACRONYM}s",
        secondary_x=transition_load_seq,
    )


def choose_local_window(
    frame: pd.DataFrame,
    coarse_bin_size: int,
    requested_region: int | None,
    requested_start: int | None,
    requested_end: int | None,
) -> tuple[int, int, int]:
    if (requested_start is None) != (requested_end is None):
        raise ValueError("--seq-start and --seq-end must be supplied together")
    if requested_start is not None and requested_start >= requested_end:
        raise ValueError("--seq-start must be less than --seq-end")

    working = frame
    if requested_start is not None:
        working = working[(working["pattern_seq"] >= requested_start) & (working["pattern_seq"] < requested_end)]
        if working.empty:
            raise ValueError("Requested sequence interval contains no events")

    if requested_region is not None:
        working = working[working[REGION_COLUMN] == requested_region]
        if working.empty:
            raise ValueError(f"Requested region {requested_region:#x} contains no events in the selected interval")

    if requested_start is not None and requested_region is not None:
        return requested_region, requested_start, requested_end

    scoped = working.copy()
    scoped["time_bin"] = scoped["pattern_seq"] // coarse_bin_size
    scoped["is_stlb_miss"] = (scoped["stlb_accessed"].astype(bool)) & (scoped["stlb_result"].astype(str) == "MISS")
    cells = (
        scoped.groupby([REGION_COLUMN, "time_bin"], observed=True)
        .agg(access_count=("pattern_seq", "size"), stlb_miss_count=("is_stlb_miss", "sum"))
        .reset_index()
    )
    if cells.empty:
        raise ValueError("No region/time cell is available")

    if int(cells["stlb_miss_count"].sum()) > 0:
        selected = cells.sort_values(["stlb_miss_count", "access_count", REGION_COLUMN, "time_bin"], ascending=[False, False, True, True]).iloc[0]
    else:
        selected = cells.sort_values(["access_count", REGION_COLUMN, "time_bin"], ascending=[False, True, True]).iloc[0]

    region = requested_region if requested_region is not None else int(selected[REGION_COLUMN])
    if requested_start is not None:
        return region, requested_start, requested_end
    time_bin = int(selected["time_bin"])
    return region, time_bin * coarse_bin_size, (time_bin + 1) * coarse_bin_size


def plot_region_time_heatmap(frame: pd.DataFrame, output_dir: Path, coarse_bin_size: int, selected: tuple[int, int, int], stream_kind: str,
                             sequence_label: str, stream_title: str, secondary_frame: pd.DataFrame | None = None,
                             secondary_selected: tuple[int, int, int] | None = None) -> None:
    views = [(frame, selected, sequence_label)]
    if secondary_frame is not None and secondary_selected is not None:
        views.append((secondary_frame, secondary_selected, "load_tlb_seq"))
    region_count = int(frame[REGION_COLUMN].nunique())
    fig = plt.figure(figsize=(12.0 * len(views), max(6.2, min(13.0, 3.8 + 0.12 * region_count))))
    outer = fig.add_gridspec(1, len(views), wspace=0.20)
    cmap = LinearSegmentedColormap.from_list("region_loads", ["#f7f7f7", "#bdd7e7", "#2171b5", "#08306b"])

    for column, (view_frame, view_selected, view_label) in enumerate(views):
        selected_region, selected_start, selected_end = view_selected
        work = view_frame.copy()
        work["time_bin"] = work["pattern_seq"] // coarse_bin_size
        grouped = work.groupby([REGION_COLUMN, "time_bin"], observed=True).size().rename("access_count").reset_index()
        regions = np.sort(grouped[REGION_COLUMN].unique())
        min_bin, max_bin = int(work["time_bin"].min()), int(work["time_bin"].max())
        bins = np.arange(min_bin, max_bin + 1, dtype=np.int64)
        matrix = grouped.pivot(index=REGION_COLUMN, columns="time_bin", values="access_count").reindex(
            index=regions, columns=bins, fill_value=0).fillna(0).to_numpy()
        stlb_miss = (work["stlb_accessed"].astype(bool) & work["stlb_result"].astype(str).eq("MISS")).groupby(
            work["time_bin"]).sum().reindex(bins, fill_value=0)
        stream_events = work.groupby("time_bin").size().reindex(bins, fill_value=0)
        if stream_kind == "dtlb_access":
            first_values = work["l1dtlb_result"].astype(str).eq("MISS").groupby(work["time_bin"]).sum().reindex(bins, fill_value=0)
            first_label, second_values, second_label = "L1 DTLB\nmisses", stlb_miss, "STLB\nmisses"
        elif stream_kind == "stlb_access":
            first_values, first_label, second_values, second_label = stream_events, "STLB\naccesses", stlb_miss, "STLB\nmisses"
        else:
            stlb_merge = work["stlb_merged"].astype(bool).groupby(work["time_bin"]).sum().reindex(bins, fill_value=0)
            first_values, first_label, second_values, second_label = stream_events, "STLB\nmisses", stlb_merge, "STLB-side\nmerges"

        # Keep the heatmap body and both time-series axes in the same grid
        # column.  Passing ``ax=ax`` to fig.colorbar would shrink only the
        # heatmap axis, making equal load_tlb_seq bins look horizontally
        # misaligned with the two shared-x miss plots below.
        grid = outer[column].subgridspec(
            3,
            2,
            height_ratios=[6.0, 1.0, 1.0],
            width_ratios=[30.0, 1.35],
            hspace=0.08,
            wspace=0.04,
        )
        ax = fig.add_subplot(grid[0, 0])
        colorbar_ax = fig.add_subplot(grid[0, 1])
        x_start, x_end = min_bin * coarse_bin_size, (max_bin + 1) * coarse_bin_size
        image = ax.imshow(np.log1p(matrix), aspect="auto", origin="lower", cmap=cmap, extent=[x_start, x_end, -0.5, len(regions) - 0.5])
        colorbar = fig.colorbar(image, cax=colorbar_ax)
        colorbar.set_label("log1p(event count)")
        ticks = np.unique(np.linspace(0, len(regions) - 1, min(24, len(regions)), dtype=int))
        ax.set_yticks(ticks)
        ax.set_yticklabels([f"0x{int(regions[pos]):x}" for pos in ticks])
        ax.set_ylabel(f"Active 2 MiB {ADDRESS_SPACE_ADJECTIVE} region ID")
        ax.set_title(f"{stream_title} by {view_label}")
        if selected_region in regions:
            row = int(np.where(regions == selected_region)[0][0])
            ax.add_patch(Rectangle((selected_start, row - 0.5), selected_end - selected_start, 1.0, fill=False,
                                   edgecolor=COLORS["selected"], linewidth=1.8))
        bin_edges = np.arange(min_bin, max_bin + 2, dtype=np.int64) * coarse_bin_size
        ax_first = fig.add_subplot(grid[1, 0], sharex=ax)
        ax_first.stairs(first_values.to_numpy(), bin_edges, baseline=0, fill=True, color=COLORS["stlb_hit"], alpha=0.3)
        ax_first.set_ylabel(first_label)
        ax_second = fig.add_subplot(grid[2, 0], sharex=ax)
        ax_second.stairs(second_values.to_numpy(), bin_edges, baseline=0, fill=True, color=COLORS["stlb_miss"], alpha=0.3)
        ax_second.set_ylabel(second_label)
        ax_second.set_xlabel(view_label)
        for small_ax in (ax_first, ax_second):
            small_ax.grid(axis="y", linestyle=":", alpha=0.35)
        plt.setp(ax.get_xticklabels(), visible=False)
        plt.setp(ax_first.get_xticklabels(), visible=False)
        # Hide the scientific-notation multiplier on the two label-suppressed
        # axes as well.  Leaving only ``1e7`` visible there is easily mistaken
        # for an axis endpoint; the bottom shared axis carries the complete
        # tick labels and its multiplier.
        ax.xaxis.get_offset_text().set_visible(False)
        ax_first.xaxis.get_offset_text().set_visible(False)
    save_figure(fig, output_dir, f"01_{ADDRESS_SPACE_ADJECTIVE}_region_time_heatmap")


def classify_translation_outcomes(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Partition recorded events into mutually exclusive translation outcomes.

    Merge outcomes take precedence over ordinary hit/miss outcomes.  The
    existing provenance can distinguish the DTLB side from the STLB side, but
    cannot split RQ merge, MSHR merge, and the DTLB pre-lookup completion case.
    Incomplete or internally inconsistent records fall into the final bucket.
    """
    complete = frame["completion_state"].astype(str).eq("COMPLETE")
    l1_merged = frame["l1dtlb_merged"].astype(bool)
    stlb_merged = frame["stlb_merged"].astype(bool)
    l1_result = frame["l1dtlb_result"].astype(str)
    stlb_accessed = frame["stlb_accessed"].astype(bool)
    stlb_result = frame["stlb_result"].astype(str)

    # This ordering implements the documented classification priority:
    # incomplete -> DTLB-side merge -> STLB-side merge -> ordinary outcomes.
    dtlb_side_merge = complete & l1_merged
    stlb_side_merge = complete & ~l1_merged & stlb_merged
    ordinary = complete & ~l1_merged & ~stlb_merged
    l1_hit = ordinary & l1_result.eq("HIT")
    l1_miss_stlb_hit = ordinary & l1_result.eq("MISS") & stlb_accessed & stlb_result.eq("HIT")
    stlb_miss = ordinary & l1_result.eq("MISS") & stlb_accessed & stlb_result.eq("MISS")
    accounted = l1_hit | l1_miss_stlb_hit | stlb_miss | dtlb_side_merge | stlb_side_merge
    other = ~accounted

    categories = {
        "L1 DTLB hit": l1_hit,
        "L1 miss + STLB hit": l1_miss_stlb_hit,
        "STLB miss": stlb_miss,
        "DTLB-side translation merge": dtlb_side_merge,
        "STLB-side translation merge": stlb_side_merge,
        "Other / incomplete": other,
    }
    membership = sum((mask.astype(np.uint8) for mask in categories.values()), start=np.zeros(len(frame), dtype=np.uint8))
    if not np.all(membership == 1):
        raise ValueError("Translation outcome categories are not a complete, mutually exclusive partition")
    return categories


def export_local_raster_records(local: pd.DataFrame, category_masks: dict[str, pd.Series], output_dir: Path, view_label: str) -> Path:
    """Export every source record represented by one local-raster coordinate view."""
    category = pd.Series(index=local.index, dtype="object")
    for label, mask in category_masks.items():
        category.loc[mask] = label
    if category.isna().any():
        raise ValueError("A local-raster record has no translation outcome category")

    # ``pattern_seq`` is an analysis-only alias of the selected coordinate.
    # Preserve every actual input column in its original order, then append the
    # exact mutually exclusive category used to draw the corresponding point.
    source_columns = [column for column in local.columns if column != "pattern_seq"]
    exported = local.loc[:, source_columns].copy()
    exported["raster_outcome_category"] = category
    safe_view_label = "".join(character if character.isalnum() else "_" for character in view_label).strip("_")
    output_path = output_dir / f"02_local_page_offset_raster_records_{safe_view_label}.csv"
    exported.to_csv(output_path, index=False)
    print(f"[DONE] Exported {len(exported):,} local-raster records to {output_path}")
    return output_path


def plot_local_raster(frame: pd.DataFrame, output_dir: Path, page_size: int, region_size: int, selected: tuple[int, int, int], sequence_label: str,
                      stream_title: str, secondary_frame: pd.DataFrame | None = None,
                      secondary_selected: tuple[int, int, int] | None = None) -> dict[str, int]:
    views = [(frame, selected, sequence_label)]
    if secondary_frame is not None and secondary_selected is not None:
        views.append((secondary_frame, secondary_selected, "load_tlb_seq"))
    # Each coordinate view occupies a 4x2 block on one large page: one combined
    # panel, six mutually exclusive outcome panels, and one unused slot.
    fig, axes = plt.subplots(4, 2 * len(views), figsize=(20.0 * len(views), 20.0), squeeze=False)
    pages_per_region = region_size // page_size
    primary_metrics: dict[str, int] = {}

    for view_index, (view_frame, view_selected, view_label) in enumerate(views):
        region, seq_start, seq_end = view_selected
        local = view_frame[(view_frame[REGION_COLUMN] == region) & (view_frame["pattern_seq"] >= seq_start)
                           & (view_frame["pattern_seq"] < seq_end)].copy()
        if local.empty:
            raise ValueError("Selected local raster window is empty")
        category_masks = classify_translation_outcomes(local)
        export_local_raster_records(local, category_masks, output_dir, view_label)
        l1_hit = category_masks["L1 DTLB hit"]
        stlb_hit = category_masks["L1 miss + STLB hit"]
        stlb_miss = category_masks["STLB miss"]
        raw_stlb_miss = local["stlb_accessed"].astype(bool) & local["stlb_result"].astype(str).eq("MISS")
        metrics = {"total_demand_loads": len(local), "unique_pages": int(local[PAGE_NUMBER_COLUMN].nunique()),
                   "l1dtlb_misses": int(local["l1dtlb_result"].astype(str).eq("MISS").sum()),
                   "stlb_accesses": int(local["stlb_accessed"].sum()), "stlb_misses": int(raw_stlb_miss.sum())}
        if view_index == 0:
            primary_metrics = metrics
        box = "\n".join(
            [
                f"coordinate: {view_label}",
                f"region: 0x{region:x}",
                f"seq: [{seq_start:,}, {seq_end:,})",
                f"stream events: {metrics['total_demand_loads']:,}",
                f"unique {PAGE_ACRONYM}s: {metrics['unique_pages']:,}",
            ]
            + [f"{label}: {int(mask.sum()):,}" for label, mask in category_masks.items()]
        )
        categories = [
            ("L1 DTLB hit", l1_hit, {"s": 5, "c": COLORS["l1_hit"], "alpha": 0.45, "linewidths": 0}),
            ("L1 miss + STLB hit", stlb_hit, {"s": 10, "c": COLORS["stlb_hit"], "alpha": 0.75, "linewidths": 0}),
            ("STLB miss", stlb_miss, {"s": 13, "c": COLORS["stlb_miss"], "alpha": 0.9, "linewidths": 0}),
            ("DTLB-side translation merge", category_masks["DTLB-side translation merge"],
             {"s": 8, "c": COLORS["dtlb_merge"], "alpha": 0.65, "linewidths": 0}),
            ("STLB-side translation merge", category_masks["STLB-side translation merge"],
             {"s": 9, "c": COLORS["stlb_merge"], "alpha": 0.7, "linewidths": 0}),
            ("Other / incomplete", category_masks["Other / incomplete"],
             {"s": 7, "c": COLORS["other"], "alpha": 0.65, "linewidths": 0}),
        ]
        panels = [("All categories", categories)] + [(label, [(label, mask, style)]) for label, mask, style in categories]
        view_axes = axes[:, 2 * view_index:2 * view_index + 2].flat
        for panel_index, (ax, (panel_title, panel_categories)) in enumerate(zip(view_axes, panels)):
            for label, mask, style in panel_categories:
                if mask.any():
                    ax.scatter(local.loc[mask, "pattern_seq"], local.loc[mask, REGION_OFFSET_COLUMN],
                               label=f"{label} ({int(mask.sum()):,})", **style)
                elif len(panel_categories) == 1:
                    ax.text(0.5, 0.5, f"No {label} events in this window", transform=ax.transAxes, ha="center", va="center", fontsize=11)
            ax.set_ylim(-1, pages_per_region)
            ax.set_xlim(seq_start, seq_end)
            ax.set_xlabel(view_label)
            ax.set_ylabel(f"4 KiB page offset inside selected 2 MiB {ADDRESS_SPACE_ADJECTIVE} region")
            ax.set_title(f"{panel_title}\nregion 0x{region:x}, [{seq_start:,}, {seq_end:,})")
            ax.grid(linestyle=":", alpha=0.25)
            if any(mask.any() for _, mask, _ in panel_categories):
                ax.legend(loc="upper left", frameon=True, fontsize=8)
            if panel_index == 0:
                ax.text(0.99, 0.98, box, transform=ax.transAxes, va="top", ha="right", fontsize=8,
                        bbox={"facecolor": "white", "edgecolor": "#888888", "alpha": 0.9})
        for unused_ax in list(view_axes)[len(panels):]:
            unused_ax.axis("off")
    fig.suptitle(f"Local {stream_title} {PAGE_ACRONYM} pattern", fontsize=16)
    fig.subplots_adjust(hspace=0.32, wspace=0.22, top=0.94)
    save_figure(fig, output_dir, "02_local_page_offset_raster")
    return primary_metrics


def draw_delta_distribution(ax: plt.Axes, deltas: np.ndarray, delta_limit: int, title: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    counts = bucket_deltas(deltas, delta_limit, include_zero=False)
    ratios = counts / counts.sum() if counts.sum() else counts.astype(float)
    labels = delta_bucket_labels(delta_limit, include_zero=False)
    x = np.arange(len(labels))
    ax.bar(x, ratios * 100.0, color=COLORS["bar"], width=0.82)

    if delta_limit <= 16:
        tick_positions = x
    else:
        tick_positions = np.array(
            [idx for idx, label in enumerate(labels) if idx in (0, len(labels) - 1) or (label not in (f"<-{delta_limit}", f">+{delta_limit}") and
                                                                                         ((int(label) % 8 == 0 and abs(int(label)) < delta_limit) or
                                                                                          int(label) in (-1, 1)))],
            dtype=np.int64,
        )
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([labels[idx] for idx in tick_positions], rotation=55, ha="right", fontsize=7)
    ax.set_ylabel("Share of compressed page transitions (%)")
    ax.set_xlabel(f"Delta {PAGE_ACRONYM}")
    ax.set_title(title)
    ax.grid(axis="y", linestyle=":", alpha=0.35)
    return counts, ratios, labels


def plot_global_delta(frame: pd.DataFrame, output_dir: Path, delta_limit: int, wide_delta_limit: int) -> dict[str, float | int | list[int]]:
    vpns = frame[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)
    deltas = global_page_deltas(vpns)

    fig, axes = plt.subplots(2, 1, figsize=(12.0, 9.2))
    counts, ratios, labels = draw_delta_distribution(
        axes[0], deltas, delta_limit, f"Global page-transition delta after removing consecutive repeated {PAGE_ACRONYM}s"
    )
    wide_counts, wide_ratios, wide_labels = draw_delta_distribution(
        axes[1], deltas, wide_delta_limit, f"Expanded global page-transition delta within +/-{wide_delta_limit}"
    )
    fig.subplots_adjust(hspace=0.48)
    save_figure(fig, output_dir, "03_global_page_delta")

    adjacent_pairs = max(0, len(vpns) - 1)
    same_page_ratio = float(np.sum(vpns[1:] == vpns[:-1]) / adjacent_pairs) if adjacent_pairs else 0.0
    abs_delta = np.abs(deltas)
    top1, top1_coverage = ranked_delta_coverage(deltas, 1)
    top2, top2_coverage = ranked_delta_coverage(deltas, 2)
    metrics: dict[str, float | int | list[int]] = {
        "total_raw_demand_loads": len(vpns),
        "total_page_transitions": len(deltas),
        "same_page_continuation_ratio": same_page_ratio,
        "p_abs_delta_eq_1": float(np.mean(abs_delta == 1)) if len(deltas) else 0.0,
        "p_abs_delta_le_4": float(np.mean(abs_delta <= 4)) if len(deltas) else 0.0,
        "p_abs_delta_le_16": float(np.mean(abs_delta <= 16)) if len(deltas) else 0.0,
        "p_abs_delta_gt_16": float(np.mean(abs_delta > 16)) if len(deltas) else 0.0,
        "global_top1_deltas": top1,
        "global_top1_coverage": top1_coverage,
        "global_top2_deltas": top2,
        "global_top2_coverage": top2_coverage,
    }

    rows = [
        {"kind": "delta_bucket", "name": label, "count": int(count), "ratio": float(ratio), "value": ""}
        for label, count, ratio in zip(labels, counts, ratios)
    ]
    rows.extend(
        {"kind": "delta_bucket_wide", "name": label, "count": int(count), "ratio": float(ratio), "value": ""}
        for label, count, ratio in zip(wide_labels, wide_counts, wide_ratios)
    )
    rows.extend({"kind": "metric", "name": key, "count": "", "ratio": "", "value": str(value)} for key, value in metrics.items())
    pd.DataFrame(rows).to_csv(output_dir / "03_global_page_delta_summary.csv", index=False)
    return metrics


def plot_per_pc(frame: pd.DataFrame, output_dir: Path, top_pcs: int, rank_by: str, delta_limit: int) -> tuple[float, float]:
    work = frame.copy()
    work["is_stlb_miss"] = work["stlb_accessed"].astype(bool) & (work["stlb_result"].astype(str) == "MISS")
    ranking = (
        work.groupby("pc", observed=True)
        .agg(
            load_count=("pattern_seq", "size"),
            stlb_access=("stlb_accessed", "sum"),
            stlb_miss=("is_stlb_miss", "sum"),
        )
        .reset_index()
    )
    rank_column = {"stlb_miss": "stlb_miss", "stlb_access": "stlb_access", "load_count": "load_count"}[rank_by]
    eligible = ranking[ranking["load_count"] >= 32].sort_values([rank_column, "load_count", "pc"], ascending=[False, False, True]).head(top_pcs)
    total_raw_stlb_miss_count = int(work["is_stlb_miss"].sum())
    labels = delta_bucket_labels(delta_limit, include_zero=True)
    def build_section(deduplicate: bool) -> tuple[list[np.ndarray], list[dict[str, object]], float, float]:
        matrix_rows: list[np.ndarray] = []
        csv_rows: list[dict[str, object]] = []
        weighted_top1_numerator = 0.0
        weighted_top2_numerator = 0.0
        weighted_denominator = 0
        sequence_kind = f"deduplicated_consecutive_{PAGE_TOKEN}" if deduplicate else "raw"
        for pc in eligible["pc"].astype("uint64"):
            raw_rows = work[work["pc"] == pc].sort_values("pattern_seq", kind="stable")
            raw_stlb_miss_count = int(raw_rows["is_stlb_miss"].sum())
            rows = raw_rows
            if deduplicate and not rows.empty:
                vpns = rows[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)
                rows = rows.iloc[np.flatnonzero(np.r_[True, vpns[1:] != vpns[:-1]])]
            deltas = per_pc_deltas(rows[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64))
            counts = bucket_deltas(deltas, delta_limit, include_zero=True)
            matrix_rows.append(counts / counts.sum() if counts.sum() else counts.astype(float))
            top1, top1_coverage = ranked_delta_coverage(deltas, 1)
            top2, top2_coverage = ranked_delta_coverage(deltas, 2)
            valid_count = len(deltas)
            weighted_top1_numerator += valid_count * top1_coverage
            weighted_top2_numerator += valid_count * top2_coverage
            weighted_denominator += valid_count
            csv_rows.append({
                "sequence_kind": sequence_kind,
                "pc": f"0x{int(pc):x}",
                "load_count": len(rows),
                "raw_load_count": len(raw_rows),
                "valid_delta_count": valid_count,
                f"unique_{PAGE_TOKEN}_count": int(rows[PAGE_NUMBER_COLUMN].nunique()),
                "l1dtlb_miss_count": int(rows["l1dtlb_result"].astype(str).eq("MISS").sum()),
                "stlb_access_count": int(rows["stlb_accessed"].sum()),
                "stlb_miss_count": int(rows["is_stlb_miss"].sum()),
                "top1_delta": top1[0] if top1 else "",
                "top1_coverage": top1_coverage,
                "top2_deltas": ";".join(str(value) for value in top2),
                "top2_coverage": top2_coverage,
                "raw_stlb_miss_share_of_all_pct": (
                    100.0 * raw_stlb_miss_count / total_raw_stlb_miss_count if total_raw_stlb_miss_count else np.nan
                ),
            })
        weighted_top1 = weighted_top1_numerator / weighted_denominator if weighted_denominator else 0.0
        weighted_top2 = weighted_top2_numerator / weighted_denominator if weighted_denominator else 0.0
        return matrix_rows, csv_rows, weighted_top1, weighted_top2

    raw_matrix, raw_rows, weighted_top1, weighted_top2 = build_section(False)
    dedup_matrix, dedup_rows, _, _ = build_section(True)
    csv_path = output_dir / "04_per_pc_topk.csv"
    pd.DataFrame(raw_rows).to_csv(csv_path, index=False)
    with csv_path.open("a", encoding="utf-8", newline="") as output:
        output.write("\n")
        pd.DataFrame(dedup_rows).to_csv(output, index=False)

    fig_height = max(3.5, min(12.0, 1.8 + 0.32 * max(1, len(raw_rows))))
    fig, axes = plt.subplots(1, 2, figsize=(23.0, fig_height), squeeze=False)
    for ax, matrix_rows, section_rows, title, xlabel in [
        (axes[0, 0], raw_matrix, raw_rows, f"Raw per-PC {PAGE_ACRONYM} sequence", f"Per-PC Delta {PAGE_ACRONYM} (zero retained)"),
        (axes[0, 1], dedup_matrix, dedup_rows, f"Per-PC sequence after removing consecutive repeated {PAGE_ACRONYM}s", f"Per-PC Delta {PAGE_ACRONYM}"),
    ]:
        if matrix_rows:
            matrix = np.vstack(matrix_rows)
            image = ax.imshow(matrix * 100.0, aspect="auto", cmap="YlGnBu", vmin=0.0,
                              vmax=max(1.0, float(np.percentile(matrix * 100.0, 98))))
            colorbar = fig.colorbar(image, ax=ax, pad=0.01)
            colorbar.set_label("Per-PC delta share (%)")
            ax.set_yticks(np.arange(len(section_rows)))
            ax.set_yticklabels([str(row["pc"]) for row in section_rows], fontsize=8)
            ax.set_xticks(np.arange(len(labels)))
            ax.set_xticklabels(labels, rotation=55, ha="right", fontsize=7)
        else:
            ax.text(0.5, 0.5, "No PC has at least 32 dynamic load samples", ha="center", va="center", transform=ax.transAxes)
            ax.set_xticks([])
            ax.set_yticks([])
        ax.set_xlabel(xlabel)
        ax.set_ylabel(f"Top PCs by raw {rank_by}")
        ax.set_title(title)
    fig.suptitle(f"Per-static-load-PC {PAGE_ACRONYM} delta distribution", fontsize=14)
    fig.subplots_adjust(wspace=0.18, top=0.90)
    save_figure(fig, output_dir, "04_per_pc_delta_heatmap")
    return weighted_top1, weighted_top2


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze an ROI real demand-data TLB request stream.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--stream-kind", choices=sorted(STREAM_SPECS), default="dtlb_access")
    parser.add_argument("--address-space", choices=["virtual", "physical"], default="virtual")
    parser.add_argument("--coarse-bin-size", type=int, default=50000)
    parser.add_argument("--region-id", type=parse_integer)
    parser.add_argument("--seq-start", type=int)
    parser.add_argument("--seq-end", type=int)
    parser.add_argument("--top-pcs", type=int, default=32)
    parser.add_argument("--pc-rank-by", choices=["stlb_miss", "stlb_access", "load_count"], default="stlb_miss")
    parser.add_argument("--delta-limit", type=int, default=16)
    parser.add_argument("--wide-delta-limit", type=int, default=64)
    only_group = parser.add_mutually_exclusive_group()
    only_group.add_argument("--heatmap-only", action="store_true",
                            help="Only regenerate 01_*_region_time_heatmap.{pdf,png}")
    only_group.add_argument("--local-raster-only", action="store_true",
                            help="Only regenerate 02_local_page_offset_raster.{pdf,png} and its selected-window CSV")
    only_group.add_argument("--per-pc-only", action="store_true",
                            help="Only regenerate 04_per_pc_delta_heatmap.{pdf,png} and 04_per_pc_topk.csv")
    args = parser.parse_args()
    if args.coarse_bin_size <= 0 or args.top_pcs <= 0 or args.delta_limit <= 0 or args.wide_delta_limit <= 0:
        parser.error("coarse-bin-size, top-pcs, delta-limit, and wide-delta-limit must be positive")
    if args.wide_delta_limit < args.delta_limit:
        parser.error("wide-delta-limit must be greater than or equal to delta-limit")

    configure_address_space(args.address_space)
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    page_size = int(metadata["page_size"])
    region_size = int(metadata["region_size"])
    stream_spec = STREAM_SPECS[args.stream_kind]
    sequence_column = str(stream_spec["sequence_column"])
    sequence_label = str(stream_spec["sequence_label"])
    stream_title = str(stream_spec["title"])
    input_columns = set(pd.read_csv(args.input, nrows=0).columns)
    input_dtypes = {name: dtype for name, dtype in DTYPES.items() if name in input_columns}
    frame = pd.read_csv(args.input, dtype=input_dtypes)
    if frame.empty:
        raise SystemExit("[ERROR] Input pattern CSV is empty")
    required_address_columns = {PAGE_NUMBER_COLUMN, REGION_COLUMN, REGION_OFFSET_COLUMN}
    missing_address_columns = sorted(required_address_columns - set(frame.columns))
    if missing_address_columns:
        raise SystemExit(f"[ERROR] Missing {args.address_space} address columns in {args.input}: {', '.join(missing_address_columns)}")
    if args.address_space == "physical":
        if "physical_address_valid" not in frame.columns:
            raise SystemExit(f"[ERROR] Missing physical_address_valid in {args.input}")
        unavailable = int((frame["physical_address_valid"] == 0).sum())
        if unavailable:
            print(f"[INFO] Physical analysis excludes {unavailable:,} incomplete events without a returned translation")
        frame = frame[frame["physical_address_valid"].astype(bool)].copy()
        if frame.empty:
            raise SystemExit("[ERROR] No event has a valid physical address")
    if sequence_column not in frame.columns:
        raise SystemExit(f"[ERROR] Missing sequence column {sequence_column} in {args.input}")
    frame["pattern_seq"] = frame[sequence_column].astype("uint64")
    frame = frame.sort_values(["cpu", "pattern_seq"], kind="stable").reset_index(drop=True)
    for cpu, rows in frame.groupby("cpu", sort=True):
        actual = rows["pattern_seq"].to_numpy(dtype=np.uint64)
        expected = np.arange(len(rows), dtype=np.uint64)
        if args.address_space == "virtual" and not np.array_equal(actual, expected):
            raise SystemExit(f"[ERROR] Core {cpu}: {sequence_column} is not contiguous from zero")
        if args.address_space == "physical" and (len(actual) > 1 and np.any(actual[1:] <= actual[:-1])):
            raise SystemExit(f"[ERROR] Core {cpu}: {sequence_column} is not strictly increasing")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.per_pc_only:
        plot_per_pc(frame, args.output_dir, args.top_pcs, args.pc_rank_by, args.delta_limit)
        print(f"[DONE] Regenerated {args.output_dir / '04_per_pc_topk.csv'}")
        return

    dual_load_sequence = args.stream_kind != "dtlb_access"
    secondary_frame = None
    secondary_selected = None
    if dual_load_sequence:
        secondary_frame = frame.copy()
        secondary_frame["pattern_seq"] = secondary_frame["load_tlb_seq"].astype("uint64")
        secondary_frame = secondary_frame.sort_values(["cpu", "pattern_seq"], kind="stable").reset_index(drop=True)

    selected = choose_local_window(frame, args.coarse_bin_size, args.region_id, args.seq_start, args.seq_end)
    print(f"[INFO] Selected local window: region=0x{selected[0]:x}, seq=[{selected[1]}, {selected[2]})")
    if secondary_frame is not None:
        secondary_selected = choose_local_window(secondary_frame, args.coarse_bin_size, args.region_id, None, None)
        print(f"[INFO] Selected load_tlb_seq window: region=0x{secondary_selected[0]:x}, "
              f"seq=[{secondary_selected[1]}, {secondary_selected[2]})")
    if args.heatmap_only:
        plot_region_time_heatmap(frame, args.output_dir, args.coarse_bin_size, selected, args.stream_kind, sequence_label, stream_title,
                                 secondary_frame, secondary_selected)
        print(f"[DONE] Regenerated 01_{ADDRESS_SPACE_ADJECTIVE}_region_time_heatmap.pdf in {args.output_dir}")
        return
    if args.local_raster_only:
        plot_local_raster(frame, args.output_dir, page_size, region_size, selected, sequence_label, stream_title,
                          secondary_frame, secondary_selected)
        print(f"[DONE] Regenerated {args.output_dir / '02_local_page_offset_raster.pdf'}")
        return

    plot_vpn_trajectories(frame, args.output_dir, sequence_label, stream_title, dual_load_sequence)
    plot_region_time_heatmap(frame, args.output_dir, args.coarse_bin_size, selected, args.stream_kind, sequence_label, stream_title,
                             secondary_frame, secondary_selected)
    local_metrics = plot_local_raster(frame, args.output_dir, page_size, region_size, selected, sequence_label, stream_title,
                                      secondary_frame, secondary_selected)
    write_raw_global_delta_topk(frame, args.output_dir)
    global_metrics = plot_global_delta(frame, args.output_dir, args.delta_limit, args.wide_delta_limit)
    weighted_top1, weighted_top2 = plot_per_pc(frame, args.output_dir, args.top_pcs, args.pc_rank_by, args.delta_limit)

    completed = int((frame["completion_state"].astype(str) == "COMPLETE").sum())
    incomplete = len(frame) - completed
    l1_hits = int((frame["l1dtlb_result"].astype(str) == "HIT").sum())
    l1_misses = int((frame["l1dtlb_result"].astype(str) == "MISS").sum())
    stlb_accesses = int(frame["stlb_accessed"].sum())
    stlb_hits = int((frame["stlb_result"].astype(str) == "HIT").sum())
    stlb_misses = int((frame["stlb_result"].astype(str) == "MISS").sum())
    merge_count = int((frame["l1dtlb_merged"].astype(bool) | frame["stlb_merged"].astype(bool)).sum())

    lines = [
        f"stream kind: {args.stream_kind}",
        f"address space: {args.address_space}",
        f"sequence column: {sequence_column}",
        f"total completed stream events: {completed}",
        f"incomplete events: {incomplete}",
        f"unique {PAGE_ACRONYM}s: {frame[PAGE_NUMBER_COLUMN].nunique()}",
        f"unique 2 MiB {ADDRESS_SPACE_ADJECTIVE} regions: {frame[REGION_COLUMN].nunique()}",
        f"L1 DTLB hit count/rate: {l1_hits} / {ratio(l1_hits, l1_hits + l1_misses):.8f}",
        f"L1 DTLB miss count/rate: {l1_misses} / {ratio(l1_misses, l1_hits + l1_misses):.8f}",
        f"STLB access count: {stlb_accesses}",
        f"STLB hit count/rate: {stlb_hits} / {ratio(stlb_hits, stlb_accesses):.8f}",
        f"STLB miss count/rate: {stlb_misses} / {ratio(stlb_misses, stlb_accesses):.8f}",
        f"translation merge count: {merge_count}",
        f"same-page continuation ratio: {global_metrics['same_page_continuation_ratio']:.8f}",
        f"page-transition count: {global_metrics['total_page_transitions']}",
        f"P(|Delta{PAGE_ACRONYM}| = 1): {global_metrics['p_abs_delta_eq_1']:.8f}",
        f"P(|Delta{PAGE_ACRONYM}| <= 4): {global_metrics['p_abs_delta_le_4']:.8f}",
        f"P(|Delta{PAGE_ACRONYM}| <= 16): {global_metrics['p_abs_delta_le_16']:.8f}",
        f"P(|Delta{PAGE_ACRONYM}| > 16): {global_metrics['p_abs_delta_gt_16']:.8f}",
        f"global Top-1 transition-delta coverage: {global_metrics['global_top1_coverage']:.8f}",
        f"global Top-2 transition-delta coverage: {global_metrics['global_top2_coverage']:.8f}",
        f"weighted per-PC Top-1 delta coverage: {weighted_top1:.8f}",
        f"weighted per-PC Top-2 delta coverage: {weighted_top2:.8f}",
        f"auto-selected region: 0x{selected[0]:x}",
        f"auto-selected sequence interval: [{selected[1]}, {selected[2]})",
        f"selected-window stream events: {local_metrics['total_demand_loads']}",
    ]
    (args.output_dir / "analysis_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(f"[SUMMARY] {line}" for line in lines))


if __name__ == "__main__":
    main()
