"""A Mapping of bundled thumbnail keys to lazily read base64 strings.

The distributed JSON remains unchanged. A small, versioned byte-offset sidecar
under user-data avoids decoding/retaining image bodies during list requests.
"""
from collections.abc import Mapping
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import io
import json
import os
import re
from pathlib import Path
import tempfile


def character_pack_fingerprint(path):
    """Read the install receipt, never hash the large pack on a runtime query."""
    try:
        value = Path(path).with_suffix('.sha256').read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return None
    return value if re.fullmatch(r'[0-9a-f]{64}', value) else None


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
    def __init__(self, path, cache_path=None, *, cache_write=True,
                 extension=False, source_fingerprint=None, validate_images=False):
        self.path = Path(path)
        self.extension = extension
        self.source_fingerprint = source_fingerprint
        self.validate_images = validate_images
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
        if not validate_images and cache_path is not None and (not extension or source_fingerprint is not None):
            try:
                data = json.loads(Path(cache_path).read_text(encoding='utf-8'))
                offsets = data['offsets']
                if (data.get('schema') == 3 and data.get('signature') == self.signature
                        and (not extension or data.get('source_sha256') == source_fingerprint)
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
                self._decode_value(handle.read(end - start))
        return True

    @staticmethod
    def _decode(body):
        value = json.loads(body)
        if not isinstance(value, str):
            raise ValueError('Preview body must be a base64 string')
        base64.b64decode(value, validate=True)
        return value

    def _decode_value(self, body, *, validate_image=False):
        if not self.extension:
            return self._decode(body)
        value = json.loads(body)
        if not isinstance(value, str):
            raise ValueError('Preview body must be a base64 string')
        image = base64.b64decode(value, validate=True)
        if len(image) < 12 or image[:4] != b'RIFF' or image[8:12] != b'WEBP':
            raise ValueError('Preview body must contain a RIFF/WEBP image')
        if validate_image:
            # Installation only: runtime reads must never decode image pixels.
            from PIL import Image
            with Image.open(io.BytesIO(image)) as decoded:
                decoded.load()
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
            body = _ByteWindow(handle, stat.st_size)
            offsets = (self._scan_extension(body) if self.extension else self._scan(body)) if stat.st_size else {}
        self.offsets = offsets
        if self.cache_path is not None and self.cache_write:
            self._save(self.cache_path)

    def _scan_extension(self, body):
        """Keep decoding bounded and outside the service lock during staging."""
        if not self.validate_images:
            return self._scan_extension_body(body, self._decode_value)
        from PIL import Image
        Image.init()  # Initialize plugins before concurrent Image.open calls.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='pack-validate') as pool:
            pending = deque()

            def validate(raw):
                pending.append(pool.submit(self._decode_value, raw, validate_image=True))
                if len(pending) >= 8:
                    pending.popleft().result()

            offsets = self._scan_extension_body(body, validate)
            for future in pending:
                future.result()
            return offsets

    def _scan_extension_body(self, body, validate):
        """Strict streaming scan; retain only keys/offsets and bounded image work."""
        head = body[0:min(len(body), 64 * 1024)]
        match = re.search(rb',\s*"thumbs"\s*:\s*\{', head)
        if match is None:
            raise ValueError('Invalid extension pack header')
        metadata = json.loads(head[:match.start()] + b'}')
        if (list(metadata) != ['note', 'size', 'quality', 'count']
                or not isinstance(metadata['note'], list)
                or metadata['size'] != 384 or metadata['quality'] != 72
                or type(metadata['count']) is not int or metadata['count'] <= 0):
            raise ValueError('Invalid extension pack metadata')

        def space(pos):
            while pos < len(body):
                body._load(pos)
                found = re.search(rb'[^ \t\r\n]',
                                  memoryview(body.chunk)[pos-body.start:body.valid])
                if found is not None:
                    return pos + found.start()
                pos = body.start + body.valid
            return pos

        offsets = {}
        pos = space(match.end())
        while body[pos] != 125:
            # A member header can cross a streaming block boundary.
            length = 4096
            while True:
                header = body[pos:min(len(body), pos + length)]
                member = re.match(rb'("(?:[^"\\]|\\.)*")[ \t\r\n]*:[ \t\r\n]*(")', header)
                if member is not None:
                    break
                if pos + length >= len(body) or length >= 64 * 1024:
                    raise ValueError('Invalid extension thumbnail member')
                length *= 2
            key = json.loads(member[1])
            if key in offsets:
                raise ValueError('Duplicate extension thumbnail key')
            start = pos + member.start(2)
            end = start
            while True:
                end = body.find(b'"', end + 1)
                if end < 0:
                    raise ValueError('Unterminated extension thumbnail')
                slash = end - 1
                while slash > start and body[slash] == 92:
                    slash -= 1
                if (end - 1 - slash) % 2 == 0:
                    break
            validate(body[start:end + 1])
            offsets[key] = [start, end + 1]
            pos = space(end + 1)
            if body[pos] == 125:
                break
            if body[pos] != 44:
                raise ValueError('Missing extension thumbnail separator')
            pos = space(pos + 1)
            if body[pos] == 125:
                raise ValueError('Trailing extension thumbnail separator')
        pos = space(pos + 1)
        if body[pos] != 125 or space(pos + 1) != len(body):
            raise ValueError('Invalid extension pack terminator')
        if len(offsets) != metadata['count']:
            raise ValueError('Extension thumbnail count mismatch')
        return offsets

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

    def _save(self, path, *, signature=None, strict=False):
        temp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                             prefix=path.name, suffix='.tmp', delete=False) as handle:
                temp = handle.name
                json.dump({'schema': 3, 'signature': self.signature if signature is None else signature,
                           'count': len(self.offsets),
                           **({'source_sha256': self.source_fingerprint} if self.extension else {}),
                           'keys_sha1': self._keys_sha1(self.offsets), 'offsets': self.offsets},
                          handle, ensure_ascii=False, separators=(',', ':'))
            os.replace(temp, path)
        except OSError:
            if strict:
                raise  # Installation requires the prepared sidecar before replacement.
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
            if self.extension:
                header_start = max(0, start - (len(key.encode('utf-8')) * 6 + 64))
                handle.seek(header_start)
                header = handle.read(start - header_start)
                match = re.search(rb'("(?:[^"\\]|\\.)*")\s*:\s*$', header)
                if match is None or json.loads(match[1]) != key:
                    raise ValueError('Extension thumbnail offset key mismatch')
            else:
                handle.seek(start)
            return self._decode_value(handle.read(end-start))

    def __getitem__(self, key):
        if self.extension:
            # Propagate corruption to the service; repairing here would hide it
            # from readiness and suppress the user's retry/download action.
            return self._read(key)
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
