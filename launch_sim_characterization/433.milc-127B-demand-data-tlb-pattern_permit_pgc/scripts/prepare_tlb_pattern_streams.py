#!/usr/bin/env python3

import argparse
import csv
import heapq
import json
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path


REQUIRED_FIELDS = {
    "cpu",
    "load_tlb_seq",
    "instr_id",
    "operand_index",
    "pc",
    "va",
    "vpn",
    "virtual_region_2m",
    "page_offset_in_region",
    "l1dtlb_result",
    "l1dtlb_merged",
    "stlb_accessed",
    "stlb_result",
    "stlb_merged",
    "completion_state",
}

PHYSICAL_FIELDS = {
    "pa",
    "ppn",
    "physical_region_2m",
    "page_offset_in_physical_region",
    "physical_address_valid",
}

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


def compact_fieldnames(fieldnames: list[str]) -> list[str]:
    return [field for field in fieldnames if field not in COMPACT_DROP_FIELDS]


def compact_sibling(path: Path) -> Path:
    return path.with_name(f"{path.stem}_compact{path.suffix}")


def insert_after(fields: list[str], anchor: str, new_field: str) -> list[str]:
    result = list(fields)
    result.insert(result.index(anchor) + 1, new_field)
    return result


def temporary_csv(destination: Path) -> tuple[Path, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, text=True)
    return Path(name), os.fdopen(fd, "w", encoding="utf-8", newline="")


def write_compact_copy(input_csv: Path, output_csv: Path) -> int:
    """Write an atomic, order-preserving copy without presentation-only fields."""
    if input_csv.resolve() == output_csv.resolve():
        raise ValueError("The compact output must not overwrite the complete CSV")
    output_tmp, output_file = temporary_csv(output_csv)
    row_count = 0
    try:
        with input_csv.open(encoding="utf-8", newline="") as input_file, output_file:
            reader = csv.DictReader(input_file)
            if reader.fieldnames is None:
                raise ValueError(f"Missing CSV header: {input_csv}")
            fields = compact_fieldnames(reader.fieldnames)
            writer = csv.DictWriter(output_file, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                writer.writerow(row)
                row_count += 1
        os.replace(output_tmp, output_csv)
    except Exception:
        output_tmp.unlink(missing_ok=True)
        raise
    return row_count


def write_sorted_chunk(rows: list[dict[str, str]], fieldnames: list[str], directory: Path, sequence_column: str) -> Path:
    rows.sort(key=lambda row: (int(row["cpu"]), int(row[sequence_column])))
    fd, name = tempfile.mkstemp(prefix=".stlb-order.", suffix=".csv", dir=directory, text=True)
    path = Path(name)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_global_seq_ordered_copy(input_csv: Path, output_csv: Path, chunk_size: int = 250_000,
                                  compact_output_csv: Path | None = None) -> int:
    """Write full and optional compact copies ordered by (cpu, global_seq)."""
    if input_csv.resolve() == output_csv.resolve():
        raise ValueError("The global-sequence ordered output must not overwrite the native event log")
    if compact_output_csv is not None and compact_output_csv.resolve() in {input_csv.resolve(), output_csv.resolve()}:
        raise ValueError("The compact DTLB output must use an independent path")

    output_tmp, output_file = temporary_csv(output_csv)
    compact_tmp: Path | None = None
    compact_file = None
    if compact_output_csv is not None:
        compact_tmp, compact_file = temporary_csv(compact_output_csv)
    chunk_paths: list[Path] = []
    row_count = 0
    try:
        with input_csv.open(encoding="utf-8", newline="") as input_file:
            reader = csv.DictReader(input_file)
            if reader.fieldnames is None:
                raise ValueError(f"Missing CSV header: {input_csv}")
            missing = {"cpu", "global_seq"} - set(reader.fieldnames)
            if missing:
                raise ValueError(f"Cannot produce global_seq order; missing: {', '.join(sorted(missing))}")

            buffered: list[dict[str, str]] = []
            for row in reader:
                buffered.append(row)
                row_count += 1
                if len(buffered) >= chunk_size:
                    chunk_paths.append(write_sorted_chunk(buffered, reader.fieldnames, output_csv.parent, "global_seq"))
                    buffered = []
            if buffered:
                chunk_paths.append(write_sorted_chunk(buffered, reader.fieldnames, output_csv.parent, "global_seq"))
            fieldnames = reader.fieldnames

        with output_file, ExitStack() as stack:
            writer = csv.DictWriter(output_file, fieldnames=fieldnames)
            writer.writeheader()
            compact_writer = None
            if compact_file is not None:
                stack.enter_context(compact_file)
                compact_writer = csv.DictWriter(compact_file, fieldnames=compact_fieldnames(fieldnames), extrasaction="ignore")
                compact_writer.writeheader()
            chunk_readers = [csv.DictReader(stack.enter_context(path.open(encoding="utf-8", newline=""))) for path in chunk_paths]
            for row in heapq.merge(*chunk_readers, key=lambda item: (int(item["cpu"]), int(item["global_seq"]))):
                writer.writerow(row)
                if compact_writer is not None:
                    compact_writer.writerow(row)
        os.replace(output_tmp, output_csv)
        if compact_output_csv is not None and compact_tmp is not None:
            os.replace(compact_tmp, compact_output_csv)
    except Exception:
        output_tmp.unlink(missing_ok=True)
        if compact_tmp is not None:
            compact_tmp.unlink(missing_ok=True)
        raise
    finally:
        for path in chunk_paths:
            path.unlink(missing_ok=True)
    return row_count


def derive_streams(input_csv: Path, stlb_access_csv: Path, stlb_miss_csv: Path,
                   stlb_access_compact_csv: Path | None = None,
                   stlb_miss_compact_csv: Path | None = None) -> dict[str, int]:
    access_tmp, access_file = temporary_csv(stlb_access_csv)
    miss_tmp, miss_file = temporary_csv(stlb_miss_csv)
    access_compact_tmp: Path | None = None
    miss_compact_tmp: Path | None = None
    access_compact_file = None
    miss_compact_file = None
    if stlb_access_compact_csv is not None:
        access_compact_tmp, access_compact_file = temporary_csv(stlb_access_compact_csv)
    if stlb_miss_compact_csv is not None:
        miss_compact_tmp, miss_compact_file = temporary_csv(stlb_miss_compact_csv)
    counts = {"dtlb_access": 0, "stlb_access": 0, "stlb_miss": 0, "stlb_merge": 0}
    per_core_access: dict[str, int] = {}
    per_core_miss: dict[str, int] = {}
    chunk_paths: list[Path] = []

    try:
        with input_csv.open(encoding="utf-8", newline="") as input_file:
            reader = csv.DictReader(input_file)
            if reader.fieldnames is None:
                raise ValueError(f"Missing CSV header: {input_csv}")
            missing = sorted(REQUIRED_FIELDS - set(reader.fieldnames))
            if missing:
                raise ValueError(f"Missing required fields in {input_csv}: {', '.join(missing)}")
            present_physical_fields = PHYSICAL_FIELDS & set(reader.fieldnames)
            if present_physical_fields and present_physical_fields != PHYSICAL_FIELDS:
                missing = ", ".join(sorted(PHYSICAL_FIELDS - present_physical_fields))
                raise ValueError(f"Partial physical-address schema in {input_csv}; missing: {missing}")

            sequence_column = "global_seq" if "global_seq" in reader.fieldnames else "load_tlb_seq"
            buffered: list[dict[str, str]] = []
            for row in reader:
                counts["dtlb_access"] += 1
                if row["stlb_accessed"] != "1":
                    continue
                buffered.append(row)
                counts["stlb_access"] += 1
                if row["stlb_merged"] == "1":
                    counts["stlb_merge"] += 1
                if row["stlb_result"] == "MISS":
                    counts["stlb_miss"] += 1
                if len(buffered) >= 250_000:
                    chunk_paths.append(write_sorted_chunk(buffered, reader.fieldnames, stlb_access_csv.parent, sequence_column))
                    buffered = []
            if buffered:
                chunk_paths.append(write_sorted_chunk(buffered, reader.fieldnames, stlb_access_csv.parent, sequence_column))

            access_fields = insert_after(reader.fieldnames, sequence_column, "stlb_access_seq")
            miss_fields = insert_after(access_fields, "stlb_access_seq", "stlb_miss_seq")

        with access_file, miss_file, ExitStack() as stack:
            access_writer = csv.DictWriter(access_file, fieldnames=access_fields)
            miss_writer = csv.DictWriter(miss_file, fieldnames=miss_fields)
            access_writer.writeheader()
            miss_writer.writeheader()
            access_compact_writer = None
            miss_compact_writer = None
            if access_compact_file is not None:
                stack.enter_context(access_compact_file)
                access_compact_writer = csv.DictWriter(
                    access_compact_file, fieldnames=compact_fieldnames(access_fields), extrasaction="ignore"
                )
                access_compact_writer.writeheader()
            if miss_compact_file is not None:
                stack.enter_context(miss_compact_file)
                miss_compact_writer = csv.DictWriter(
                    miss_compact_file, fieldnames=compact_fieldnames(miss_fields), extrasaction="ignore"
                )
                miss_compact_writer.writeheader()

            chunk_readers = [csv.DictReader(stack.enter_context(path.open(encoding="utf-8", newline=""))) for path in chunk_paths]
            ordered_rows = heapq.merge(
                *chunk_readers,
                key=lambda row: (int(row["cpu"]), int(row[sequence_column])),
            )
            for row in ordered_rows:
                cpu = row["cpu"]
                access_row = dict(row)
                access_row["stlb_access_seq"] = str(per_core_access.get(cpu, 0))
                access_writer.writerow(access_row)
                if access_compact_writer is not None:
                    access_compact_writer.writerow(access_row)
                per_core_access[cpu] = per_core_access.get(cpu, 0) + 1

                if row["stlb_result"] == "MISS":
                    miss_row = dict(access_row)
                    miss_row["stlb_miss_seq"] = str(per_core_miss.get(cpu, 0))
                    miss_writer.writerow(miss_row)
                    if miss_compact_writer is not None:
                        miss_compact_writer.writerow(miss_row)
                    per_core_miss[cpu] = per_core_miss.get(cpu, 0) + 1

        os.replace(access_tmp, stlb_access_csv)
        os.replace(miss_tmp, stlb_miss_csv)
        if stlb_access_compact_csv is not None and access_compact_tmp is not None:
            os.replace(access_compact_tmp, stlb_access_compact_csv)
        if stlb_miss_compact_csv is not None and miss_compact_tmp is not None:
            os.replace(miss_compact_tmp, stlb_miss_compact_csv)
    except Exception:
        access_tmp.unlink(missing_ok=True)
        miss_tmp.unlink(missing_ok=True)
        if access_compact_tmp is not None:
            access_compact_tmp.unlink(missing_ok=True)
        if miss_compact_tmp is not None:
            miss_compact_tmp.unlink(missing_ok=True)
        raise
    finally:
        for path in chunk_paths:
            path.unlink(missing_ok=True)

    return counts


def write_stream_metadata(source_metadata: Path, output_dir: Path, stream_kind: str, sequence_column: str, event_count: int,
                          source_event_count: int, physical_address_fields_present: bool) -> None:
    metadata = json.loads(source_metadata.read_text(encoding="utf-8"))
    metadata.update(
        {
            "stream_kind": stream_kind,
            "sequence_column": sequence_column,
            "event_count": event_count,
            "source_dtlb_event_count": source_event_count,
            "origin_scope": "real data demand plus actual vBerti cross-page prefetch DTLB requests",
            "physical_address_fields_present": physical_address_fields_present,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive unified STLB access and STLB miss streams from the DTLB event log.")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--source-metadata", type=Path)
    parser.add_argument("--dtlb-ordered-output", type=Path)
    parser.add_argument("--dtlb-compact-output", type=Path)
    parser.add_argument("--stlb-access-dir", type=Path)
    parser.add_argument("--stlb-miss-dir", type=Path)
    parser.add_argument("--compact-copy-input", type=Path,
                        help="Only write an order-preserving compact copy of this existing CSV")
    parser.add_argument("--compact-copy-output", type=Path)
    args = parser.parse_args()

    if args.compact_copy_input is not None or args.compact_copy_output is not None:
        if args.compact_copy_input is None or args.compact_copy_output is None:
            parser.error("--compact-copy-input and --compact-copy-output must be supplied together")
        count = write_compact_copy(args.compact_copy_input, args.compact_copy_output)
        print(f"[PASS] Wrote compact CSV: {args.compact_copy_output} ({count:,} events)")
        return

    required = {
        "--input": args.input,
        "--source-metadata": args.source_metadata,
        "--dtlb-ordered-output": args.dtlb_ordered_output,
        "--stlb-access-dir": args.stlb_access_dir,
        "--stlb-miss-dir": args.stlb_miss_dir,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")

    assert args.input is not None
    assert args.source_metadata is not None
    assert args.dtlb_ordered_output is not None
    assert args.stlb_access_dir is not None
    assert args.stlb_miss_dir is not None

    access_csv = args.stlb_access_dir / "stlb_access_core_0.csv"
    miss_csv = args.stlb_miss_dir / "stlb_miss_core_0.csv"
    dtlb_compact_csv = args.dtlb_compact_output or compact_sibling(args.dtlb_ordered_output)
    access_compact_csv = compact_sibling(access_csv)
    miss_compact_csv = compact_sibling(miss_csv)
    with args.input.open(encoding="utf-8", newline="") as input_file:
        source_fields = set(next(csv.reader(input_file)))
    physical_address_fields_present = PHYSICAL_FIELDS <= source_fields
    ordered_count = write_global_seq_ordered_copy(
        args.input, args.dtlb_ordered_output, compact_output_csv=dtlb_compact_csv
    )
    counts = derive_streams(
        args.dtlb_ordered_output,
        access_csv,
        miss_csv,
        access_compact_csv,
        miss_compact_csv,
    )
    if ordered_count != counts["dtlb_access"]:
        raise AssertionError("The ordered DTLB copy changed the source event count")
    source_header_has_global_seq = "global_seq" in source_fields
    analysis_sequence_column = "global_seq" if source_header_has_global_seq else "stlb_access_seq"
    miss_analysis_sequence_column = "global_seq" if source_header_has_global_seq else "stlb_miss_seq"
    write_stream_metadata(args.source_metadata, args.stlb_access_dir, "stlb_access", analysis_sequence_column, counts["stlb_access"], counts["dtlb_access"], physical_address_fields_present)
    write_stream_metadata(args.source_metadata, args.stlb_miss_dir, "stlb_miss", miss_analysis_sequence_column, counts["stlb_miss"], counts["dtlb_access"], physical_address_fields_present)

    summary = "\n".join(f"{key} {value}" for key, value in counts.items()) + "\n"
    (args.stlb_access_dir / "stream_summary.txt").write_text(summary, encoding="utf-8")
    (args.stlb_miss_dir / "stream_summary.txt").write_text(summary, encoding="utf-8")
    print(
        f"[PASS] Wrote global-sequence ordered DTLB stream: {args.dtlb_ordered_output} ({ordered_count:,} events)\n"
        f"[PASS] Wrote compact result streams: {dtlb_compact_csv}, {access_compact_csv}, {miss_compact_csv}\n"
        f"[PASS] Derived unified demand + cross-page-vBerti streams: DTLB access={counts['dtlb_access']:,}, "
        f"STLB access={counts['stlb_access']:,}, STLB miss={counts['stlb_miss']:,}, STLB merge={counts['stlb_merge']:,}"
    )


if __name__ == "__main__":
    main()
