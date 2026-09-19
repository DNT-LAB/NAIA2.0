"""`.naiamap` - 이벤트 맵 색인을 **파일 하나**에 담는 형식.

예전에는 `event_map.sqlite3`(태그·게시물 목록·분면표) + `event_map.records.bin`(게시물
본문) 두 파일이 한 벌이었다. 옮기다 한쪽만 옮기면 안 열린다. 이 형식은 둘을 한 파일에
구역(section)으로 담고, 머리에 구역 목차를 둔다. 읽는 쪽은 파일 전체를 mmap 으로 걸고
구역마다 numpy 뷰를 만든다 - 복사가 없어 여는 데 드는 시간은 목차와 태그표뿐이다.

배치
    [0 .. HEADER_SIZE)   MAGIC(8) + 목차 길이(u32 LE) + 목차 JSON(utf-8), 나머지는 0
    이후                  구역들. 시작 위치는 8바이트 정렬. 순서는 상관없다(목차가 말한다).

목차 JSON
    {"container": "naiamap-v1", "sections": {"<이름>": [시작, 길이], ...}}

구역 (모두 little-endian)
    meta        JSON  - schema, records, partitions, policy, guard, lanes, source ...
    tags        JSON  - [[이름, 관측 수, 갈래(role), lane], ...]  (id = 목록 순서)
    post_index  u64[태그 수 + 1] - postings 구역 안에서 태그 t 의 조각은 [idx[t], idx[t+1])
    postings    태그별 `zlib(개수 + 차분 varint)` 를 이어 붙인 것
    partitions  u8[rid]  - 게시물 -> 분면 번호
    offsets     u32[rid + 1] - 게시물 rid 의 본문은 body[offsets[rid]:offsets[rid+1]]
    body        u16[...]  - 게시물별 정렬된 태그 id 를 한 줄로 이어 붙인 것
"""
from __future__ import annotations

import json
import mmap
from pathlib import Path

MAGIC = b"NAIAMAP2"
CONTAINER = "naiamap-v1"
HEADER_SIZE = 4096
ALIGN = 8
SUFFIX = ".naiamap"
REQUIRED = ("meta", "tags", "post_index", "postings", "partitions", "offsets", "body")


def is_pack(path: str | Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


class PackWriter:
    """구역을 차례로 쓰고, 닫을 때 머리의 목차를 채운다.

    ⚠️ 목차가 채워지기 전(닫기 전)의 파일은 MAGIC 이 없어 `is_pack` 이 거절한다 -
       도중에 끊긴 파일을 색인으로 잘못 여는 일이 없다.
    """

    def __init__(self, path: str | Path, required: tuple[str, ...] = REQUIRED):
        """`required` 는 닫을 때 있어야 하는 구역 이름. 기본은 이벤트 맵의 것이다.

        같은 그릇(MAGIC·목차·정렬)을 쓰되 구역 구성이 다른 팩 - 예: 작가 친화도
        (`tools/build_artist_affinity_pack.py`) - 은 자기 목록을 넘긴다. 그릇을
        따로 구현하면 두 벌이 갈라지므로 여기 한 곳만 둔다.
        """
        self.path = Path(path)
        self.required = tuple(required)
        self.f = self.path.open("wb")
        self.f.write(bytes(HEADER_SIZE))
        self.sections: dict[str, list[int]] = {}
        self._open: str | None = None

    def begin(self, name: str) -> None:
        if self._open or name in self.sections:
            raise ValueError("구역 이름이 겹치거나 앞 구역이 안 닫혔다: %s" % name)
        pad = (-self.f.tell()) % ALIGN
        if pad:
            self.f.write(bytes(pad))
        self.sections[name] = [self.f.tell(), 0]
        self._open = name

    def write(self, data) -> None:
        if not self._open:
            raise ValueError("begin() 없이 쓰려 했다")
        self.f.write(data)

    def end(self) -> None:
        start = self.sections[self._open][0]
        self.sections[self._open][1] = self.f.tell() - start
        self._open = None

    def add(self, name: str, data) -> None:
        self.begin(name)
        self.write(data)
        self.end()

    def add_json(self, name: str, value) -> None:
        self.add(name, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def close(self) -> None:
        if self._open:
            raise ValueError("닫히지 않은 구역: %s" % self._open)
        missing = [n for n in self.required if n not in self.sections]
        if missing:
            raise ValueError("빠진 구역: %s" % ", ".join(missing))
        toc = json.dumps({"container": CONTAINER, "sections": self.sections},
                         separators=(",", ":")).encode("utf-8")
        if len(MAGIC) + 4 + len(toc) > HEADER_SIZE:
            raise ValueError("목차가 머리 크기를 넘는다")
        self.f.flush()
        self.f.seek(0)
        self.f.write(MAGIC + len(toc).to_bytes(4, "little") + toc)
        self.f.close()


class PackReader:
    """파일 전체를 mmap 으로 걸고 구역 위치를 알려 준다."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = self.path.open("rb")
        try:
            self.map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception:
            self._file.close()
            raise
        if self.map[:len(MAGIC)] != MAGIC:
            self.close()
            raise ValueError("naiamap 형식이 아니다(끊긴 빌드일 수 있다): %s" % self.path)
        n = int.from_bytes(self.map[len(MAGIC):len(MAGIC) + 4], "little")
        toc = json.loads(bytes(self.map[len(MAGIC) + 4:len(MAGIC) + 4 + n]).decode("utf-8"))
        if toc.get("container") != CONTAINER:
            self.close()
            raise ValueError("모르는 컨테이너 버전: %s" % toc.get("container"))
        self.sections = {k: (int(v[0]), int(v[1])) for k, v in toc["sections"].items()}
        size = len(self.map)
        for name, (start, length) in self.sections.items():
            if start < HEADER_SIZE or start + length > size:
                self.close()
                raise ValueError("구역 %s 가 파일 밖을 가리킨다 - 파일이 잘렸다" % name)

    def span(self, name: str) -> tuple[int, int]:
        return self.sections[name]

    def bytes_of(self, name: str) -> bytes:
        start, length = self.sections[name]
        return bytes(self.map[start:start + length])

    def json_of(self, name: str):
        return json.loads(self.bytes_of(name).decode("utf-8"))

    def close(self) -> None:
        m = getattr(self, "map", None)
        if m is not None:
            m.close()
            self.map = None
        f = getattr(self, "_file", None)
        if f is not None:
            f.close()
            self._file = None
