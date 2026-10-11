"""Build the offline character-parts catalogue; semantic decisions live in rules.

Only the generated MJS data literals are parsed, never executed. Thumbnail values
are streamed past without decoding or retaining the image payloads.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import re
import sys


AXES_PATH = "app/web/remote/js/features/interactiveAxes.mjs"
RULES_PATH = "tools/character_parts_rules.json"
CATALOG_PATH = "data/character_parts.json"
TSV_PATH = "docs/character_parts_verdicts.tsv"
REASONS = {"state", "scene", "composition", "action", "multi", "franchise",
           "not_carriable", "fragment", "meta", "duplicate", "state_or_design", "out_of_scope"}


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + ascii(key))
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


class LiteralParser:
    """Small, fail-closed parser for the emitter's JS data literals."""

    def __init__(self, text, pos=0):
        self.text, self.pos = text, pos

    def space(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def value(self):
        self.space()
        char = self.text[self.pos]
        if char in "\"'":
            quote = char
            self.pos += 1
            out = []
            while self.pos < len(self.text):
                char = self.text[self.pos]
                self.pos += 1
                if char == quote:
                    return "".join(out)
                if char != "\\":
                    out.append(char)
                    continue
                esc = self.text[self.pos]
                self.pos += 1
                if esc == "u":
                    if self.text[self.pos] == "{":
                        end = self.text.index("}", self.pos)
                        out.append(chr(int(self.text[self.pos + 1:end], 16)))
                        self.pos = end + 1
                    else:
                        out.append(chr(int(self.text[self.pos:self.pos + 4], 16)))
                        self.pos += 4
                else:
                    out.append({"n": "\n", "r": "\r", "t": "\t", "b": "\b",
                                "f": "\f", "\\": "\\", "\"": "\"", "'": "'",
                                "/": "/"}[esc])
            raise ValueError("Unterminated MJS string")
        if char in "[{":
            is_object = char == "{"
            end = "}" if is_object else "]"
            self.pos += 1
            result = {} if is_object else []
            self.space()
            while self.text[self.pos] != end:
                if is_object:
                    if self.text[self.pos] in "\"'":
                        key = self.value()
                    else:
                        match = re.match(r"[A-Za-z_$][\w$]*", self.text[self.pos:])
                        if not match:
                            raise ValueError("Invalid MJS object key")
                        key = match[0]
                        self.pos += len(key)
                    self.space()
                    if self.text[self.pos] != ":" or key in result:
                        raise ValueError("Invalid or duplicate MJS object key")
                    self.pos += 1
                    result[key] = self.value()
                else:
                    result.append(self.value())
                self.space()
                if self.text[self.pos] == end:
                    break
                if self.text[self.pos] != ",":
                    raise ValueError("Unsupported MJS literal separator")
                self.pos += 1
                self.space()
            self.pos += 1
            return result
        match = re.match(r"(?:true|false|null|-?\d+(?:\.\d+)?)\b", self.text[self.pos:])
        if not match:
            raise ValueError("Unsupported MJS literal at " + str(self.pos))
        self.pos += len(match[0])
        return json.loads(match[0])


def read_sources(root):
    text = (root / AXES_PATH).read_text(encoding="utf-8")
    def exported(name):
        match = re.search(r"^export const " + re.escape(name) + r"\s*=\s*", text, re.M)
        if not match:
            raise ValueError("Missing MJS export: " + name)
        return LiteralParser(text, match.end()).value()
    palettes = exported("PALETTES")
    sliders = exported("SLIDERS")
    thumbs = exported("THUMB_TAGS")
    slots = exported("CHAR_SLOTS")
    objects = exported("OBJ_SECTIONS")
    sections = {}
    for section in [s for slot in slots for s in slot["sections"]] + objects:
        if "ref" in section:
            sections[section["ref"]] = section
    # Embedded palettes have no standalone section. Reuse their host's label.
    for section in list(sections.values()):
        for field in ("mainPalette", "extraPalette"):
            if field in section and section[field] not in sections:
                ref = section[field]
                sections[ref] = {"ref": ref, "kind": "palette", "label": section["label"]}
    axes = {axis: [{"tag": tag} for tag in tags] for axis, tags in thumbs.items()}
    axes.update({axis: [{"tag": tag} for tag in value["steps"]]
                 for axis, value in sliders.items()})
    axes.update(palettes)
    for axis, entries in axes.items():
        if len({entry["tag"] for entry in entries}) != len(entries):
            raise ValueError("Repeated source tag in axis: " + axis)
    return {"axes": axes, "sections": sections, "sliders": sliders,
            "slots": slots, "objects": objects, "pack_axis": exported("PACK_AXIS")}


class KeyStream:
    """Bounded-memory scanner for a flat JSON object with string values."""

    def __init__(self, stream):
        self.stream, self.buf, self.pos = stream, "", 0

    def peek(self):
        if self.pos == len(self.buf):
            self.buf = self.stream.read(65536)
            self.pos = 0
        return self.buf[self.pos:self.pos + 1]

    def space(self):
        while self.peek() and self.peek().isspace():
            self.pos += 1

    def expect(self, char):
        self.space()
        if self.peek() != char:
            raise ValueError("Invalid thumbnail JSON; expected " + ascii(char))
        self.pos += 1

    def string(self, capture):
        self.expect('"')
        pieces = ['"'] if capture else None
        while self.peek():
            match = re.search(r'["\\]', self.buf[self.pos:])
            end = self.pos + match.start() if match else len(self.buf)
            if capture:
                pieces.append(self.buf[self.pos:end])
            self.pos = end
            if not match:
                continue
            char = self.peek()
            self.pos += 1
            if capture:
                pieces.append(char)
            if char == '"':
                return json.loads("".join(pieces)) if capture else None
            escaped = self.peek()
            if not escaped:
                raise ValueError("Truncated thumbnail escape")
            if capture:
                pieces.append(escaped)
            self.pos += 1
        raise ValueError("Truncated thumbnail string")


def thumbnail_keys(path):
    keys = set()
    with path.open(encoding="utf-8") as stream:
        reader = KeyStream(stream)
        reader.expect("{")
        reader.space()
        if reader.peek() != "}":
            while True:
                key = reader.string(True)
                if key in keys:
                    raise ValueError("Repeated thumbnail key: " + ascii(key))
                keys.add(key)
                reader.expect(":")
                reader.string(False)
                reader.space()
                if reader.peek() == "}":
                    break
                reader.expect(",")
        reader.expect("}")
        reader.space()
        if reader.peek():
            raise ValueError("Trailing thumbnail data")
    return keys


def validate_rules(rules, source):
    axes = source["axes"]
    mapped = [a for b in rules["blocks"] for a in b["axes"]]
    audited = rules.get("audit_axes", [])
    scope = mapped + audited
    if len(scope) != len(set(scope)):
        raise ValueError("An axis is assigned more than once")
    if len({b["key"] for b in rules["blocks"]}) != len(rules["blocks"]):
        raise ValueError("Duplicate block key")
    for axis in scope:
        if axis not in axes or axis not in source["sections"]:
            raise ValueError("Unknown or unsectioned axis: " + axis)
    for axis in rules.get("hold_axes", []):
        if axis not in audited:
            raise ValueError("Hold axis must be audited: " + axis)
    defaults = rules.get("axis_default", {})
    overrides = rules.get("tag_overrides", {})
    for axis in defaults.keys() | overrides.keys():
        if axis not in scope:
            raise ValueError("Rule references unknown/inactive axis: " + axis)
    def decision(value):
        if not isinstance(value, dict) or set(value) - {"verdict", "reason", "brand"}:
            raise ValueError("Invalid decision object")
        verdict, reason = value.get("verdict"), value.get("reason")
        if verdict not in {"keep", "drop", "review"}:
            raise ValueError("Invalid verdict")
        if verdict != "keep" and reason not in REASONS:
            raise ValueError("Missing or invalid reason")
        if reason == "state_or_design" and verdict != "review":
            raise ValueError("state_or_design requires review")
        if verdict == "keep" and reason is not None:
            raise ValueError("keep must not have a drop/review reason")
        if "brand" in value and (value["brand"] is not True or verdict != "keep"):
            raise ValueError("brand requires keep and literal true")
    for value in defaults.values():
        decision(value)
        if "brand" in value:
            raise ValueError("brand requires a named tag override")
    for axis, values in overrides.items():
        valid = {entry["tag"] for entry in axes[axis]}
        for tag, value in values.items():
            if tag not in valid:
                raise ValueError("Unknown tag in " + axis + ": " + ascii(tag))
            decision(value)
    for axis in scope:
        for entry in axes[axis]:
            value = overrides.get(axis, {}).get(entry["tag"], defaults.get(axis))
            if value is None:
                raise ValueError("Missing verdict: " + axis + "/" + ascii(entry["tag"]))
            if axis in audited and value["verdict"] != "drop":
                raise ValueError("Audit-only axis cannot publish tags: " + axis)
    return scope


def build(root):
    source = read_sources(root)
    rules = read_json(root / RULES_PATH)
    scope = validate_rules(rules, source)
    dictionary = read_json(root / "data/interactive_tags.json")
    adult = set(read_json(root / "data/interactive_adult_tags.json")["tags"])
    harmony = read_json(root / "data/interactive_clothing_harmony.json")
    thumbs = thumbnail_keys(root / "data/interactive_thumbnails.json")
    hold_source = set(dictionary)
    for axis in rules.get("hold_axes", []):
        hold_source.update(entry["tag"] for entry in source["axes"][axis])
    index, rows, blocks = {}, [], []
    targets = {axis: block["key"] for block in rules["blocks"] for axis in block["axes"]}
    parts = {}
    for axis in scope:
        section = source["sections"][axis]
        kind = section["kind"]
        if kind.startswith("thumb"):
            kind = "thumb"
        if kind not in {"palette", "slider", "thumb"}:
            raise ValueError("Unsupported section kind: " + kind)
        part = {"key": axis, "label": section["label"], "kind": kind,
                "source_axis": axis, "gender": "male" if axis.endswith("_male") else "any",
                "adult": axis.startswith("nsfw_")}
        for key in ("mainPalette", "extraPalette"):
            if key in section:
                part[key] = section[key]
        if kind == "slider" and "default" in source["sliders"][axis]:
            part["default"] = source["sliders"][axis]["default"]
        part["tags"] = []
        for original in source["axes"][axis]:
            tag = original["tag"]
            decision = rules.get("tag_overrides", {}).get(axis, {}).get(
                tag, rules.get("axis_default", {}).get(axis))
            verdict, reason = decision["verdict"], decision.get("reason", "")
            if verdict != "drop" and tag in index:
                verdict, reason = "drop", "duplicate"
            block = targets.get(axis, "")
            freq = dictionary.get(tag, {}).get("freq", "")
            rows.append({"tag": tag, "source_axis": axis, "verdict": verdict,
                         "reason": reason, "block": block, "part": axis, "freq": freq})
            if verdict == "drop":
                continue
            entry = dict(original)
            if tag in dictionary and "freq" in dictionary[tag]:
                entry["freq"] = freq
            thumb = source["pack_axis"].get(axis, axis) + "/" + tag
            if thumb in thumbs:
                entry["thumb"] = thumb
            if tag in adult:
                entry["adult"] = True
            if block in rules.get("region_blocks", []):
                region = harmony["region"].get(tag, harmony["region_weak"].get(tag))
                if region is not None:
                    entry["region"] = region
            if (block == rules.get("hold_block")
                    or [block, axis] in rules.get("hold_parts", [])):
                holding = "holding " + tag
                entry["hold"] = holding if holding in hold_source else None
            if decision.get("brand") is True:
                entry["brand"] = True
            if verdict == "review":
                entry["review"] = reason
            part["tags"].append(entry)
            index[tag] = [block, axis]
        parts[axis] = part
    for extra in rules.get("extra_items", []):
        tag, axis, target = extra["tag"], extra["source_axis"], extra["part"]
        if axis not in source["axes"] or not any(e["tag"] == tag for e in source["axes"][axis]):
            raise ValueError("Unknown extra item source: " + axis + "/" + ascii(tag))
        if tag in index:
            raise ValueError("Extra item already published: " + ascii(tag))
        if target not in parts or targets.get(target) != "item":
            raise ValueError("Extra item target must be an existing item part: " + target)
        holding = "holding " + tag
        if holding not in hold_source:
            raise ValueError("Extra item has no holding source: " + ascii(tag))
        freq = dictionary.get(tag, {}).get("freq", "")
        entry = {"tag": tag, "hold": holding, "freq": freq, "from_axis": axis}
        thumb = axis + "/" + tag
        if thumb in thumbs:
            entry["thumb"] = thumb
        if axis.startswith("nsfw_") or tag in adult:
            entry["adult"] = True
        parts[target]["tags"].append(entry)
        index[tag] = ["item", target]
        rows.append({"tag": tag, "source_axis": axis, "verdict": "keep", "reason": "",
                     "block": "item", "part": target, "freq": freq})
    for block in rules["blocks"]:
        blocks.append({"key": block["key"], "label": block["label"],
                       "parts": [parts[axis] for axis in block["axes"] if parts[axis]["tags"]]})
    all_parts = [part for block in blocks for part in block["parts"]]
    catalog = {"version": 1, "generated_by": "tools/build_character_parts.py",
               "note": ["Generated file. Edit tools/character_parts_rules.json and rebuild."],
               "counts": {"blocks": len(blocks), "parts": len(all_parts), "tags": len(index),
                          "adult_tags": sum(bool(p["adult"] or t.get("adult"))
                                            for p in all_parts for t in p["tags"]),
                          "review": sum("review" in t for p in all_parts for t in p["tags"])},
               "blocks": blocks, "index": index}
    return catalog, rows


def serialized(catalog, rows):
    text = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    tsv = io.StringIO(newline="")
    writer = csv.DictWriter(tsv, fieldnames=["tag", "source_axis", "verdict", "reason", "block", "part", "freq"],
                            delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return {CATALOG_PATH: text, TSV_PATH: tsv.getvalue()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        catalog, rows = build(args.root)
        outputs = serialized(catalog, rows)
        if args.check:
            # 판정표(docs/)는 .gitignore 라 다른 체크아웃에는 없다. 없으면 건너뛴다 - 카탈로그는 반드시 대조한다.
            skipped = [name for name in outputs if name == TSV_PATH and not (args.root / name).is_file()]
            stale = [name for name, text in outputs.items()
                     if name not in skipped
                     and (not (args.root / name).is_file()
                          or (args.root / name).read_bytes() != text.encode("utf-8"))]
            if stale:
                print("STALE: " + ", ".join(stale))
                return 1
            if skipped:
                print("OK: catalog matches inputs (not in this checkout, skipped: " + ", ".join(skipped) + ")")
            else:
                print("OK: catalog and verdicts match inputs")
        else:
            for name, text in outputs.items():
                path = args.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
            print("BUILT: " + json.dumps(catalog["counts"], sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print("ERROR: " + ascii(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
