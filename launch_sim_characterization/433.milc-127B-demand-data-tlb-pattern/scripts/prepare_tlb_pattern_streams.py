#!/usr/bin/env python3

import argparse
import csv
import json
import os
import tempfile
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


def insert_after(fields: list[str], anchor: str, new_field: str) -> list[str]:
    result = list(fields)
    result.insert(result.index(anchor) + 1, new_field)
    return result


def temporary_csv(destination: Path) -> tuple[Path, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, text=True)
    return Path(name), os.fdopen(fd, "w", encoding="utf-8", newline="")


def derive_streams(input_csv: Path, stlb_access_csv: Path, stlb_miss_csv: Path) -> dict[str, int]:
    access_tmp, access_file = temporary_csv(stlb_access_csv)
    miss_tmp, miss_file = temporary_csv(stlb_miss_csv)
    counts = {"dtlb_access": 0, "stlb_access": 0, "stlb_miss": 0, "stlb_merge": 0}
    per_core_access: dict[str, int] = {}
    per_core_miss: dict[str, int] = {}

    try:
        with input_csv.open(encoding="utf-8", newline="") as input_file, access_file, miss_file:
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

            access_fields = insert_after(reader.fieldnames, "load_tlb_seq", "stlb_access_seq")
            miss_fields = insert_after(access_fields, "stlb_access_seq", "stlb_miss_seq")
            access_writer = csv.DictWriter(access_file, fieldnames=access_fields)
            miss_writer = csv.DictWriter(miss_file, fieldnames=miss_fields)
            access_writer.writeheader()
            miss_writer.writeheader()

            for row in reader:
                cpu = row["cpu"]
                counts["dtlb_access"] += 1
                if row["stlb_accessed"] != "1":
                    continue

                access_row = dict(row)
                access_row["stlb_access_seq"] = str(per_core_access.get(cpu, 0))
                access_writer.writerow(access_row)
                per_core_access[cpu] = per_core_access.get(cpu, 0) + 1
                counts["stlb_access"] += 1
                if row["stlb_merged"] == "1":
                    counts["stlb_merge"] += 1

                if row["stlb_result"] == "MISS":
                    miss_row = dict(access_row)
                    miss_row["stlb_miss_seq"] = str(per_core_miss.get(cpu, 0))
                    miss_writer.writerow(miss_row)
                    per_core_miss[cpu] = per_core_miss.get(cpu, 0) + 1
                    counts["stlb_miss"] += 1

        os.replace(access_tmp, stlb_access_csv)
        os.replace(miss_tmp, stlb_miss_csv)
    except Exception:
        access_tmp.unlink(missing_ok=True)
        miss_tmp.unlink(missing_ok=True)
        raise

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
            "origin_scope": "real demand data load only",
            "physical_address_fields_present": physical_address_fields_present,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive demand-data STLB access and STLB miss streams from the DTLB event log.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source-metadata", required=True, type=Path)
    parser.add_argument("--stlb-access-dir", required=True, type=Path)
    parser.add_argument("--stlb-miss-dir", required=True, type=Path)
    args = parser.parse_args()

    access_csv = args.stlb_access_dir / "stlb_access_core_0.csv"
    miss_csv = args.stlb_miss_dir / "stlb_miss_core_0.csv"
    with args.input.open(encoding="utf-8", newline="") as input_file:
        source_fields = set(next(csv.reader(input_file)))
    physical_address_fields_present = PHYSICAL_FIELDS <= source_fields
    counts = derive_streams(args.input, access_csv, miss_csv)
    write_stream_metadata(args.source_metadata, args.stlb_access_dir, "stlb_access", "stlb_access_seq", counts["stlb_access"], counts["dtlb_access"], physical_address_fields_present)
    write_stream_metadata(args.source_metadata, args.stlb_miss_dir, "stlb_miss", "stlb_miss_seq", counts["stlb_miss"], counts["dtlb_access"], physical_address_fields_present)

    summary = "\n".join(f"{key} {value}" for key, value in counts.items()) + "\n"
    (args.stlb_access_dir / "stream_summary.txt").write_text(summary, encoding="utf-8")
    (args.stlb_miss_dir / "stream_summary.txt").write_text(summary, encoding="utf-8")
    print(
        f"[PASS] Derived real demand-data streams: DTLB access={counts['dtlb_access']:,}, "
        f"STLB access={counts['stlb_access']:,}, STLB miss={counts['stlb_miss']:,}, STLB merge={counts['stlb_merge']:,}"
    )


if __name__ == "__main__":
    main()
