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
    "demand": "#2878b5",
    "prefetch": "#e45756",
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

COMPACT_DROP_FIELDS = {
    "vberti_prefetch_seq",
    "prefetch_issue_cycle",
    "prefetch_trigger_instr_id",
    "prefetch_trigger_pc",
    "prefetch_trigger_va",
    "pa",
    "ppn",
    "physical_region_2m",
    "page_offset_in_physical_region",
    "physical_address_valid",
}


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


def real_data_demand_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the real-data-demand subsequence, preserving legacy demand-only inputs."""
    if "event_type" not in frame.columns:
        return frame
    return frame[frame["event_type"].astype(str).eq("DATA_DEMAND")].copy()


def write_raw_global_delta_topk(frame: pd.DataFrame, output_dir: Path, k: int = 20) -> None:
    """Write raw real-data-demand Top-K deltas, including delta-zero pairs."""
    demand = real_data_demand_frame(frame)
    vpns = demand[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)
    deltas = np.diff(vpns)
    total = len(deltas)
    ranked = sorted(Counter(int(value) for value in deltas).items(), key=lambda item: (-item[1], item[0]))[:k]
    rows = [
        {"event_scope": "DATA_DEMAND", "rank": rank, "delta": delta, "count": count, "ratio": count / total if total else 0.0}
        for rank, (delta, count) in enumerate(ranked, start=1)
    ]
    pd.DataFrame(rows, columns=["event_scope", "rank", "delta", "count", "ratio"]).to_csv(
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
    event_types: np.ndarray | None = None,
) -> None:
    column_count = 2 if secondary_x is not None else 1
    fig, axes = plt.subplots(1, column_count, figsize=(12.0 * column_count, 4.8), squeeze=False)
    views = [(x, xlabel, f"{title} ({xlabel})")]
    if secondary_x is not None:
        views.append((secondary_x, secondary_xlabel, f"{title} ({secondary_xlabel})"))
    for ax, (view_x, view_xlabel, view_title) in zip(axes.flat, views):
        if event_types is None:
            ax.scatter(view_x, y, s=0.25, color=COLORS["bar"], alpha=0.7, linewidths=0, rasterized=True)
        else:
            demand = event_types == "DATA_DEMAND"
            prefetch = event_types == "VBERTI_CP_PREFETCH"
            ax.scatter(view_x[demand], y[demand], s=0.35, color=COLORS["demand"], alpha=0.65, linewidths=0,
                       label=f"Real data demand ({int(demand.sum()):,})", rasterized=True)
            ax.scatter(view_x[prefetch], y[prefetch], s=0.55, color=COLORS["prefetch"], alpha=0.72, linewidths=0,
                       label=f"vBerti cross-page prefetch ({int(prefetch.sum()):,})", rasterized=True)
            ax.legend(loc="best", fontsize=8, markerscale=5)
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
    raw_event_types = frame["event_type"].astype(str).to_numpy() if "event_type" in frame.columns else None

    save_trajectory(
        raw_seq,
        raw_vpns,
        output_dir,
        f"05a_raw_{PAGE_TOKEN}_trajectory",
        sequence_label,
        f"Raw {ADDRESS_SPACE_ADJECTIVE} page number",
        f"Raw ROI {stream_title} {PAGE_ACRONYM} trajectory",
        secondary_x=raw_load_seq,
        event_types=raw_event_types,
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
        event_types=raw_event_types,
    )

    transition_frame = deduplicate_vpn_frame(frame)
    transition_frame.to_csv(output_dir / f"05_deduplicated_{PAGE_TOKEN}_access_stream.csv", index=False)
    transition_vpns = transition_frame[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)
    transition_seq = transition_frame["page_transition_seq"].to_numpy(dtype=np.int64)
    transition_first_touch = transition_frame[f"first_touch_{PAGE_TOKEN}_id"].to_numpy(dtype=np.int64)
    transition_load_seq = transition_frame["load_tlb_seq"].to_numpy(dtype=np.int64) if dual_load_sequence else None
    transition_event_types = transition_frame["event_type"].astype(str).to_numpy() if "event_type" in transition_frame.columns else None
    save_trajectory(
        transition_seq,
        transition_vpns,
        output_dir,
        f"05c_deduplicated_{PAGE_TOKEN}_trajectory",
        f"{stream_title.lower().replace(' ', '_')}_page_transition_seq",
        f"{ADDRESS_SPACE_ADJECTIVE.title()} page number",
        f"{PAGE_ACRONYM} trajectory after removing consecutive repeated {PAGE_ACRONYM}s",
        secondary_x=transition_load_seq,
        event_types=transition_event_types,
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
        event_types=transition_event_types,
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
    # For the unified observer stream, show the aggregate, real-demand, and
    # cross-page-vBerti views side-by-side.  They deliberately use the same
    # global_seq extent, region rows, and colour scale, so visual differences
    # are attributable to origin rather than to a rescaled coordinate system.
    base_views = [(frame, selected, sequence_label)]
    if secondary_frame is not None and secondary_selected is not None:
        base_views.append((secondary_frame, secondary_selected, "load_tlb_seq"))
    has_event_types = "event_type" in frame.columns
    origin_views: list[tuple[str, str | None]]
    if has_event_types:
        origin_views = [
            ("All recorded events", None),
            ("Real data demand", "DATA_DEMAND"),
            ("vBerti cross-page prefetch", "VBERTI_CP_PREFETCH"),
            ("Real data demand: L1 DTLB miss + STLB miss", "DATA_DEMAND_DTLB_STLB_MISS"),
        ]
    else:
        origin_views = [(stream_title, None)]

    region_count = int(frame[REGION_COLUMN].nunique())
    column_count = len(base_views) * len(origin_views)
    fig = plt.figure(figsize=(12.0 * column_count, max(6.2, min(13.0, 3.8 + 0.12 * region_count))))
    outer = fig.add_gridspec(1, column_count, wspace=0.20)
    cmap = LinearSegmentedColormap.from_list("region_loads", ["#f7f7f7", "#bdd7e7", "#2171b5", "#08306b"])
    stream_label = {
        "dtlb_access": "L1 DTLB access",
        "stlb_access": "STLB access",
        "stlb_miss": "STLB miss",
    }[stream_kind]

    column = 0
    for view_frame, view_selected, view_label in base_views:
        selected_region, selected_start, selected_end = view_selected
        base_work = view_frame.copy()
        base_work["time_bin"] = base_work["pattern_seq"] // coarse_bin_size
        regions = np.sort(base_work[REGION_COLUMN].unique())
        min_bin, max_bin = int(base_work["time_bin"].min()), int(base_work["time_bin"].max())
        bins = np.arange(min_bin, max_bin + 1, dtype=np.int64)
        grouped_all = base_work.groupby([REGION_COLUMN, "time_bin"], observed=True).size().rename("access_count").reset_index()
        all_matrix = grouped_all.pivot(index=REGION_COLUMN, columns="time_bin", values="access_count").reindex(
            index=regions, columns=bins, fill_value=0).fillna(0).to_numpy()
        color_max = max(1.0, float(np.log1p(all_matrix).max()))
        x_start, x_end = min_bin * coarse_bin_size, (max_bin + 1) * coarse_bin_size
        bin_edges = np.arange(min_bin, max_bin + 2, dtype=np.int64) * coarse_bin_size

        for origin_title, event_type in origin_views:
            if event_type is None:
                work = base_work
            elif event_type == "DATA_DEMAND_DTLB_STLB_MISS":
                # Match the raster's ordinary ``STLB miss`` category: the
                # event is a real data demand, reaches both levels, misses in
                # both, and is not a request/MSHR merge at either level.
                dual_miss = (
                    base_work["event_type"].astype(str).eq("DATA_DEMAND")
                    & base_work["completion_state"].astype(str).eq("COMPLETE")
                    & ~base_work["l1dtlb_merged"].astype(bool)
                    & ~base_work["stlb_merged"].astype(bool)
                    & base_work["l1dtlb_result"].astype(str).eq("MISS")
                    & base_work["stlb_accessed"].astype(bool)
                    & base_work["stlb_result"].astype(str).eq("MISS")
                )
                work = base_work[dual_miss]
            else:
                work = base_work[base_work["event_type"].astype(str).eq(event_type)]
            grouped = work.groupby([REGION_COLUMN, "time_bin"], observed=True).size().rename("access_count").reset_index()
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
            # column.  Each origin view has an identical x/y coordinate system;
            # the shared colour range makes their density directly comparable.
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
            image = ax.imshow(np.log1p(matrix), aspect="auto", origin="lower", cmap=cmap, vmin=0.0, vmax=color_max,
                              extent=[x_start, x_end, -0.5, len(regions) - 0.5])
            colorbar = fig.colorbar(image, cax=colorbar_ax)
            colorbar.set_label("log1p(event count)")
            ticks = np.unique(np.linspace(0, len(regions) - 1, min(24, len(regions)), dtype=int))
            ax.set_yticks(ticks)
            ax.set_yticklabels([f"0x{int(regions[pos]):x}" for pos in ticks])
            ax.set_ylabel(f"Active 2 MiB {ADDRESS_SPACE_ADJECTIVE} region ID")
            ax.set_title(f"{origin_title}: {stream_label} by {view_label}")
            if selected_region in regions:
                row = int(np.where(regions == selected_region)[0][0])
                ax.add_patch(Rectangle((selected_start, row - 0.5), selected_end - selected_start, 1.0, fill=False,
                                       edgecolor=COLORS["selected"], linewidth=1.8))
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
            # Hide the scientific-notation multiplier on the two
            # label-suppressed axes.  The bottom axis carries it once.
            ax.xaxis.get_offset_text().set_visible(False)
            ax_first.xaxis.get_offset_text().set_visible(False)
            column += 1
    if has_event_types:
        fig.suptitle(f"{stream_title}: origin-resolved region/time pattern on common {sequence_label}", fontsize=15)
        fig.subplots_adjust(top=0.92)
    save_figure(fig, output_dir, f"01_{ADDRESS_SPACE_ADJECTIVE}_region_time_heatmap")


def classify_translation_outcomes(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Partition recorded events into mutually exclusive translation outcomes.

    Merge outcomes take precedence over ordinary hit/miss outcomes. The raster
    intentionally keeps one aggregate panel per TLB level; the exported CSV's
    dtlb_merge_detail/stlb_merge_detail fields provide the finer RQ/MSHR and
    target-origin split. Incomplete or inconsistent records use the last bucket.
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
    # New streams already carry the native category; verify and preserve it.
    # Append the derived category only for legacy streams that predate it.
    source_columns = [column for column in local.columns if column != "pattern_seq"]
    exported = local.loc[:, source_columns].copy()
    if "raster_outcome_category" in exported.columns:
        native = exported["raster_outcome_category"].astype(str)
        if not native.equals(category.astype(str)):
            raise ValueError("Native raster_outcome_category disagrees with the lifecycle fields")
    else:
        exported["raster_outcome_category"] = category
    safe_view_label = "".join(character if character.isalnum() else "_" for character in view_label).strip("_")
    output_path = output_dir / f"02_local_page_offset_raster_records_{safe_view_label}.csv"
    exported.to_csv(output_path, index=False)
    compact_path = output_path.with_name(f"{output_path.stem}_compact{output_path.suffix}")
    compact_columns = [column for column in exported.columns if column not in COMPACT_DROP_FIELDS]
    exported.loc[:, compact_columns].to_csv(compact_path, index=False)
    print(
        f"[DONE] Exported {len(exported):,} local-raster records to {output_path}\n"
        f"[DONE] Exported compact local-raster records to {compact_path}"
    )
    return output_path


def plot_local_raster(frame: pd.DataFrame, output_dir: Path, page_size: int, region_size: int, selected: tuple[int, int, int], sequence_label: str,
                      stream_title: str, secondary_frame: pd.DataFrame | None = None,
                      secondary_selected: tuple[int, int, int] | None = None) -> dict[str, int]:
    views = [(frame, selected, sequence_label)]
    if secondary_frame is not None and secondary_selected is not None:
        views.append((secondary_frame, secondary_selected, "load_tlb_seq"))
    has_event_types = "event_type" in frame.columns
    # Unified streams add two origin-only panels to the existing combined and
    # six mutually exclusive translation-outcome panels, all on one large PDF page.
    panel_count = 9 if has_event_types else 7
    row_count = math.ceil(panel_count / 2)
    fig, axes = plt.subplots(row_count, 2 * len(views), figsize=(20.0 * len(views), 4.8 * row_count), squeeze=False)
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
        raw_stlb_miss = local["stlb_accessed"].astype(bool) & local["stlb_result"].astype(str).eq("MISS")
        metrics = {"total_demand_loads": len(local), "total_stream_events": len(local), "unique_pages": int(local[PAGE_NUMBER_COLUMN].nunique()),
                   "l1dtlb_misses": int(local["l1dtlb_result"].astype(str).eq("MISS").sum()),
                   "stlb_accesses": int(local["stlb_accessed"].sum()), "stlb_misses": int(raw_stlb_miss.sum())}
        if has_event_types:
            metrics["real_data_demand_events"] = int(local["event_type"].astype(str).eq("DATA_DEMAND").sum())
            metrics["cross_page_prefetch_events"] = int(local["event_type"].astype(str).eq("VBERTI_CP_PREFETCH").sum())
        if view_index == 0:
            primary_metrics = metrics
        demand_mask = local["event_type"].astype(str).eq("DATA_DEMAND") if has_event_types else None
        prefetch_mask = local["event_type"].astype(str).eq("VBERTI_CP_PREFETCH") if has_event_types else None
        # The outcome panels are intended to characterize the program's demand
        # translation behaviour.  Keep the aggregate/origin panels above them,
        # but never mix a vBerti request into a demand outcome category.
        outcome_masks = {
            label: (mask & demand_mask) if demand_mask is not None else mask
            for label, mask in category_masks.items()
        }
        box = "\n".join(
            [
                f"coordinate: {view_label}",
                f"region: 0x{region:x}",
                f"seq: [{seq_start:,}, {seq_end:,})",
                f"stream events: {metrics['total_stream_events']:,}",
                f"unique {PAGE_ACRONYM}s: {metrics['unique_pages']:,}",
            ]
            + ([f"real data demand: {metrics['real_data_demand_events']:,}",
                f"cross-page vBerti: {metrics['cross_page_prefetch_events']:,}",
                "outcome panels: DATA_DEMAND only"] if has_event_types else [])
            + [f"demand {label}: {int(mask.sum()):,}" for label, mask in outcome_masks.items()]
        )
        category_styles = {
            "L1 DTLB hit": {"s": 5, "c": COLORS["l1_hit"], "alpha": 0.45, "linewidths": 0},
            "L1 miss + STLB hit": {"s": 10, "c": COLORS["stlb_hit"], "alpha": 0.75, "linewidths": 0},
            "STLB miss": {"s": 13, "c": COLORS["stlb_miss"], "alpha": 0.9, "linewidths": 0},
            "DTLB-side translation merge": {"s": 8, "c": COLORS["dtlb_merge"], "alpha": 0.65, "linewidths": 0},
            "STLB-side translation merge": {"s": 9, "c": COLORS["stlb_merge"], "alpha": 0.7, "linewidths": 0},
            "Other / incomplete": {"s": 7, "c": COLORS["other"], "alpha": 0.65, "linewidths": 0},
        }
        all_categories = [(label, category_masks[label], category_styles[label]) for label in category_masks]
        categories = [(label, outcome_masks[label], category_styles[label]) for label in category_masks]
        panels = [("All translation outcomes", all_categories)]
        if has_event_types:
            panels.extend([
                ("Real data demand only", [("Real data demand", demand_mask,
                                            {"s": 5, "c": COLORS["demand"], "alpha": 0.62, "linewidths": 0})]),
                ("vBerti cross-page prefetch only", [("vBerti cross-page prefetch", prefetch_mask,
                                                       {"s": 8, "c": COLORS["prefetch"], "alpha": 0.75, "linewidths": 0})]),
            ])
        panels.extend((f"Real data demand — {label}", [(label, mask, style)]) for label, mask, style in categories)
        view_axes = list(axes[:, 2 * view_index:2 * view_index + 2].flat)
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
        for unused_ax in view_axes[len(panels):]:
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
    # Delta regularity is a property of the program demand stream.  In a
    # unified observer log, prefetch targets are deliberately excluded here.
    demand = real_data_demand_frame(frame)
    vpns = demand[PAGE_NUMBER_COLUMN].to_numpy(dtype=np.int64)
    deltas = global_page_deltas(vpns)

    fig, axes = plt.subplots(2, 1, figsize=(12.0, 9.2))
    counts, ratios, labels = draw_delta_distribution(
        axes[0], deltas, delta_limit,
        f"Real-data-demand global page-transition delta after removing consecutive repeated {PAGE_ACRONYM}s"
    )
    wide_counts, wide_ratios, wide_labels = draw_delta_distribution(
        axes[1], deltas, wide_delta_limit,
        f"Real-data-demand expanded global page-transition delta within +/-{wide_delta_limit}"
    )
    fig.subplots_adjust(hspace=0.48)
    save_figure(fig, output_dir, "03_global_page_delta")

    adjacent_pairs = max(0, len(vpns) - 1)
    same_page_ratio = float(np.sum(vpns[1:] == vpns[:-1]) / adjacent_pairs) if adjacent_pairs else 0.0
    abs_delta = np.abs(deltas)
    top1, top1_coverage = ranked_delta_coverage(deltas, 1)
    top2, top2_coverage = ranked_delta_coverage(deltas, 2)
    metrics: dict[str, float | int | list[int]] = {
        "event_scope": "DATA_DEMAND",
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
        {"event_scope": "DATA_DEMAND", "kind": "delta_bucket", "name": label, "count": int(count), "ratio": float(ratio), "value": ""}
        for label, count, ratio in zip(labels, counts, ratios)
    ]
    rows.extend(
        {"event_scope": "DATA_DEMAND", "kind": "delta_bucket_wide", "name": label, "count": int(count), "ratio": float(ratio), "value": ""}
        for label, count, ratio in zip(wide_labels, wide_counts, wide_ratios)
    )
    rows.extend({"event_scope": "DATA_DEMAND", "kind": "metric", "name": key, "count": "", "ratio": "", "value": str(value)} for key, value in metrics.items())
    pd.DataFrame(rows).to_csv(output_dir / "03_global_page_delta_summary.csv", index=False)
    return metrics


def refresh_existing_summary_delta_scope(output_dir: Path, metrics: dict[str, float | int | list[int]]) -> None:
    """Keep a pre-existing summary consistent after a 03-only refresh."""
    path = output_dir / "analysis_summary.txt"
    if not path.exists():
        return
    replacements = {
        "same-page continuation ratio:": f"same-page continuation ratio: {metrics['same_page_continuation_ratio']:.8f}",
        "page-transition count:": f"page-transition count: {metrics['total_page_transitions']}",
        f"P(|Delta{PAGE_ACRONYM}| = 1):": f"P(|Delta{PAGE_ACRONYM}| = 1): {metrics['p_abs_delta_eq_1']:.8f}",
        f"P(|Delta{PAGE_ACRONYM}| <= 4):": f"P(|Delta{PAGE_ACRONYM}| <= 4): {metrics['p_abs_delta_le_4']:.8f}",
        f"P(|Delta{PAGE_ACRONYM}| <= 16):": f"P(|Delta{PAGE_ACRONYM}| <= 16): {metrics['p_abs_delta_le_16']:.8f}",
        f"P(|Delta{PAGE_ACRONYM}| > 16):": f"P(|Delta{PAGE_ACRONYM}| > 16): {metrics['p_abs_delta_gt_16']:.8f}",
        "global Top-1 transition-delta coverage:": f"global Top-1 transition-delta coverage: {metrics['global_top1_coverage']:.8f}",
        "global Top-2 transition-delta coverage:": f"global Top-2 transition-delta coverage: {metrics['global_top2_coverage']:.8f}",
    }
    refreshed: list[str] = []
    inserted_scope = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("global VPN-delta event scope:") or line.startswith("per-PC VPN-delta event scope:"):
            continue
        replacement = next((value for prefix, value in replacements.items() if line.startswith(prefix)), None)
        if replacement is not None:
            if not inserted_scope:
                refreshed.append("global VPN-delta event scope: DATA_DEMAND")
                inserted_scope = True
            refreshed.append(replacement)
            if line.startswith("global Top-2 transition-delta coverage:"):
                refreshed.append("per-PC VPN-delta event scope: DATA_DEMAND")
        else:
            refreshed.append(line)
    path.write_text("\n".join(refreshed) + "\n", encoding="utf-8")


def plot_per_pc(frame: pd.DataFrame, output_dir: Path, top_pcs: int, rank_by: str, delta_limit: int) -> tuple[float, float]:
    work = real_data_demand_frame(frame)
    # A vBerti request has no independent static load-PC identity.  Keep the
    # per-load-PC statistic strictly on real data demand.
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
                "event_scope": "DATA_DEMAND",
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
        (axes[0, 0], raw_matrix, raw_rows, f"Raw real-data-demand per-PC {PAGE_ACRONYM} sequence", f"Per-PC Delta {PAGE_ACRONYM} (zero retained)"),
        (axes[0, 1], dedup_matrix, dedup_rows, f"Real-data-demand per-PC sequence after removing consecutive repeated {PAGE_ACRONYM}s", f"Per-PC Delta {PAGE_ACRONYM}"),
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
        ax.set_ylabel(f"Top real-data-demand PCs by raw {rank_by}")
        ax.set_title(title)
    fig.suptitle(f"Per-static-real-data-load-PC {PAGE_ACRONYM} delta distribution", fontsize=14)
    fig.subplots_adjust(wspace=0.18, top=0.90)
    save_figure(fig, output_dir, "04_per_pc_delta_heatmap")
    return weighted_top1, weighted_top2


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


COMBINED_REQUIRED_COLUMNS = {
    "cpu", "global_seq", "event_type", "load_tlb_seq", "cross_page_prefetch_seq", "dtlb_lookup_cycle",
    "prefetch_issue_cycle", "prefetch_trigger_pc", "prefetch_trigger_va",
    "va", "vpn", "virtual_region_2m", "page_offset_in_region",
}


def read_combined_pattern(input_path: Path) -> pd.DataFrame:
    available = set(pd.read_csv(input_path, nrows=0).columns)
    missing = sorted(COMBINED_REQUIRED_COLUMNS - available)
    if missing:
        raise SystemExit(f"[ERROR] Combined pattern is missing columns: {', '.join(missing)}")
    usecols = [
        "cpu", "global_seq", "event_type", "load_tlb_seq", "cross_page_prefetch_seq", "dtlb_lookup_cycle",
        "pc", "prefetch_issue_cycle", "prefetch_trigger_pc", "prefetch_trigger_va",
        "va", "vpn", "virtual_region_2m", "page_offset_in_region",
    ]
    frame = pd.read_csv(
        input_path,
        usecols=usecols,
        dtype={
            "cpu": "uint32",
            "global_seq": "uint64",
            "event_type": "category",
            "load_tlb_seq": "float64",
            "cross_page_prefetch_seq": "float64",
            "pc": "uint64",
            "prefetch_issue_cycle": "float64",
            "prefetch_trigger_pc": "float64",
            "prefetch_trigger_va": "float64",
            "dtlb_lookup_cycle": "uint64",
            "va": "uint64",
            "vpn": "uint64",
            "virtual_region_2m": "uint64",
            "page_offset_in_region": "uint16",
        },
    )
    if frame.empty:
        raise SystemExit("[ERROR] Combined pattern CSV is empty")
    event_types = set(frame["event_type"].astype(str).unique())
    allowed = {"DATA_DEMAND", "VBERTI_CP_PREFETCH"}
    if not event_types <= allowed:
        raise SystemExit(f"[ERROR] Unexpected combined-pattern event types: {sorted(event_types - allowed)}")
    return frame


def validate_combined_pattern(frame: pd.DataFrame, page_size: int) -> pd.DataFrame:
    cores = sorted(int(value) for value in frame["cpu"].unique())
    if len(cores) != 1:
        raise SystemExit(f"[ERROR] This one-core analysis expected one CPU, found {cores}")
    frame = frame.sort_values(["cpu", "global_seq"], kind="stable").reset_index(drop=True)
    actual = frame["global_seq"].to_numpy(dtype=np.uint64)
    expected = np.arange(len(frame), dtype=np.uint64)
    if not np.array_equal(actual, expected):
        raise SystemExit("[ERROR] global_seq is not unique and contiguous from zero")

    demand = frame["event_type"].astype(str).eq("DATA_DEMAND")
    prefetch = frame["event_type"].astype(str).eq("VBERTI_CP_PREFETCH")
    if frame.loc[demand, "load_tlb_seq"].isna().any():
        raise SystemExit("[ERROR] A real-demand row has no load_tlb_seq")
    demand_seq = frame.loc[demand, "load_tlb_seq"].to_numpy(dtype=np.uint64)
    if not np.array_equal(demand_seq, np.arange(len(demand_seq), dtype=np.uint64)):
        raise SystemExit("[ERROR] load_tlb_seq is not contiguous inside the real-demand stream")
    if frame.loc[prefetch, "cross_page_prefetch_seq"].isna().any():
        raise SystemExit("[ERROR] A prefetch row has no cross_page_prefetch_seq")
    prefetch_seq = frame.loc[prefetch, "cross_page_prefetch_seq"].to_numpy(dtype=np.uint64)
    if not np.array_equal(prefetch_seq, np.arange(len(prefetch_seq), dtype=np.uint64)):
        raise SystemExit("[ERROR] cross_page_prefetch_seq is not contiguous inside the prefetch stream")
    trigger_vpn = (frame.loc[prefetch, "prefetch_trigger_va"].to_numpy(dtype=np.uint64) // page_size)
    target_vpn = frame.loc[prefetch, "vpn"].to_numpy(dtype=np.uint64)
    if np.any(trigger_vpn == target_vpn):
        raise SystemExit("[ERROR] The cross-page stream contains a same-page vBerti candidate")
    return frame


def choose_combined_local_window(
    displayed: pd.DataFrame,
    coarse_bin_size: int,
    requested_region: int | None,
    requested_start: int | None,
    requested_end: int | None,
) -> tuple[int, int, int]:
    if (requested_start is None) != (requested_end is None):
        raise ValueError("--seq-start and --seq-end must be supplied together")
    if requested_start is not None and requested_start >= requested_end:
        raise ValueError("--seq-start must be less than --seq-end")
    working = displayed
    if requested_start is not None:
        working = working[(working["global_seq"] >= requested_start) & (working["global_seq"] < requested_end)]
    if requested_region is not None:
        working = working[working["virtual_region_2m"] == requested_region]
    if working.empty:
        raise ValueError("The requested common-sequence/region scope contains no displayed event")
    if requested_start is not None and requested_region is not None:
        return requested_region, requested_start, requested_end

    scoped = working[["global_seq", "virtual_region_2m", "event_type"]].copy()
    scoped["time_bin"] = scoped["global_seq"] // coarse_bin_size
    scoped["is_demand"] = scoped["event_type"].astype(str).eq("DATA_DEMAND")
    scoped["is_prefetch"] = ~scoped["is_demand"]
    cells = (
        scoped.groupby(["virtual_region_2m", "time_bin"], observed=True)
        .agg(event_count=("global_seq", "size"), demand_count=("is_demand", "sum"), prefetch_count=("is_prefetch", "sum"))
        .reset_index()
    )
    cells = cells.sort_values(
        ["event_count", "demand_count", "prefetch_count", "virtual_region_2m", "time_bin"],
        ascending=[False, False, False, True, True],
    )
    selected = cells.iloc[0]
    region = requested_region if requested_region is not None else int(selected["virtual_region_2m"])
    if requested_start is not None:
        return region, requested_start, requested_end
    time_bin = int(selected["time_bin"])
    return region, time_bin * coarse_bin_size, (time_bin + 1) * coarse_bin_size


def combined_heatmap_matrix(frame: pd.DataFrame, regions: np.ndarray, bins: np.ndarray, coarse_bin_size: int) -> np.ndarray:
    if frame.empty:
        return np.zeros((len(regions), len(bins)), dtype=np.int64)
    work = frame[["global_seq", "virtual_region_2m"]].copy()
    work["time_bin"] = work["global_seq"] // coarse_bin_size
    grouped = work.groupby(["virtual_region_2m", "time_bin"], observed=True).size().rename("count").reset_index()
    return (
        grouped.pivot(index="virtual_region_2m", columns="time_bin", values="count")
        .reindex(index=regions, columns=bins, fill_value=0)
        .fillna(0)
        .to_numpy(dtype=np.int64)
    )


def plot_combined_region_time(
    demand: pd.DataFrame,
    accepted_prefetch: pd.DataFrame,
    displayed: pd.DataFrame,
    output_dir: Path,
    coarse_bin_size: int,
    selected: tuple[int, int, int],
) -> None:
    min_bin = int(displayed["global_seq"].min() // coarse_bin_size)
    max_bin = int(displayed["global_seq"].max() // coarse_bin_size)
    bins = np.arange(min_bin, max_bin + 1, dtype=np.int64)
    regions = np.sort(displayed["virtual_region_2m"].unique())
    matrices = [
        combined_heatmap_matrix(demand, regions, bins, coarse_bin_size),
        combined_heatmap_matrix(accepted_prefetch, regions, bins, coarse_bin_size),
    ]
    titles = [
        "Real data demand: 2 MiB virtual region by global_seq",
        "Accepted cross-page vBerti prefetch: 2 MiB virtual region by global_seq",
    ]
    colors = [
        LinearSegmentedColormap.from_list("demand_regions", ["#f7fbff", "#9ecae1", "#2171b5", "#08306b"]),
        LinearSegmentedColormap.from_list("prefetch_regions", ["#fff7ec", "#fdd49e", "#f16913", "#7f2704"]),
    ]
    fig = plt.figure(figsize=(18.0, max(9.0, min(16.0, 7.0 + 0.08 * len(regions)))))
    grid = fig.add_gridspec(3, 2, height_ratios=[4.8, 4.8, 1.8], width_ratios=[35.0, 1.2], hspace=0.18, wspace=0.04)
    x_start = min_bin * coarse_bin_size
    x_end = (max_bin + 1) * coarse_bin_size
    region, selected_start, selected_end = selected
    shared_ax = None
    for row, (matrix, title, cmap) in enumerate(zip(matrices, titles, colors)):
        ax = fig.add_subplot(grid[row, 0], sharex=shared_ax) if shared_ax is not None else fig.add_subplot(grid[row, 0])
        if shared_ax is None:
            shared_ax = ax
        cax = fig.add_subplot(grid[row, 1])
        image = ax.imshow(np.log1p(matrix), aspect="auto", origin="lower", cmap=cmap,
                          extent=[x_start, x_end, -0.5, len(regions) - 0.5])
        colorbar = fig.colorbar(image, cax=cax)
        colorbar.set_label("log1p(event count)")
        ticks = np.unique(np.linspace(0, len(regions) - 1, min(24, len(regions)), dtype=int))
        ax.set_yticks(ticks)
        ax.set_yticklabels([f"0x{int(regions[position]):x}" for position in ticks], fontsize=8)
        ax.set_ylabel("Active 2 MiB virtual region ID")
        ax.set_title(title)
        if region in regions:
            region_row = int(np.where(regions == region)[0][0])
            ax.add_patch(Rectangle((selected_start, region_row - 0.5), selected_end - selected_start, 1.0,
                                   fill=False, edgecolor="#7b2cbf", linewidth=1.8))
        ax.xaxis.get_offset_text().set_visible(False)
        plt.setp(ax.get_xticklabels(), visible=False)

    count_ax = fig.add_subplot(grid[2, 0], sharex=shared_ax)
    bin_edges = np.arange(min_bin, max_bin + 2, dtype=np.int64) * coarse_bin_size
    demand_counts = demand.assign(time_bin=demand["global_seq"] // coarse_bin_size).groupby("time_bin").size().reindex(bins, fill_value=0)
    prefetch_counts = accepted_prefetch.assign(time_bin=accepted_prefetch["global_seq"] // coarse_bin_size).groupby("time_bin").size().reindex(bins, fill_value=0)
    count_ax.stairs(demand_counts.to_numpy(), bin_edges, label="Real data demand", color="#2171b5", linewidth=1.3)
    count_ax.stairs(prefetch_counts.to_numpy(), bin_edges, label="Accepted cross-page vBerti prefetch", color="#e6550d", linewidth=1.3)
    count_ax.set_ylabel("Events/bin")
    count_ax.set_xlabel("global_seq (shared source-observation order)")
    count_ax.grid(axis="y", linestyle=":", alpha=0.35)
    count_ax.legend(loc="upper right", frameon=False)
    fig.add_subplot(grid[2, 1]).axis("off")
    save_figure(fig, output_dir, "01_region_time_comparison")


def write_combined_window_records(
    input_path: Path,
    output_path: Path,
    cpu: int,
    selected: tuple[int, int, int],
) -> int:
    region, seq_start, seq_end = selected
    wrote_header = False
    row_count = 0
    for chunk in pd.read_csv(input_path, chunksize=250_000):
        rows = chunk[(chunk["cpu"] == cpu) & (chunk["global_seq"] >= seq_start) & (chunk["global_seq"] < seq_end)].copy()
        if rows.empty:
            continue
        rows["in_selected_region"] = rows["virtual_region_2m"].eq(region).astype(np.uint8)
        rows["displayed_in_figure"] = (
            rows["in_selected_region"].astype(bool)
            & (rows["event_type"].eq("DATA_DEMAND")
               | rows["event_type"].eq("VBERTI_CP_PREFETCH"))
        ).astype(np.uint8)
        rows.to_csv(output_path, mode="w" if not wrote_header else "a", header=not wrote_header, index=False)
        wrote_header = True
        row_count += len(rows)
    if not wrote_header:
        pd.DataFrame().to_csv(output_path, index=False)
    return row_count


def plot_combined_local_raster(
    demand: pd.DataFrame,
    accepted_prefetch: pd.DataFrame,
    output_dir: Path,
    selected: tuple[int, int, int],
) -> dict[str, int]:
    region, seq_start, seq_end = selected
    demand_local = demand[(demand["virtual_region_2m"] == region) & (demand["global_seq"] >= seq_start) & (demand["global_seq"] < seq_end)]
    prefetch_local = accepted_prefetch[(accepted_prefetch["virtual_region_2m"] == region)
                                          & (accepted_prefetch["global_seq"] >= seq_start)
                                          & (accepted_prefetch["global_seq"] < seq_end)]
    fig, axes = plt.subplots(3, 1, figsize=(18.0, 11.0), sharex=True, sharey=True)
    axes[0].scatter(demand_local["global_seq"], demand_local["page_offset_in_region"], s=4.0, color="#2171b5",
                    alpha=0.58, linewidths=0, rasterized=True, label="Real data demand")
    axes[0].scatter(prefetch_local["global_seq"], prefetch_local["page_offset_in_region"], s=7.0, marker="x", color="#e6550d",
                    alpha=0.78, linewidths=0.55, rasterized=True, label="Accepted cross-page vBerti prefetch")
    axes[0].legend(loc="upper right", frameon=False)
    axes[0].set_title("Overlay")
    axes[1].scatter(demand_local["global_seq"], demand_local["page_offset_in_region"], s=4.0, color="#2171b5",
                    alpha=0.68, linewidths=0, rasterized=True)
    axes[1].set_title("Real data demand only")
    axes[2].scatter(prefetch_local["global_seq"], prefetch_local["page_offset_in_region"], s=7.0, marker="x", color="#e6550d",
                    alpha=0.82, linewidths=0.55, rasterized=True)
    axes[2].set_title("Accepted cross-page vBerti prefetch only")
    for ax in axes:
        ax.set_ylabel("4 KiB page offset\ninside selected 2 MiB region")
        ax.set_ylim(-8, 519)
        ax.grid(linestyle=":", linewidth=0.45, alpha=0.35)
    axes[-1].set_xlabel("global_seq (same selected interval for both streams)")
    fig.suptitle(f"Local page-offset raster: region 0x{region:x}, global_seq [{seq_start:,}, {seq_end:,})", fontsize=14)
    fig.subplots_adjust(top=0.92, hspace=0.22)
    save_figure(fig, output_dir, "02_local_page_offset_raster")
    return {"demand_count": len(demand_local), "accepted_prefetch_count": len(prefetch_local)}


def sampled_for_scatter(frame: pd.DataFrame, limit: int = 750_000) -> pd.DataFrame:
    if len(frame) <= limit:
        return frame
    positions = np.linspace(0, len(frame) - 1, limit, dtype=np.int64)
    return frame.iloc[positions]


def plot_combined_vpn_trajectory(demand: pd.DataFrame, accepted_prefetch: pd.DataFrame, output_dir: Path) -> None:
    demand_plot = sampled_for_scatter(demand)
    prefetch_plot = sampled_for_scatter(accepted_prefetch)
    fig, axes = plt.subplots(3, 1, figsize=(18.0, 12.0), sharex=True)
    axes[0].scatter(demand_plot["global_seq"], demand_plot["vpn"], s=0.5, color="#2171b5", alpha=0.48,
                    linewidths=0, rasterized=True, label="Real data demand")
    axes[0].scatter(prefetch_plot["global_seq"], prefetch_plot["vpn"], s=1.0, color="#e6550d", alpha=0.55,
                    linewidths=0, rasterized=True, label="Accepted cross-page vBerti prefetch")
    axes[0].legend(loc="upper right", frameon=False)
    axes[0].set_title("Raw VPN trajectories overlaid")
    axes[1].scatter(demand_plot["global_seq"], demand_plot["vpn"], s=0.5, color="#2171b5", alpha=0.55,
                    linewidths=0, rasterized=True)
    axes[1].set_title("Real data demand raw VPN trajectory")
    axes[2].scatter(prefetch_plot["global_seq"], prefetch_plot["vpn"], s=1.0, color="#e6550d", alpha=0.62,
                    linewidths=0, rasterized=True)
    axes[2].set_title("Accepted cross-page vBerti prefetch raw VPN trajectory")
    for ax in axes:
        ax.set_ylabel("VPN")
        ax.grid(linestyle=":", linewidth=0.45, alpha=0.30)
    axes[-1].set_xlabel("global_seq")
    fig.suptitle("Demand versus cross-page vBerti VPN trajectory (plot-only deterministic sampling when needed)", fontsize=14)
    fig.subplots_adjust(top=0.93, hspace=0.22)
    save_figure(fig, output_dir, "03_vpn_trajectory_comparison")


def raw_delta_topk_rows(frame: pd.DataFrame, stream: str, k: int = 20) -> list[dict[str, object]]:
    vpns = frame["vpn"].to_numpy(dtype=np.int64)
    deltas = np.diff(vpns)
    total = len(deltas)
    ranked = sorted(Counter(int(value) for value in deltas).items(), key=lambda item: (-item[1], item[0]))[:k]
    return [
        {"stream": stream, "rank": rank, "delta_vpn": delta, "count": count, "share_of_stream_pairs": count / total if total else 0.0,
         "total_stream_pairs": total}
        for rank, (delta, count) in enumerate(ranked, start=1)
    ]


def plot_combined_delta(demand: pd.DataFrame, accepted_prefetch: pd.DataFrame, output_dir: Path) -> None:
    demand_rows = raw_delta_topk_rows(demand, "real_data_demand")
    prefetch_rows = raw_delta_topk_rows(accepted_prefetch, "accepted_cross_page_vberti_prefetch")
    rows = demand_rows + prefetch_rows
    pd.DataFrame(rows).to_csv(output_dir / "04_vpn_delta_top20.csv", index=False)
    fig, axes = plt.subplots(2, 1, figsize=(18.0, 9.0))
    for ax, section, title, color in [
        (axes[0], demand_rows, "Real data demand: raw adjacent DeltaVPN Top 20", "#2171b5"),
        (axes[1], prefetch_rows, "Accepted cross-page vBerti prefetch: raw adjacent DeltaVPN Top 20", "#e6550d"),
    ]:
        if section:
            labels = [str(row["delta_vpn"]) for row in section]
            values = [100.0 * float(row["share_of_stream_pairs"]) for row in section]
            ax.bar(np.arange(len(section)), values, color=color, alpha=0.82)
            ax.set_xticks(np.arange(len(section)))
            ax.set_xticklabels(labels, rotation=45, ha="right")
        else:
            ax.text(0.5, 0.5, "No adjacent pair", ha="center", va="center", transform=ax.transAxes)
        ax.set_ylabel("Share of stream pairs (%)")
        ax.set_title(title)
        ax.grid(axis="y", linestyle=":", alpha=0.35)
    axes[-1].set_xlabel("DeltaVPN")
    fig.subplots_adjust(hspace=0.36, bottom=0.12)
    save_figure(fig, output_dir, "04_vpn_delta_comparison")


def build_future_vpn_matches(demand: pd.DataFrame, accepted_prefetch: pd.DataFrame) -> pd.DataFrame:
    result_parts: list[pd.DataFrame] = []
    demand_groups = {int(vpn): rows.sort_values("global_seq") for vpn, rows in demand.groupby("vpn", sort=False)}
    for vpn, prefetch_rows in accepted_prefetch.groupby("vpn", sort=False):
        prefetch_rows = prefetch_rows.sort_values("global_seq").copy()
        matching_demand = demand_groups.get(int(vpn))
        if matching_demand is None:
            prefetch_rows["future_demand_found"] = 0
            prefetch_rows["next_demand_global_seq"] = np.nan
            prefetch_rows["next_demand_load_tlb_seq"] = np.nan
            prefetch_rows["next_demand_cycle"] = np.nan
        else:
            demand_seq = matching_demand["global_seq"].to_numpy(dtype=np.uint64)
            positions = np.searchsorted(demand_seq, prefetch_rows["global_seq"].to_numpy(dtype=np.uint64), side="right")
            valid = positions < len(demand_seq)
            next_global = np.full(len(prefetch_rows), np.nan)
            next_load = np.full(len(prefetch_rows), np.nan)
            next_cycle = np.full(len(prefetch_rows), np.nan)
            if np.any(valid):
                selected_demand = matching_demand.iloc[positions[valid]]
                next_global[valid] = selected_demand["global_seq"].to_numpy(dtype=np.float64)
                next_load[valid] = selected_demand["load_tlb_seq"].to_numpy(dtype=np.float64)
                next_cycle[valid] = selected_demand["dtlb_lookup_cycle"].to_numpy(dtype=np.float64)
            prefetch_rows["future_demand_found"] = valid.astype(np.uint8)
            prefetch_rows["next_demand_global_seq"] = next_global
            prefetch_rows["next_demand_load_tlb_seq"] = next_load
            prefetch_rows["next_demand_cycle"] = next_cycle
        result_parts.append(prefetch_rows)
    if not result_parts:
        return pd.DataFrame()
    result = pd.concat(result_parts, ignore_index=True).sort_values("global_seq", kind="stable")
    result["lead_global_events"] = result["next_demand_global_seq"] - result["global_seq"]
    result["lead_cycles"] = result["next_demand_cycle"] - result["dtlb_lookup_cycle"]
    return result


def plot_future_vpn_matches(matches: pd.DataFrame, output_dir: Path) -> dict[str, float]:
    output_csv = output_dir / "05_future_demand_vpn_match.csv"
    if matches.empty:
        matches.to_csv(output_csv, index=False)
        matched_count = 0
        total = 0
        valid = matches
    else:
        matches.to_csv(output_csv, index=False)
        total = len(matches)
        matched_count = int(matches["future_demand_found"].sum())
        valid = matches[matches["future_demand_found"].astype(bool)]
    match_rate = matched_count / total if total else 0.0
    fig, axes = plt.subplots(1, 3, figsize=(18.0, 5.2))
    axes[0].bar(["Future same-VPN\ndemand", "No future same-VPN\ndemand"], [matched_count, total - matched_count],
                color=["#2ca25f", "#bdbdbd"])
    axes[0].set_ylabel("Accepted cross-page candidates")
    axes[0].set_title(f"VPN future-match rate = {100.0 * match_rate:.2f}%")
    if not valid.empty:
        axes[1].hist(valid["lead_global_events"], bins=80, color="#756bb1", alpha=0.82, log=True)
        axes[2].hist(valid["lead_cycles"], bins=80, color="#31a354", alpha=0.82, log=True)
    axes[1].set_xlabel("Next same-VPN demand distance (global events)")
    axes[2].set_xlabel("Next same-VPN demand lead (cycles)")
    axes[1].set_ylabel("Candidates (log count)")
    axes[2].set_ylabel("Candidates (log count)")
    axes[1].set_title("Event-distance distribution")
    axes[2].set_title("Cycle-lead distribution")
    for ax in axes:
        ax.grid(axis="y", linestyle=":", alpha=0.35)
    fig.suptitle("Spatial future match only: it is not equivalent to a measured TLB useful hit", fontsize=13)
    fig.subplots_adjust(top=0.84, wspace=0.28)
    save_figure(fig, output_dir, "05_future_demand_vpn_match")
    return {
        "future_vpn_match_count": matched_count,
        "future_vpn_match_rate": match_rate,
        "median_lead_global_events": float(valid["lead_global_events"].median()) if not valid.empty else math.nan,
        "median_lead_cycles": float(valid["lead_cycles"].median()) if not valid.empty else math.nan,
    }


def write_combined_readme(output_dir: Path) -> None:
    text = """# vBerti cross-page prefetch vs. real demand TLB pattern

本目录只比较 `DATA_DEMAND` 和 vBerti 产生的 `VBERTI_CP_PREFETCH`；same-page prefetch 不进入记录。

所有图的主横轴均为源码记录器分配的 `global_seq`。它表示两类事件在本 core 上进入观察器的公共顺序；`load_tlb_seq` 和
`cross_page_prefetch_seq` 分别是两个流内部的编号。`dtlb_lookup_cycle` 用于计算提前周期，但图中的空间轨迹不以 cycle 为主横轴。

- `01_region_time_comparison`：real demand 与已被 `prefetch_line()` 接收的 cross-page vBerti 目标使用相同 `global_seq` 范围和相同 region 行。
- `02_local_page_offset_raster`：`choose_local_window()` 在联合流上选择一个公共 `global_seq` 窗口，三行分别为叠加、demand、accepted cross-page prefetch。
- `02_local_page_offset_raster_records_global_seq.csv`：选中公共时间段内的完整原始记录；`in_selected_region` 和
  `displayed_in_figure` 指明哪些行实际画在局部 raster 中。
- `03_vpn_trajectory_comparison`：两类事件的原始 VPN 轨迹。大流只对绘图点做确定性降采样，统计仍使用全量数据。
- `04_vpn_delta_top20.csv`/`04_vpn_delta_comparison`：两个未去重内部序列各自的相邻 DeltaVPN Top 20。
- `05_future_demand_vpn_match`：对每个 accepted cross-page 目标查找之后首次同 VPN demand。它只表达空间预测机会，不能替代
  ChampSim 的 STLB/DTLB useful 统计。

每条 `VBERTI_CP_PREFETCH` 都是已经成功送入 DTLB 的实际跨页请求，因此无需额外的常量 accepted 字段。
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def analyze_combined_pattern(args: argparse.Namespace) -> None:
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    page_size = int(metadata["page_size"])
    frame = validate_combined_pattern(read_combined_pattern(args.combined_input), page_size)
    demand_mask = frame["event_type"].astype(str).eq("DATA_DEMAND")
    prefetch_mask = frame["event_type"].astype(str).eq("VBERTI_CP_PREFETCH")
    demand = frame[demand_mask].copy()
    prefetch = frame[prefetch_mask].copy()
    accepted_prefetch = prefetch.copy()
    displayed = pd.concat([demand, accepted_prefetch], ignore_index=True).sort_values("global_seq", kind="stable")
    if displayed.empty:
        raise SystemExit("[ERROR] No demand or accepted cross-page prefetch event is available")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = choose_combined_local_window(displayed, args.coarse_bin_size, args.region_id, args.seq_start, args.seq_end)
    print(f"[INFO] Combined local window: region=0x{selected[0]:x}, global_seq=[{selected[1]}, {selected[2]})")
    plot_combined_region_time(demand, accepted_prefetch, displayed, args.output_dir, args.coarse_bin_size, selected)
    local_metrics = plot_combined_local_raster(demand, accepted_prefetch, args.output_dir, selected)
    exported_rows = write_combined_window_records(
        args.combined_input, args.output_dir / "02_local_page_offset_raster_records_global_seq.csv", int(frame["cpu"].iloc[0]), selected
    )
    plot_combined_vpn_trajectory(demand, accepted_prefetch, args.output_dir)
    plot_combined_delta(demand, accepted_prefetch, args.output_dir)
    match_metrics = plot_future_vpn_matches(build_future_vpn_matches(demand, accepted_prefetch), args.output_dir)
    summary = {
        "real_data_demand_events": len(demand),
        "cross_page_prefetch_recorded": len(prefetch),
        "selected_region_2m": f"0x{selected[0]:x}",
        "selected_global_seq_start": selected[1],
        "selected_global_seq_end": selected[2],
        "selected_window_exported_rows": exported_rows,
        "selected_region_demand_events": local_metrics["demand_count"],
        "selected_region_accepted_prefetch_events": local_metrics["accepted_prefetch_count"],
        **match_metrics,
    }
    pd.DataFrame([summary]).to_csv(args.output_dir / "analysis_summary.csv", index=False)
    (args.output_dir / "analysis_summary.txt").write_text(
        "\n".join(f"{key}: {value}" for key, value in summary.items()) + "\n", encoding="utf-8"
    )
    write_combined_readme(args.output_dir)
    for key, value in summary.items():
        print(f"[SUMMARY] {key}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a demand-only or unified demand/cross-page-vBerti TLB stream.")
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
    only_group.add_argument("--global-delta-only", action="store_true",
                            help="Only regenerate 03_global_page_delta and its raw/summary CSV tables")
    parser.add_argument("--skip-trajectories", action="store_true",
                        help="Regenerate summaries and 01--04, but retain existing 05 trajectory files")
    args = parser.parse_args()
    if args.coarse_bin_size <= 0 or args.top_pcs <= 0 or args.delta_limit <= 0 or args.wide_delta_limit <= 0:
        parser.error("coarse-bin-size, top-pcs, delta-limit, and wide-delta-limit must be positive")
    if args.wide_delta_limit < args.delta_limit:
        parser.error("wide-delta-limit must be greater than or equal to delta-limit")

    configure_address_space(args.address_space)
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    page_size = int(metadata["page_size"])
    region_size = int(metadata["region_size"])
    input_columns = set(pd.read_csv(args.input, nrows=0).columns)
    unified_stream = {"global_seq", "event_type"} <= input_columns
    stream_spec = STREAM_SPECS[args.stream_kind]
    if unified_stream:
        sequence_column = "global_seq"
        sequence_label = "global_seq"
        unified_titles = {
            "dtlb_access": "Real-demand + cross-page-vBerti L1 DTLB access",
            "stlb_access": "Real-demand + cross-page-vBerti STLB access",
            "stlb_miss": "Real-demand + cross-page-vBerti STLB miss",
        }
        stream_title = unified_titles[args.stream_kind]
    else:
        sequence_column = str(stream_spec["sequence_column"])
        sequence_label = str(stream_spec["sequence_label"])
        stream_title = str(stream_spec["title"])
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
        if args.address_space == "virtual" and args.stream_kind == "dtlb_access" and not np.array_equal(actual, expected):
            raise SystemExit(f"[ERROR] Core {cpu}: {sequence_column} is not contiguous from zero")
        if (args.address_space == "physical" or args.stream_kind != "dtlb_access") and (len(actual) > 1 and np.any(actual[1:] <= actual[:-1])):
            raise SystemExit(f"[ERROR] Core {cpu}: {sequence_column} is not strictly increasing")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.per_pc_only:
        plot_per_pc(frame, args.output_dir, args.top_pcs, args.pc_rank_by, args.delta_limit)
        print(f"[DONE] Regenerated {args.output_dir / '04_per_pc_topk.csv'}")
        return

    if args.global_delta_only:
        write_raw_global_delta_topk(frame, args.output_dir)
        global_metrics = plot_global_delta(frame, args.output_dir, args.delta_limit, args.wide_delta_limit)
        refresh_existing_summary_delta_scope(args.output_dir, global_metrics)
        print(f"[DONE] Regenerated real-data-demand 03 delta figures/tables in {args.output_dir}")
        return

    dual_load_sequence = args.stream_kind != "dtlb_access" and not unified_stream
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

    if not args.skip_trajectories:
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
    real_demand_events = int(frame["event_type"].astype(str).eq("DATA_DEMAND").sum()) if unified_stream else len(frame)
    cross_page_prefetch_events = int(frame["event_type"].astype(str).eq("VBERTI_CP_PREFETCH").sum()) if unified_stream else 0

    lines = [
        f"stream kind: {args.stream_kind}",
        f"address space: {args.address_space}",
        f"sequence column: {sequence_column}",
        f"real data-demand events: {real_demand_events}",
        f"vBerti cross-page prefetch events: {cross_page_prefetch_events}",
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
        "global VPN-delta event scope: DATA_DEMAND",
        f"same-page continuation ratio: {global_metrics['same_page_continuation_ratio']:.8f}",
        f"page-transition count: {global_metrics['total_page_transitions']}",
        f"P(|Delta{PAGE_ACRONYM}| = 1): {global_metrics['p_abs_delta_eq_1']:.8f}",
        f"P(|Delta{PAGE_ACRONYM}| <= 4): {global_metrics['p_abs_delta_le_4']:.8f}",
        f"P(|Delta{PAGE_ACRONYM}| <= 16): {global_metrics['p_abs_delta_le_16']:.8f}",
        f"P(|Delta{PAGE_ACRONYM}| > 16): {global_metrics['p_abs_delta_gt_16']:.8f}",
        f"global Top-1 transition-delta coverage: {global_metrics['global_top1_coverage']:.8f}",
        f"global Top-2 transition-delta coverage: {global_metrics['global_top2_coverage']:.8f}",
        "per-PC VPN-delta event scope: DATA_DEMAND",
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
