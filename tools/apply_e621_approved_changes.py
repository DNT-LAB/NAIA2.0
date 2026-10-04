"""Apply a hash-bound approval ledger to E621 sources and their Parquet export.

All validation/export happens in an owned staging directory before publication.
Caught publication failures restore the original bytes. Run with the application
closed: multiple flat files cannot offer power-loss atomicity to live readers.
The ledger schema and examples are in docs/e621_approved_write_contract.ko.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.e621_catalog_format import _unique_object, load_catalog, rows_json, text_digest
from core.site_tag_repository import walk_legacy_tags
from tools.build_e621_catalog import export_legacy, verify_legacy

SCHEMA = "naia.e621-approved-changes.v1"
INPUTS = (
    "e621_data", "e621_catalog/translations.json", "e621_catalog/manifest.json",
    "e621_KR_tags.parquet", "e621_research_annotations.json",
)


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def json_bytes(value, original: bytes, indent=2) -> bytes:
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    if original.endswith(b"\n"):
        text += "\n"
    return text.encode("utf-8").replace(b"\n", b"\r\n" if b"\r\n" in original else b"\n")


def at_path(tree, path):
    if not isinstance(path, list) or not path or not all(isinstance(p, str) and p for p in path):
        raise ValueError("invalid taxonomy path")
    for part in path:
        if not isinstance(tree, dict) or part not in tree:
            raise ValueError("taxonomy path does not exist")
        tree = tree[part]
    if not isinstance(tree, list):
        raise ValueError("taxonomy target must be a tag list")
    return tree


def apply_records(tree, translations, annotations, changes, reviewer):
    """Mutate isolated structures only; site identity and memberships stay exact."""
    if not isinstance(changes, list) or not changes:
        raise ValueError("changes must be a nonempty list")
    native = {}
    for path, row in walk_legacy_tags(tree):
        native.setdefault(row["tag"], []).append((path, row))
    translated = {row["tag"]: row for row in translations}
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) - {"site", "exact_tag", "decision", "move", "korean", "native_body_sha256", "evidence"}:
            raise ValueError("unknown change fields")
        tag = change.get("exact_tag")
        if change.get("site") != "e621" or change.get("decision") != "approve" or tag not in native or tag in seen:
            raise ValueError("invalid, duplicate, or unapproved site-qualified tag")
        seen.add(tag)
        memberships = native[tag]
        row = memberships[0][1]
        if any(other != row for _, other in memberships):
            raise ValueError("conflicting native memberships")
        move, korean = change.get("move"), change.get("korean")
        if not move and not korean:
            raise ValueError("empty approved change")
        if move:
            if not isinstance(move, dict) or set(move) != {"from", "to"}:
                raise ValueError("invalid move")
            old, new = move["from"], move["to"]
            source, target = at_path(tree, old), at_path(tree, new)
            if old == new or old[0] != new[0] or old[0] not in {"General", "Species"}:
                raise ValueError("invalid move domain")
            matching = [value for path, value in memberships if list(path) == old]
            if len(matching) != 1 or any(value.get("tag") == tag for value in target):
                raise ValueError("ambiguous move or occupied target")
            source.remove(matching[0])
            target.append(matching[0])
            if tag in translated and len(new) > 1:
                translated[tag]["category"] = new[1]
        if korean:
            if not isinstance(korean, dict) or set(korean) - {"label", "keywords", "description"}:
                raise ValueError("invalid Korean fields")
            body = str(row.get("wiki_body") or "")
            if not body or digest(body.encode()) != change.get("native_body_sha256"):
                raise ValueError("Korean review evidence body mismatch")
            evidence = change.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError("Korean review requires evidence")
            for item in evidence:
                if (not isinstance(item, dict) or item.get("site") != "e621"
                        or item.get("body_sha256") != change["native_body_sha256"]
                        or not isinstance(item.get("url"), str) or not item["url"]
                        or not isinstance(item.get("quote"), str) or not item["quote"] or item["quote"] not in body):
                    raise ValueError("Korean review source mismatch")
            for key, value in korean.items():
                valid = (isinstance(value, list) and all(isinstance(s, str) and s.strip() for s in value)
                         if key == "keywords" else isinstance(value, str))
                if not valid:
                    raise ValueError("invalid Korean field value")
            if "label" in korean:
                for _, value in memberships:
                    value["kor"] = korean["label"]
            if "keywords" in korean or "description" in korean:
                if tag not in translated:
                    entry = {"tag": tag, "count": int(row.get("count") or 0),
                             "category": (move["to"] if move else list(memberships[0][0]))[1],
                             "desc": "", "keywords": ""}
                    translations.append(entry)
                    translated[tag] = entry
                if "description" in korean:
                    translated[tag]["desc"] = korean["description"]
                if "keywords" in korean:
                    translated[tag]["keywords"] = ", ".join(korean["keywords"])
            # Existing reviewed supplements must not shadow the approved edit.
            # Bind any edited supplement to the new review, never its old quote.
            for collection in ("descriptions", "korean_search"):
                # A search-term supplement records a review of label/keywords. A description-only
                # approval did not review those, so it must not take over that record's evidence
                # and reviewer (2026-10-04: a body-translation batch re-attributed 123 of them).
                if collection == "korean_search" and not {"label", "keywords"} & set(korean):
                    continue
                for annotation in annotations.get(collection, []):
                    if annotation.get("e621_tag") == tag:
                        annotation.update(sources=evidence, reviewer=reviewer,
                                          e621_body_sha256=change["native_body_sha256"],
                                          native_body_matches_review_source=True)
                        for key, value in korean.items():
                            if key == "description" and collection == "korean_search":
                                continue
                            annotation[key] = (", ".join(value) if key == "keywords" and collection == "descriptions" else value)


def apply_ledger(data_dir: Path, ledger_path: Path, ledger_sha256: str) -> dict:
    data_dir = data_dir.resolve()
    ledger_bytes = ledger_path.read_bytes()
    if digest(ledger_bytes) != ledger_sha256:
        raise ValueError("approval ledger hash mismatch")
    ledger = json.loads(ledger_bytes, object_pairs_hook=_unique_object)
    if (not isinstance(ledger, dict) or ledger.get("schema") != SCHEMA or ledger.get("approved") is not True
            or not isinstance(ledger.get("reviewer"), str) or not ledger["reviewer"].strip()):
        raise ValueError("invalid approval ledger")
    if not isinstance(ledger.get("input_sha256"), dict) or set(ledger["input_sha256"]) != set(INPUTS):
        raise ValueError("ledger must bind all source and export inputs")
    originals = {name: (data_dir / name).read_bytes() for name in INPUTS}
    if any(digest(blob) != ledger["input_sha256"][name] for name, blob in originals.items()):
        raise ValueError("input hash mismatch")
    verify_legacy(data_dir / "e621_catalog", data_dir)
    tree = json.loads(originals["e621_data"], object_pairs_hook=_unique_object)
    translations, manifest = load_catalog(data_dir / "e621_catalog")
    annotations = json.loads(originals["e621_research_annotations.json"], object_pairs_hook=_unique_object)
    if annotations.get("schema") != "naia.e621-research-annotations.v1":
        raise ValueError("invalid annotation source")
    apply_records(tree, translations, annotations, ledger.get("changes"), ledger["reviewer"])
    lock_path = data_dir / ".e621-approved-write.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.close(lock_fd)
        with tempfile.TemporaryDirectory(prefix=".e621-write-", dir=data_dir) as temp:
            stage = Path(temp)
            catalog = stage / "e621_catalog"
            catalog.mkdir()
            translation_blob = rows_json(translations).encode()
            translation_blob = translation_blob.replace(b"\n", b"\r\n" if b"\r\n" in originals["e621_catalog/translations.json"] else b"\n")
            manifest["assets"]["translations.json"]["sha256_lf"] = text_digest(translation_blob)
            manifest["counts"] = {"translations": len(translations)}
            manifest["last_approval"] = {"sha256": ledger_sha256, "reviewer": ledger["reviewer"]}
            (catalog / "translations.json").write_bytes(translation_blob)
            (catalog / "manifest.json").write_bytes(json_bytes(manifest, originals["e621_catalog/manifest.json"]))
            export_legacy(catalog, stage / "export")
            verify_legacy(catalog, stage / "export")
            outputs = {
                "e621_data": json_bytes(tree, originals["e621_data"], indent=1),
                "e621_catalog/translations.json": translation_blob,
                "e621_catalog/manifest.json": (catalog / "manifest.json").read_bytes(),
                "e621_KR_tags.parquet": (stage / "export/e621_KR_tags.parquet").read_bytes(),
                "e621_research_annotations.json": json_bytes(annotations, originals["e621_research_annotations.json"]),
            }
            # Compare again under the cooperative lock before replacing files.
            if any((data_dir / name).read_bytes() != blob for name, blob in originals.items()):
                raise ValueError("inputs changed during staging")
            changed = [name for name in INPUTS if outputs[name] != originals[name]]
            for i, name in enumerate(changed):
                (stage / f"old-{i}").write_bytes(originals[name])
                (stage / f"new-{i}").write_bytes(outputs[name])
            replaced = []
            try:
                for i, name in enumerate(changed):
                    os.replace(stage / f"new-{i}", data_dir / name)
                    replaced.append((i, name))
                verify_legacy(data_dir / "e621_catalog", data_dir)
            except BaseException:
                for i, name in reversed(replaced):
                    os.replace(stage / f"old-{i}", data_dir / name)
                raise
            return {"ok": True, "approval_sha256": ledger_sha256, "changed": changed,
                    "output_sha256": {name: digest(outputs[name]) for name in INPUTS}}
    finally:
        lock_path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--ledger-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(apply_ledger(args.data_dir, args.ledger, args.ledger_sha256), ensure_ascii=True))


if __name__ == "__main__":
    main()
