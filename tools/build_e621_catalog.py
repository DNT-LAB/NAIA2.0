"""Import/export/verify E621 translations only; e621_data is already source.

CLI names retain the stage-1 interface. No operation rewrites e621_data.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.e621_catalog_format import CATALOG_SCHEMA, load_catalog, rows_json, text_digest


def translation_table(rows, manifest):
    import pyarrow as pa

    schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(manifest["translation_arrow_schema"])))
    if any(set(row) != set(schema.names) for row in rows):
        raise ValueError("translation fields differ from Arrow schema")
    return pa.Table.from_pylist(rows, schema=schema)


def import_legacy(data_dir: Path, output: Path, revision: str = "") -> dict:
    import pyarrow.parquet as pq

    if output.exists():
        raise ValueError("catalog output must not already exist")
    table = pq.read_table(data_dir / "e621_KR_tags.parquet")
    blob = rows_json(table.to_pylist()).encode("utf-8")
    manifest = {
        "schema": CATALOG_SCHEMA, "site": "e621", "source_revision": revision,
        "assets": {"translations.json": {"sha256_lf": text_digest(blob)}},
        "counts": {"translations": table.num_rows},
        "translation_arrow_schema": base64.b64encode(table.schema.serialize().to_pybytes()).decode("ascii"),
    }
    output.mkdir(parents=True)
    (output / "translations.json").write_bytes(blob)
    (output / "manifest.json").write_bytes((json.dumps(manifest, ensure_ascii=True, indent=2) + "\n").encode())
    load_catalog(output)
    return manifest


def export_legacy(catalog: Path, output: Path) -> dict:
    import pyarrow.parquet as pq

    if output.exists():
        raise ValueError("export output must not already exist")
    rows, manifest = load_catalog(catalog)
    table = translation_table(rows, manifest)
    output.mkdir(parents=True)
    pq.write_table(table, output / "e621_KR_tags.parquet")
    return {"counts": manifest["counts"]}


def verify_legacy(catalog: Path, output: Path) -> dict:
    import pyarrow.parquet as pq

    rows, manifest = load_catalog(catalog)
    expected = translation_table(rows, manifest)
    if not expected.equals(pq.read_table(output / "e621_KR_tags.parquet"), check_metadata=True):
        raise ValueError("translation projection is stale or differs from source catalog")
    return {"ok": True, "counts": manifest["counts"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["import-legacy", "export-legacy", "verify-legacy"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-revision", default="")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if args.operation != "verify-legacy" and (source == output or output in source.parents):
        parser.error("output must not overwrite the input directory")
    if args.operation == "import-legacy":
        value = import_legacy(source, output, args.source_revision)
    elif args.operation == "export-legacy":
        value = export_legacy(source, output)
    else:
        value = verify_legacy(source, output)
    print(json.dumps({"operation": args.operation, "ok": True, "counts": value["counts"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
