"""Separate editable wiki-body source and a small-row-group reading projection."""
from __future__ import annotations

import bisect
import re
from pathlib import Path

SOURCE_NAME = "wiki_bodies.json"
PARQUET_NAME = "e621_KR_wiki_bodies.parquet"
ROW_GROUP_SIZE = 128
FIELDS = {"tag", "body_ko", "native_body_sha256", "translator"}
PROJECTION_FIELDS = ["tag", "body_ko", "native_body_sha256"]


def validate_body_rows(rows):
    if not isinstance(rows, list):
        raise ValueError("wiki bodies must be a list")
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != FIELDS or
                not all(isinstance(v, str) for v in row.values()) or
                not row["tag"] or row["tag"] in seen or not row["body_ko"].strip() or
                not row["translator"].strip() or
                not re.fullmatch(r"[0-9a-f]{64}", row["native_body_sha256"])):
            raise ValueError("invalid or duplicate wiki body record")
        seen.add(row["tag"])
    return rows


def body_table(rows):
    import pyarrow as pa
    validate_body_rows(rows)
    schema = pa.schema([(name, pa.string()) for name in PROJECTION_FIELDS])
    return pa.Table.from_pylist(sorted(rows, key=lambda row: row["tag"]), schema=schema)


def export_bodies(rows, path: Path):
    import pyarrow.parquet as pq
    pq.write_table(body_table(rows), path, row_group_size=ROW_GROUP_SIZE, compression="zstd",
                   write_statistics=["tag", "native_body_sha256"])


class WikiBodyReader:
    """Startup reads tag/hash columns only. A selection decodes just its row group."""
    def __init__(self, path: Path):
        import pyarrow as pa
        import pyarrow.parquet as pq
        self.parquet = pq.ParquetFile(path)
        if self.parquet.schema_arrow != pa.schema([(name, pa.string()) for name in PROJECTION_FIELDS]):
            raise ValueError("invalid wiki body projection schema")
        columns = self.parquet.read(columns=["tag", "native_body_sha256"], use_threads=False)
        tags = columns.column("tag").to_pylist()
        self.hashes = columns.column("native_body_sha256").to_pylist()
        self.index = {}
        self.offsets = []
        total = 0
        for group in range(self.parquet.num_row_groups):
            self.offsets.append(total)
            total += self.parquet.metadata.row_group(group).num_rows
        previous = None
        digest_pattern = re.compile(r"[0-9a-f]{64}")
        for index, (tag, digest) in enumerate(zip(tags, self.hashes)):
            if (not isinstance(tag, str) or not tag or (previous is not None and tag <= previous)
                    or not isinstance(digest, str) or not digest_pattern.fullmatch(digest)):
                raise ValueError("invalid, unsorted or duplicate wiki body index")
            self.index[tag] = index
            previous = tag
        # The retained index owns Python strings only. Release Arrow's temporary
        # tag/hash buffers after both the short-description and body-index reads.
        del columns, tags
        pa.default_memory_pool().release_unused()

    def read(self, tag: str) -> str:
        entry = self.index.get(tag)
        if entry is None:
            return ""
        index, digest = entry, self.hashes[entry]
        group = bisect.bisect_right(self.offsets, index) - 1
        table = self.parquet.read_row_group(group, columns=PROJECTION_FIELDS)
        row = table.slice(index - self.offsets[group], 1).to_pylist()[0]
        if row["tag"] != tag or row["native_body_sha256"] != digest:
            raise ValueError("wiki body projection changed after indexing")
        text = row["body_ko"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty wiki body projection")
        return text
