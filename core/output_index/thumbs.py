"""WebP thumbnails keyed by indexed file identity."""
from hashlib import sha1
from io import BytesIO
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import threading

from PIL import Image


_GENERATION = threading.BoundedSemaphore(2)


def cache_key(file, size):
    identity = f"{file.root_path}|{file.rel}|{file.name}|{file.size}|{file.mtime_ns}|{size}"
    return sha1(identity.encode("utf-8")).hexdigest()


def generate_thumbnail(path, size):
    with Image.open(path) as source:
        longest = max(source.size)
        target = tuple(max(1, round(n * size / longest)) for n in source.size)
        if source.format == "JPEG":
            source.draft("RGB", target)
        mode = "RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB"
        image = source if source.mode == mode else source.convert(mode)
        factor = max(image.size) // (2 * size)
        if factor >= 2:
            image = image.reduce(factor)
        image.thumbnail(target, Image.Resampling.LANCZOS)
        if image.size != target:
            image = image.resize(target, Image.Resampling.LANCZOS)
        out = BytesIO()
        image.save(out, "WEBP", quality=80, method=4)
        return out.getvalue()


class ThumbnailCache:
    def __init__(self, index_dir, cap=512 * 1024 * 1024):
        self.root = Path(index_dir).resolve() / "thumbs"
        self.cap = cap
        self._bytes = None
        self._lock = threading.Lock()

    def _entries(self):
        # Only visit the cache's bucket level. Reject redirected paths, including
        # Windows junctions, before entering a directory or removing a file.
        if self.root.resolve() != self.root:
            raise OSError("Redirected thumbnail directory")
        with os.scandir(self.root) as buckets:
            for bucket in buckets:
                folder = Path(bucket.path)
                if not bucket.is_dir(follow_symlinks=False) or folder.resolve() != folder:
                    continue
                with os.scandir(folder) as files:
                    for file in files:
                        path = Path(file.path)
                        if path.suffix == ".webp" and file.is_file(follow_symlinks=False) and path.resolve() == path:
                            stat = file.stat(follow_symlinks=False)
                            yield stat.st_mtime_ns, path, stat.st_size

    def _prune(self):
        entries = sorted(self._entries())
        self._bytes = sum(size for _, _, size in entries)
        for _, path, size in entries:
            if self._bytes <= self.cap * 0.8:
                break
            if path.resolve() == path:
                try:
                    path.unlink(missing_ok=True)
                except PermissionError:
                    continue
                self._bytes -= size

    def _read(self, target):
        if target.resolve() != target:
            raise OSError("Redirected thumbnail path")
        try:
            return target.read_bytes()
        except FileNotFoundError:
            return None

    def _write(self, target, data):
        target.parent.mkdir(parents=True, exist_ok=True)
        if self._bytes is None:
            self._bytes = sum(size for _, _, size in self._entries())
        temp = NamedTemporaryFile(dir=target.parent, delete=False)
        try:
            with temp:
                temp.write(data)
            os.replace(temp.name, target)
        finally:
            temp_path = Path(temp.name)
            if temp_path.resolve() == temp_path:
                temp_path.unlink(missing_ok=True)
        self._bytes += len(data)
        if self._bytes > self.cap:
            self._prune()

    def get(self, file, size):
        key = cache_key(file, size)
        target = self.root / key[:2] / (key + ".webp")
        with self._lock:
            cached = self._read(target)
        if cached is not None:
            return cached
        with _GENERATION:
            with self._lock:
                cached = self._read(target)
            if cached is not None:
                return cached
            data = generate_thumbnail(file.path, size)
            with self._lock:
                if self._read(target) is None:
                    self._write(target, data)
            return data
