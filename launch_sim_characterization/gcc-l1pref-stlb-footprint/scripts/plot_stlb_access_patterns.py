#!/usr/bin/env python3
import argparse
import math
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(description="Plot STLB virtual-page access patterns.")
    parser.add_argument("--input", required=True, type=Path, help="Input stlb_access_trace.csv")
    parser.add_argument("--outdir", required=True, type=Path, help="Output directory")
    parser.add_argument("--window", default=100, type=int, help="Window size in accesses")
    parser.add_argument("--delta-clip", default=64, type=int, help="Y-axis clipping for adjacent VPN delta plots")
    parser.add_argument("--heatmap-delta-max", default=16, type=int, help="Plot windowed heatmap for deltas in [-N, +N]")
    parser.add_argument("--topk", default=20, type=int, help="Number of global top deltas to write")
    parser.add_argument("--stream-label", default="STLB", help="Name used for access-id axis labels")
    return parser.parse_args()


def save_line_or_scatter(x, y, ylabel, title, output, stream_label, marker_size=0.2):
    fig, ax = plt.subplots(figsize=(12, 4.8))
    if len(x) <= 200000:
        ax.plot(x, y, linewidth=0.35)
    else:
        ax.scatter(x, y, s=marker_size, rasterized=True)
    ax.set_xlabel(f"{stream_label} access id")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, linewidth=0.3, alpha=0.4)
    fig.tight_layout()
    fig.savefig(output, dpi=300)
    plt.close(fig)


def save_symlog_scatter(x, y, ylabel, title, output, stream_label, marker_size=0.15):
    fig, ax = plt.subplots(figsize=(12, 4.8))
    if len(x) <= 200000:
        ax.plot(x, y, linewidth=0.35)
    else:
        ax.scatter(x, y, s=marker_size, rasterized=True)
    ax.set_xlabel(f"{stream_label} access id")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_yscale("symlog", linthresh=64)
    ax.grid(True, linewidth=0.3, alpha=0.4)
    fig.tight_layout()
    fig.savefig(output, dpi=300)
    plt.close(fig)


def first_touch_ids(vpns):
    mapping = {}
    next_id = 0
    output = np.empty(len(vpns), dtype=np.int64)
    for idx, vpn in enumerate(vpns):
        key = int(vpn)
        if key not in mapping:
            mapping[key] = next_id
            next_id += 1
        output[idx] = mapping[key]
    return output


def window_stats(access_ids, vpns, window, heatmap_delta_max):
    rows = []
    heatmap_rows = []
    if len(vpns) == 0:
        return pd.DataFrame(), pd.DataFrame()

    heatmap_deltas = list(range(-heatmap_delta_max, heatmap_delta_max + 1))
    window_ids = access_ids // window
    start = 0
    while start < len(vpns):
        win = int(window_ids[start])
        end = start + 1
        while end < len(vpns) and window_ids[end] == win:
            end += 1

        vals = vpns[start:end].astype(np.int64, copy=False)
        deltas = vals[1:] - vals[:-1]
        denom = len(deltas)
        counts = Counter(int(x) for x in deltas)
        top1 = counts.most_common(1)[0][1] / denom if denom else 0.0
        top4 = sum(v for _, v in counts.most_common(4)) / denom if denom else 0.0
        top8 = sum(v for _, v in counts.most_common(8)) / denom if denom else 0.0
        zero = counts.get(0, 0) / denom if denom else 0.0
        plus1 = counts.get(1, 0) / denom if denom else 0.0
        minus1 = counts.get(-1, 0) / denom if denom else 0.0
        small_jump = 0.0
        medium_jump = 0.0
        large_jump = 0.0
        if denom:
            small_jump = sum(counts.get(delta, 0) for delta in (-4, -3, -2, 2, 3, 4)) / denom
            medium_jump = sum(count for delta, count in counts.items() if 4 < abs(delta) <= 16) / denom
            large_jump = sum(count for delta, count in counts.items() if abs(delta) > 16) / denom
        entropy = 0.0
        if denom:
            for count in counts.values():
                p = count / denom
                entropy -= p * math.log2(p)

        rows.append(
            {
                "window_id": win,
                "access_start": int(access_ids[start]),
                "access_end": int(access_ids[end - 1]),
                "num_accesses": int(end - start),
                "num_deltas": int(denom),
                "unique_vpn": int(len(set(int(x) for x in vals))),
                "unique_delta": int(len(counts)),
                "delta_top1_coverage": top1,
                "delta_top4_coverage": top4,
                "delta_top8_coverage": top8,
                "delta_zero_ratio": zero,
                "delta_plus1_ratio": plus1,
                "delta_minus1_ratio": minus1,
                "delta_small_jump_ratio": small_jump,
                "delta_medium_jump_ratio": medium_jump,
                "delta_large_jump_ratio": large_jump,
                "delta_entropy": entropy,
            }
        )

        heatmap_row = {
            "window_id": win,
            "access_start": int(access_ids[start]),
            "access_end": int(access_ids[end - 1]),
            "num_deltas": int(denom),
        }
        for delta in heatmap_deltas:
            heatmap_row[delta] = counts.get(delta, 0) / denom if denom else 0.0
        heatmap_rows.append(heatmap_row)
        start = end

    return pd.DataFrame(rows), pd.DataFrame(heatmap_rows)


def global_delta_tables(deltas, topk, hist_delta_max):
    if len(deltas) == 0:
        empty_topk = pd.DataFrame(columns=["rank", "delta", "count", "ratio"])
        empty_hist = pd.DataFrame(columns=["bin", "delta", "count", "ratio"])
        return empty_topk, empty_hist

    unique, counts = np.unique(deltas, return_counts=True)
    total = int(len(deltas))
    count_df = pd.DataFrame({"delta": unique.astype(np.int64), "count": counts.astype(np.int64)})
    count_df["ratio"] = count_df["count"] / total

    topk_df = count_df.sort_values(["count", "delta"], ascending=[False, True]).head(topk).copy()
    topk_df.insert(0, "rank", np.arange(1, len(topk_df) + 1))

    count_map = dict(zip(count_df["delta"].astype(int), count_df["count"].astype(int)))
    hist_rows = []
    lower_count = int(count_df.loc[count_df["delta"] < -hist_delta_max, "count"].sum())
    hist_rows.append({"bin": f"<{-hist_delta_max}", "delta": -hist_delta_max - 1, "count": lower_count, "ratio": lower_count / total})
    for delta in range(-hist_delta_max, hist_delta_max + 1):
        count = count_map.get(delta, 0)
        hist_rows.append({"bin": str(delta), "delta": delta, "count": count, "ratio": count / total})
    upper_count = int(count_df.loc[count_df["delta"] > hist_delta_max, "count"].sum())
    hist_rows.append({"bin": f">{hist_delta_max}", "delta": hist_delta_max + 1, "count": upper_count, "ratio": upper_count / total})

    return topk_df, pd.DataFrame(hist_rows)


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.input)
    if df.empty:
        raise SystemExit(f"No rows in {args.input}")

    required = {"access_id", "cycle", "ip", "vaddr", "vpn", "offset", "type"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise SystemExit(f"Missing required columns: {missing}")

    access_ids = df["access_id"].to_numpy(dtype=np.int64)
    vpns = df["vpn"].to_numpy(dtype=np.int64)

    if "origin" in df.columns:
        origin_summary = df["origin"].value_counts().rename_axis("origin").reset_index(name="count")
        origin_summary["ratio"] = origin_summary["count"] / len(df)
        origin_summary.to_csv(args.outdir / f"{args.stream_label.lower()}_origin_summary.csv", index=False)

    save_line_or_scatter(
        access_ids,
        vpns,
        "Raw virtual page number",
        "Raw VPN trajectory",
        args.outdir / "fig_a_raw_vpn_trajectory.png",
        args.stream_label,
    )

    ft_ids = first_touch_ids(vpns)
    save_line_or_scatter(
        access_ids,
        ft_ids,
        "First-touch VPN id",
        "First-touch VPN id trajectory",
        args.outdir / "fig_b_first_touch_vpn_id_trajectory.png",
        args.stream_label,
    )

    if len(vpns) >= 2:
        delta_x = access_ids[1:]
        deltas = vpns[1:] - vpns[:-1]
        clipped = np.clip(deltas, -args.delta_clip, args.delta_clip)
        save_line_or_scatter(
            delta_x,
            clipped,
            f"Adjacent raw VPN delta, clipped to +/-{args.delta_clip}",
            "Adjacent raw VPN delta sequence",
            args.outdir / "fig_c_adjacent_raw_vpn_delta_sequence.png",
            args.stream_label,
            marker_size=0.15,
        )
        save_symlog_scatter(
            delta_x,
            deltas,
            "Adjacent raw VPN delta, unclipped, symlog scale",
            "Adjacent raw VPN delta sequence, symlog",
            args.outdir / "fig_c2_adjacent_raw_vpn_delta_sequence_symlog.png",
            args.stream_label,
            marker_size=0.15,
        )
    else:
        deltas = np.array([], dtype=np.int64)

    topk_df, hist_df = global_delta_tables(deltas, args.topk, args.delta_clip)
    topk_df.to_csv(args.outdir / "vpn_delta_global_topk.csv", index=False)
    hist_df.to_csv(args.outdir / "vpn_delta_global_histogram.csv", index=False)

    if not hist_df.empty:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        ax.bar(hist_df["bin"], hist_df["ratio"], width=0.85)
        ax.set_xlabel("Adjacent raw VPN delta bin")
        ax.set_ylabel("Global ratio, log scale")
        ax.set_title(f"Global adjacent raw VPN delta histogram, exact within +/-{args.delta_clip}")
        ax.set_yscale("log")
        tick_step = max(1, len(hist_df) // 24)
        ax.set_xticks(np.arange(0, len(hist_df), tick_step))
        ax.set_xticklabels(hist_df["bin"].iloc[::tick_step], rotation=45, ha="right")
        ax.grid(True, axis="y", linewidth=0.3, alpha=0.4)
        fig.tight_layout()
        fig.savefig(args.outdir / "fig_g_global_delta_histogram.png", dpi=300)
        plt.close(fig)

    stats, heatmap = window_stats(access_ids, vpns, args.window, args.heatmap_delta_max)
    stats.to_csv(args.outdir / "vpn_delta_window_stats.csv", index=False)
    heatmap.to_csv(args.outdir / "vpn_delta_window_heatmap.csv", index=False)

    if not stats.empty:
        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.plot(stats["access_start"], stats["delta_top1_coverage"], label="top1", linewidth=0.9)
        ax.plot(stats["access_start"], stats["delta_top4_coverage"], label="top4", linewidth=0.9)
        ax.plot(stats["access_start"], stats["delta_top8_coverage"], label="top8", linewidth=0.9)
        ax.set_xlabel(f"{args.stream_label} access id")
        ax.set_ylabel("Windowed VPN delta coverage")
        ax.set_ylim(0, 1.02)
        ax.set_title("Windowed VPN delta coverage")
        ax.grid(True, linewidth=0.3, alpha=0.4)
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(args.outdir / "fig_d_windowed_vpn_delta_coverage.png", dpi=300)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.plot(stats["access_start"], stats["delta_zero_ratio"], label="delta=0", linewidth=0.9)
        ax.plot(stats["access_start"], stats["delta_plus1_ratio"], label="delta=+1", linewidth=0.9)
        ax.plot(stats["access_start"], stats["delta_minus1_ratio"], label="delta=-1", linewidth=0.9)
        ax.set_xlabel(f"{args.stream_label} access id")
        ax.set_ylabel("Windowed ratio")
        ax.set_ylim(0, 1.02)
        ax.set_title("Windowed VPN delta breakdown")
        ax.grid(True, linewidth=0.3, alpha=0.4)
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(args.outdir / "fig_d2_windowed_vpn_delta_breakdown.png", dpi=300)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.stackplot(
            stats["access_start"],
            stats["delta_zero_ratio"],
            stats["delta_plus1_ratio"],
            stats["delta_minus1_ratio"],
            stats["delta_small_jump_ratio"],
            stats["delta_medium_jump_ratio"],
            stats["delta_large_jump_ratio"],
            labels=[
                "delta=0",
                "delta=+1",
                "delta=-1",
                "small-jump: |d|<=4, excl. 0,+/-1",
                "medium-jump: 4<|d|<=16",
                "large-jump: |d|>16",
            ],
            colors=["#4c78a8", "#59a14f", "#f28e2b", "#b07aa1", "#edc948", "#9d7660"],
            alpha=0.9,
        )
        ax.set_xlabel(f"{args.stream_label} access id")
        ax.set_ylabel("Windowed ratio")
        ax.set_ylim(0, 1.0)
        ax.set_title("Windowed VPN delta basic breakdown")
        ax.grid(True, linewidth=0.3, alpha=0.4)
        ax.legend(loc="upper right")
        fig.tight_layout()
        fig.savefig(args.outdir / "fig_e_windowed_delta_ratio_stacked_area.png", dpi=300)
        plt.close(fig)

    if not heatmap.empty:
        delta_cols = list(range(-args.heatmap_delta_max, args.heatmap_delta_max + 1))
        matrix = heatmap[delta_cols].to_numpy(dtype=float).T
        fig, ax = plt.subplots(figsize=(13, 5.4))
        image = ax.imshow(
            matrix,
            origin="lower",
            aspect="auto",
            interpolation="nearest",
            extent=[0, len(heatmap), -args.heatmap_delta_max - 0.5, args.heatmap_delta_max + 0.5],
        )
        ax.set_xlabel("Window index")
        ax.set_ylabel("Adjacent raw VPN delta")
        ax.set_title(f"Windowed VPN delta heatmap, delta in +/-{args.heatmap_delta_max}")
        ax.set_yticks(np.arange(-args.heatmap_delta_max, args.heatmap_delta_max + 1, max(1, args.heatmap_delta_max // 4)))
        cbar = fig.colorbar(image, ax=ax)
        cbar.set_label("Ratio within window")
        fig.tight_layout()
        fig.savefig(args.outdir / "fig_f_windowed_delta_heatmap.png", dpi=300)
        plt.close(fig)

    summary = pd.DataFrame(
        [
            {
                "input": str(args.input),
                "num_accesses": int(len(df)),
                "unique_vpn": int(df["vpn"].nunique()),
                "num_adjacent_deltas": int(len(deltas)),
                "window": int(args.window),
            }
        ]
    )
    summary.to_csv(args.outdir / "vpn_trace_summary.csv", index=False)
    print(summary.to_string(index=False))
    print(f"[INFO] Wrote plots and tables to {args.outdir}")


if __name__ == "__main__":
    main()
