"""A Mapping of bundled thumbnail keys to lazily read base64 strings.

The distributed JSON remains unchanged. A small, versioned byte-offset sidecar
under user-data avoids decoding/retaining image bodies during list requests.
"""
from collections.abc import Mapping
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile


class _ByteWindow:
    """Bounded streaming view. bytes.find is faster than mmap.find on Windows."""
    BLOCK = 4 * 1024 * 1024

    def __init__(self, handle, size):
        self.handle, self.size = handle, size
        self.start, self.valid = -1, 0
        self.chunk = bytearray(self.BLOCK)

    def __len__(self):
        return self.size

    def _load(self, position):
        if not self.start <= position < self.start + self.valid:
            self.start = position // self.BLOCK * self.BLOCK
            self.handle.seek(self.start)
            self.valid = self.handle.readinto(self.chunk)

    def __getitem__(self, position):
        if isinstance(position, slice):
            self._load(position.start)
            if position.stop <= self.start + self.valid:
                return self.chunk[position.start-self.start:position.stop-self.start]
            self.handle.seek(position.start)
            return self.handle.read(position.stop-position.start)
        if not 0 <= position < self.size:
            raise ValueError('Truncated preview JSON')
        self._load(position)
        return self.chunk[position-self.start]

    def find(self, value, position):
        while position < self.size:
            self._load(position)
            offset = self.chunk.find(value, position-self.start, self.valid)
            if offset >= 0:
                return self.start + offset
            position = self.start + self.valid
        return -1


    _PAIR = re.compile(rb'\s*,?\s*("(?:[^"\\]|\\.)*")\s*:\s*(")')

    def scan_thumbs(self, position):
        result = {}
        while position < self.size:
            self._load(position)
            chunk, base = self.chunk, self.start
            match = self._PAIR.match(chunk, position-base, self.valid)
            if match is None:
                # Rare boundary-spanning key: copy only its small header.
                length = 4096
                while True:
                    chunk = self[position:min(self.size, position+length)]
                    base = position
                    match = self._PAIR.match(chunk)
                    if match is not None:
                        break
                    if chunk.lstrip().startswith(b'}'):
                        return result
                    if position+length >= self.size or len(chunk.rstrip()) < length:
                        raise ValueError('Invalid thumbnail JSON member')
                    length *= 2
            raw_key = match[1]
            key = (raw_key[1:-1].decode('utf-8') if b'\\' not in raw_key
                   else json.loads(raw_key))
            start = base + match.start(2)
            end = start
            while True:
                end = self.find(b'"', end+1)
                if end < 0:
                    raise ValueError('Unterminated thumbnail JSON string')
                slash = end-1
                while slash > start and self[slash] == 92:
                    slash -= 1
                if (end-1-slash) % 2 == 0:
                    break
            result[key] = [start, end+1]
            position = end+1
        raise ValueError('Unterminated thumbnail JSON object')


class PreviewKeyIndex(Mapping):
    def __init__(self, path, cache_path=None, *, cache_write=True):
        self.path = Path(path)
        self.offsets = {}
        self.reused = False
        self.cache_path = Path(cache_path) if cache_path is not None else None
        self.cache_write = cache_write
        self._repair_attempted = False
        try:
            stat = self.path.stat()
        except OSError:
            self.signature = None
            return
        self.signature = [str(self.path.resolve()), stat.st_size, stat.st_mtime_ns]
        if cache_path is not None:
            try:
                data = json.loads(Path(cache_path).read_text(encoding='utf-8'))
                offsets = data['offsets']
                if (data.get('schema') == 3 and data.get('signature') == self.signature
                        and self._valid_offsets(offsets, data.get('count'), stat.st_size,
                                                data.get('keys_sha1'))):
                    self.offsets = offsets
                    self.reused = True
                    return
            except (OSError, ValueError, KeyError, TypeError):
                pass
        self._rebuild()

    @staticmethod
    def _keys_sha1(offsets):
        keys = json.dumps(list(offsets), ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha1(keys.encode('utf-8')).hexdigest()

    def _valid_offsets(self, offsets, count, size, keys_sha1):
        if not isinstance(offsets, dict) or type(count) is not int or count != len(offsets):
            return False
        if keys_sha1 != self._keys_sha1(offsets):
            return False
        previous_end = 0
        for key, span in offsets.items():
            if not (isinstance(key, str) and isinstance(span, list) and len(span) == 2
                    and all(type(x) is int for x in span)
                    and previous_end <= span[0] < span[1] <= size):
                return False
            previous_end = span[1]
        # Decode evenly spaced samples, checking their owning key as well as the body.
        entries = list(offsets.items())
        with self.path.open('rb') as handle:
            for i in sorted({n * (len(entries) - 1) // 4 for n in range(5)} if entries else set()):
                key, (start, end) = entries[i]
                header_start = max(0, start - (len(key.encode('utf-8')) * 6 + 64))
                handle.seek(header_start)
                header = handle.read(start - header_start)
                match = re.search(rb'("(?:[^"\\]|\\.)*")\s*:\s*$', header)
                if match is None or json.loads(match[1]) != key:
                    return False
                self._decode(handle.read(end - start))
        return True

    @staticmethod
    def _decode(body):
        value = json.loads(body)
        if not isinstance(value, str):
            raise ValueError('Preview body must be a base64 string')
        base64.b64decode(value, validate=True)
        return value

    def _rebuild(self):
        # Discard the suspect mapping before scanning; never retry this recursively.
        self.offsets = {}
        self.reused = False
        with self.path.open('rb') as handle:
            stat = os.fstat(handle.fileno())
            signature = [str(self.path.resolve()), stat.st_size, stat.st_mtime_ns]
            if signature != self.signature:
                raise ValueError('Preview bundle changed while indexing')
            offsets = self._scan(_ByteWindow(handle, stat.st_size)) if stat.st_size else {}
        self.offsets = offsets
        if self.cache_path is not None and self.cache_write:
            self._save(self.cache_path)

    @staticmethod
    def _scan(body):
        # Skip string bodies with bounded bytes.find (C), without allocating base64 text.
        def space(pos):
            while pos < len(body) and body[pos] in b' \t\r\n':
                pos += 1
            return pos
        def string_end(pos):
            end = pos
            while True:
                end = body.find(b'"', end + 1)
                if end < 0:
                    raise ValueError('Unterminated preview JSON string')
                slash = end - 1
                while slash > pos and body[slash] == 92:
                    slash -= 1
                if (end - 1 - slash) % 2 == 0:
                    return end + 1
        def skip(pos):
            pos = space(pos)
            if body[pos] == 34:
                return string_end(pos)
            if body[pos] in (123, 91):
                close = 125 if body[pos] == 123 else 93
                pos = space(pos + 1)
                while body[pos] != close:
                    pos = space(skip(pos))
                    if body[pos] in (44, 58):
                        pos = space(pos + 1)
                return pos + 1
            while pos < len(body) and body[pos] not in b',}] \t\r\n':
                pos += 1
            return pos
        pos = space(0)
        if body[pos] != 123:
            raise ValueError('Preview JSON must be an object')
        pos = space(pos + 1)
        while body[pos] != 125:
            end = string_end(pos)
            key = json.loads(body[pos:end])
            pos = space(end)
            if body[pos] != 58:
                raise ValueError('Invalid preview JSON key')
            pos = space(pos + 1)
            if key == 'thumbs':
                if body[pos] != 123:
                    return {}
                return body.scan_thumbs(pos + 1)
            pos = space(skip(pos))
            if body[pos] == 44:
                pos = space(pos + 1)
        return {}

    def _save(self, path):
        temp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                             prefix=path.name, suffix='.tmp', delete=False) as handle:
                temp = handle.name
                json.dump({'schema': 3, 'signature': self.signature, 'count': len(self.offsets),
                           'keys_sha1': self._keys_sha1(self.offsets), 'offsets': self.offsets},
                          handle, ensure_ascii=False, separators=(',', ':'))
            os.replace(temp, path)
        except OSError:
            pass  # A read-only user directory must not break thumbnail lookup.
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)

    def __len__(self):
        return len(self.offsets)

    def __iter__(self):
        return iter(self.offsets)

    def __contains__(self, key):
        return key in self.offsets

    def _read(self, key):
        start, end = self.offsets[key]
        with self.path.open('rb') as handle:
            stat = os.fstat(handle.fileno())
            if [str(self.path.resolve()), stat.st_size, stat.st_mtime_ns] != self.signature:
                raise KeyError(key)  # Never read an old offset from a replaced bundle.
            handle.seek(start)
            return self._decode(handle.read(end-start))

    def __getitem__(self, key):
        try:
            return self._read(key)
        except (OSError, ValueError, TypeError, KeyError):
            if self._repair_attempted:
                raise KeyError(key) from None
            self._repair_attempted = True
            try:
                self._rebuild()
                return self._read(key)
            except KeyError:
                # A genuinely absent key must not erase the rebuilt valid mapping.
                raise KeyError(key) from None
            except (OSError, ValueError, TypeError):
                self.offsets = {}
                raise KeyError(key) from None
