"""PyQt-free Artist Thumbnail service for the headless Remote Web runtime."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import math
import os
import random
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from core.resolution_utils import (
    MAX_1MP_PIXELS,
    STANDARD_1MP_RESOLUTIONS,
    nearest_standard_1mp_resolution,
)


class ArtistLoadCancelled(RuntimeError):
    """화면이 팩 읽기를 그만두라고 했다(외부 브라우저의 [중단] - load_cancel)."""


def _safe_log(message: str, fallback: str | None = None) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        print(fallback or message.encode("ascii", "replace").decode("ascii"))


class ArtistThumbnailService:
    ARTIST_THUMB_MODES = {
        # ⚠️ **여기가 유일한 정의다**(future02). 이 표가 그대로 드롭다운이 된다 -
        #    프론트는 `key`/`label` 을 하드코딩하지 않는다.
        # ⚠️ 새 데이터셋은 **반드시 새 키 + 새 `path`** 로 낸다. 같은 키에 내용만
        #    갈아끼우면 이미 받은 사용자 기기에서는 갱신이 **안 일어난다** -
        #    갱신 판정이 `expected_size` 비교뿐이라 지문이 없으면 늘 최신으로 본다
        #    (ARTIST_THUMBNAIL_DATASET_UPDATE_REPORT.md 0절).
        # ⚠️ `expected_size`/`sha256` 은 **앱 소스에 박힌다** = 데이터셋 갱신에는
        #    앱 릴리즈가 따라야 사용자에게 닿는다.
        # NAID5 분할 팩 3종(2026-09-13, 사용자 지시). 게시물 수 구간별로 갈랐다 - 이름의 숫자가
        # 그 구간이다(6333~165 · 164~84 · 83~, WIP 는 아직 채우는 중). 방안 A(새 키 + 새 경로).
        # 지문은 업로드 원본에서 실측(같은 폴더의 NAID5-*). ⚠️ WIP 판을 나중에 채워 갈아끼울
        # 때는 **경로를 그대로 두고** expected_size/sha256 만 바꿔야 `(update)` 가 선다.
        "NAID5-6333-165": {
            "label": "NAID5-6333-165",
            "path": Path("data/artist_thumbnail_naid5_6333_165.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID5_artist_thumbnail/NAID5-6333-165",
            # 2026-09-19 갱신. 1,532,623,111 -> 1,553,062,505 (경로가 같으니 (update))
            "expected_size": 1553062505,
            "sha256": "9FB76C5A57E005EE0E137B7605D142F22642EA5BBA4EC2FE9C0654675C5D13DB",
        },
        "NAID5-164-84": {
            "label": "NAID5-164-84",
            "path": Path("data/artist_thumbnail_naid5_164_84.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID5_artist_thumbnail/NAID5-164-84",
            # 2026-09-19 갱신. 1,554,305,817 -> 1,853,907,145
            "expected_size": 1853907145,
            "sha256": "97D4F6FE9174D7C1C310632AEF8A44541668CA45720938077FDF4C23982C4406",
        },
        # 옛 `NAID5-83-WIP` 자리다(사용자 지정 2026-09-19: "링크를 유지해서 (update)를
        # 출력, 업데이트 후에는 NAID5-83-50 으로 관리").
        # ⚠️ **디스크 경로를 옛 이름 그대로 둔다**(`..._83_wip.json`). 파일명을 예쁘게
        #    고치면 이미 받은 1.4GB 가 다른 파일로 보여 `(update)` 가 아니라 `(download)`
        #    가 서고, 옛 파일이 디스크에 영영 남는다. 갱신 통보는 **같은 경로 + 다른
        #    expected_size** 가 전부다.
        # ⚠️ 키는 새 이름으로 간다 - 저장돼 있던 `NAID5-83-WIP` 선택은 한 번 풀린다
        #    (드롭다운에 `NAID5-83-50 (update)` 로 바로 보이므로 다시 고르면 된다).
        "NAID5-83-50": {
            "label": "NAID5-83-50",
            "path": Path("data/artist_thumbnail_naid5_83_wip.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID5_artist_thumbnail/NAID5-83-50",
            # 옛 WIP 판: 1,535,887,765 · 03F5E8DD… -> 아래와 달라 `needs_update` 가 선다.
            "expected_size": 2192792940,
            "sha256": "C2741D70E463B03841B0F27A59D69CD422D98B34F52E5A8F5713A10DFE227C3A",
        },
        # ── 2026-10-12 (사용자 지시): 83-50 아래 구간이 셋으로 정리됐다 ─────────────────────────────
        #   지문은 셋 다 업로드 원본 실측이고 HF 의 X-Linked-Size · X-Linked-ETag(= sha256)와 같다.
        #
        # Curated 가 이 구간에서 읽는 팩. 새 팩이라 방안 A - 새 키 + **새 경로**. 33,001 ~ 55,000 번째 줄의
        # 작가 가운데 손으로 고른 6,145명이다. ⚠️ **ALL 에는 안 든다**: 전원이 이미 다른 팩에 있다 -
        # 앞의 세 팩에 2,060명, `NAID5-49-20` 에 4,085명(그림까지 같다, 실측). 넣으면 1GB 를 더 읽고
        # 한 명도 안 늘어난다. 거르는 조각은 `Curated`(ALL 의 `exclude_contains`).
        "NAID5-33000-55000-Curated": {
            "label": "NAID5-33000-55000-Curated",
            "path": Path("data/artist_thumbnail_naid5_33000_55000_curated.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID5_artist_thumbnail/NAID5-33000-55000-Curated",
            "expected_size": 1030625005,
            "sha256": "724EE2B0C906159C22BA28566F0D0AA2AEE350E81896294AC0DED22C23144FAC",
        },
        # 옛 `NAID5-49-WIP` 의 확정판(게시물 49 이하 통과자 전원 13,167명). 83 때와 같은 방안 B -
        # 키 · 라벨 · URL · 지문은 새것, **디스크 경로는 옛 이름 그대로**(`..._49_wip.json`). 그래야 WIP 를
        # 받아 둔 기기에 `(download)` 가 아니라 `(update)` 가 선다(옛 판 1,388,682,556 · 15A62422… · 8,269명 -
        # 전원이 새 판 안에 있다). 키가 바뀌어 `NAID5-49-WIP` 로 부르던 주소는 '모르는 모드' 가 된다.
        # ⚠️ **Curated 에는 안 든다**(사용자 지정): ALL 을 고르거나 이 팩을 직접 고를 때만 읽는다.
        #    거르는 조각은 `49-20`(Curated 의 `exclude_contains`).
        "NAID5-49-20": {
            "label": "NAID5-49-20",
            "path": Path("data/artist_thumbnail_naid5_49_wip.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID5_artist_thumbnail/NAID5-49-20",
            "expected_size": 2217731005,
            "sha256": "B21A5C0ECB47E52C7050736954B766DCA2C05DC9659C0A10AEA62EA15DE2B570",
        },
        # 옛 `NAID5-STYLISH-WIP` 의 확정판(탈락 갈래 전원 8,028명). 위와 같은 방안 B - **경로는 옛 이름
        # 그대로**(`..._stylish_wip.json`), 옛 판(850,611,426 · 1486E2F0… · 5,149명)을 받은 기기엔 `(update)`.
        # ⚠️ 이름에 `STYLISH` 가 들어가는 것이 곧 계약이다: Curated 는 이 조각을
        #    `exclude_contains` 로 걸러 내고 ALL 만 포함한다.
        "NAID5-STYLISH-8000": {
            "label": "NAID5-STYLISH-8000",
            "path": Path("data/artist_thumbnail_naid5_stylish_wip.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID5_artist_thumbnail/NAID5-STYLISH-8000",
            "expected_size": 1335470826,
            "sha256": "2AC41FDC117E51EAC2A853167A67647112953FE8886F6B6BFACFC01D4A02A6DB",
        },
        "NAID4.5F-31000": {
            "label": "NAID4.5F-31000",
            "path": Path("data/artist_thumbnail_nai.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID4.5_artist_thumbnail_31000/artist_thumbnail_nai",
        },
        "NoobNAI-XL-33000": {
            "label": "NoobNAI-XL-33000",
            "path": Path("data/artist_thumbnail.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Noob_artist_thumbnail_33000/artist_thumbnail",
        },
        "ANIMA-22000": {
            "label": "ANIMA-22000",
            "path": Path("data/artist_thumbnail_anima.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima.json",
            "expected_size": 2656390724,
            "sha256": "C831A5B186176AEBED394F320C3E5B75B3ACEB78AF2D97B84D04C277C276252E",
        },
        "ANIMA-44000": {
            "label": "ANIMA-44000",
            "path": Path("data/artist_thumbnail_anima_bucket2.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima_bucket2.json",
            "expected_size": 2604574500,
            "sha256": "3B581E8A5C596B4E2AE001C8842B486BF4D7BC36485D23B0861B0200C41017E2",
        },
        "ANIMA-60000": {
            "label": "ANIMA-60000",
            "path": Path("data/artist_thumbnail_anima_bucket3.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima_bucket3.json",
            "expected_size": 1882040677,
            "sha256": "C564F0A473F32A81DEA43696FBF1CAA477184C957C7C1A8B5B2B21781334FB7B",
        },
    }
    # 여러 팩을 **한 목록으로** 이어 붙이는 가상 모드(사용자 지정 2026-09-19).
    # 팩을 합쳐 담지는 않는다 - 그림 주소에 `mode=` 가 실리므로 목록만 잇고 그림은
    # 제 팩이 낸다. 받지 않은 팩은 조용히 건너뛴다(사용자 지정).
    #
    # ⚠️ 거르는 이름은 **부분 문자열**이다. 사용자는 "NAID5-20000-Q" 라고 적었지만
    #    실제 키는 `NAID5F-20000-Q`(F 가 있다) - 통째로 비교했으면 한 개도 안 걸러지고
    #    조용히 네 팩이 붙었을 것이다. 아직 없는 `NAID5-STYLISH*` 도 같은 이유로
    #    부분 문자열로 막아 둔다.
    #
    # `pin_top`/`accent` 는 **드롭다운에서의 자리와 색**이다(사용자 지정 2026-09-19:
    # "NAID5 Curated 버튼 위치를 가장 위로 올리고, 연노랑색으로 혼자 강조").
    # ⚠️ 권하는 것이 하나라서 강조가 뜻을 갖는다 - 둘에 칠하면 둘 다 안 보인다.
    #
    # 구성(사용자 지정 2026-10-12) - 표의 차례 그대로 잇는다:
    #   Curated = 6333-165 · 164-84 · 83-50 · 33000-55000-Curated            (37,770명)
    #   ALL     = 6333-165 · 164-84 · 83-50 · 49-20 · STYLISH-8000           (54,880명)
    # `NAID5-49-20` · `NAID5-STYLISH-8000` 은 ALL 을 고르거나 그 팩을 직접 고를 때만 읽는다.
    ARTIST_THUMB_VIRTUAL_MODES = {
        "NAID5-CURATED": {
            "label": "NAID5 Curated",
            "prefix": "NAID5",
            "exclude_contains": ("20000-Q", "STYLISH", "49-20"),
            "pin_top": True,
            "accent": True,
        },
        "NAID5-ALL": {
            "label": "NAID5 ALL",
            "prefix": "NAID5",
            "exclude_contains": ("20000-Q", "Curated"),
        },
    }
    ARTIST_THUMB_OPTION_MODES = ("NAI", "WEBUI", "COMFYUI")

    def __init__(
        self,
        repo_root: str | Path,
        mode_getter: Callable[[], str] | None = None,
        *,
        mode_data_root: str | Path | None = None,
        state_root: str | Path | None = None,
        wildcards_root: str | Path | None = None,
        on_favorites_written: Callable[[Path], None] | None = None,
    ):
        self.repo_root = Path(repo_root)
        # 관심 작가 목록은 `favorite_artist.txt` 와일드카드로도 쓰인다(1.5 부터의 약속 -
        # `__favorite_artist__`). 파일만 고치면 돌고 있는 와일드카드 관리자는 서버를 다시
        # 켤 때까지 옛 목록을 본다 - 그래서 쓴 뒤 이 콜백으로 알린다(2026-09-25 사용자 제보).
        self._on_favorites_written = on_favorites_written
        self.mode_data_root = Path(mode_data_root) if mode_data_root is not None else self.repo_root / "data"
        self.state_root = Path(state_root) if state_root is not None else self.repo_root / "artist_thumb"
        self.wildcards_root = Path(wildcards_root) if wildcards_root is not None else self.repo_root / "wildcards"
        self.legacy_state_root = self.repo_root / "artist_thumb"
        self.legacy_wildcards_root = self.repo_root / "wildcards"
        self._mode_getter = mode_getter or (lambda: "NAI")
        self._data_cache: dict[str, dict] = {}
        # ⚠️ 팩 하나가 1.3GB(파싱 4.2초)다. 가상 모드는 그 여럿에 걸쳐 있어서 한 칸만
        #    쥐면 한 페이지를 그리는 동안 팩을 왕복한다 - 활성 가상 모드의 구성원
        #    수만큼 열어 둔다(Curated 4 · ALL 5). 평소에는 예전처럼 하나다.
        self._data_cache_limit = 1
        # 캐시한 팩의 **바이트 크기**. 갱신 중에도 옛 팩을 계속 보여 주되,
        # 다 받아 크기가 바뀌면 그때 새로 읽게 하는 열쇠다(2026-09-03).
        self._data_cache_size: dict[str, int] = {}
        self._image_cache: dict[tuple[str, str], tuple[bytes, str]] = {}
        # 사본 캐시(관심 · 그룹)의 **이름만** - 경로 -> ((파일 번호, mtime_ns, size), 이름들).
        self._copy_names_memo: dict[str, tuple[tuple[int, int, int], frozenset]] = {}
        # 팩의 자리 색인(core/artist_pack_index) - 팩 키 -> 색인. 팩을 통째로 읽지 않고 작가 몇 명만 꺼내는 자리가 쓴다.
        self._pack_indexes: dict[str, Any] = {}
        self._pack_index_lock = threading.Lock()
        # 작가 사전(artist_dictionary.py)의 표 - (파일 지문, 표). 파일이 그대로면 다시 읽지 않는다(_dictionary_weights).
        self._dictionary_memo: tuple[tuple[int, int], dict[str, int]] | None = None
        # 가상 모드의 작가 -> 주인 팩 표 - 모드 -> (구성원 지문, 표). 구성원이 그대로면 다시 만들지 않는다.
        self._owner_map_memo: dict[str, tuple[tuple, dict[str, str]]] = {}
        # 지금 읽고 있는 팩(load_status) · 가상 모드의 몇 번째인지 · 그만두라는 요청(load_cancel).
        self._load_status: dict = {"active": False}
        self._load_group: dict = {}
        self._load_cancel = False
        self._random_history: dict[tuple[str, str, str, int], list[str]] = {}
        # [이번 세션 중복 스킵](사용자 지정 2026-11-04) - 메인 Random 이 이미 붙인 작가. 실행하는 동안만 · 체크를 끄면 비운다.
        self._random_seen: set[str] = set()
        self._random_seen_lock = threading.Lock()
        # 아티스트 검색 결과 풀(사용자 지정 2026-11-04) - 같은 조건이면 다시 세지 않는다(조건 문자열 -> (시각, 이름들)).
        self._search_pool_cache: dict[str, tuple[float, list[str]]] = {}
        self._search_pool_lock = threading.Lock()
        self._lock = threading.RLock()
        # generate_options.json 은 읽고-고치고-쓰는 파일이다 - 프리픽스 저장과 랜덤 도구 저장이 겹치면 한쪽이 사라진다.
        self._options_lock = threading.Lock()
        # 리모컨 하단 바의 세 토글은 **실행하는 동안만** 기억한다(사용자 지시 2026-10-19 - 다시 켜면 꺼진 채로).
        # 파일에는 늘 꺼짐으로 쓰고, 읽을 때 이 값을 덮는다(예전 판이 켜진 채 저장한 파일도 꺼짐으로 시작한다).
        self._random_toggles = {key: False for key in self.RANDOM_TOOL_TOGGLES}
        # 작가 패널 [고정] 이 붙이는 작가 - 격자에서 고른 작가(`focus`)와 따로 둔다(격자를 눌러도 고정이 안 옮겨 간다 ·
        # Codex 릴리즈 리뷰 11-04). 고정과 같이 이번 실행에만 산다.
        self._random_pin_artist = ""
        self._download_thread: threading.Thread | None = None
        self._download_cancel = threading.Event()
        self._download_state = {
            "active": False,
            "mode": "",
            "percent": 0,
            "downloaded_mb": 0.0,
            "total_mb": 0.0,
            "message": "",
            "error": "",
            "done": False,
            "updated_at": "",
        }
        self.ensure_state()

    def _path(self, relative: str | Path) -> Path:
        path = Path(relative)
        return path if path.is_absolute() else self.repo_root / path

    def is_virtual_mode(self, mode: str) -> bool:
        return str(mode or "").strip() in self.ARTIST_THUMB_VIRTUAL_MODES

    def virtual_members(self, mode: str, *, existing_only: bool = True) -> list[str]:
        """가상 모드가 이어 붙일 **실제 팩 키**들. 표에 적힌 차례 그대로다.

        ⚠️ 받지 않은 팩은 건너뛴다(사용자 지정) - 없는 것이 고장은 아니다.
        """
        out = []
        for key, info in self._virtual_roster(mode):
            if existing_only and not self._file_state(info)["exists"]:
                continue
            out.append(key)
        return out

    def _virtual_roster(self, mode: str) -> list[tuple[str, dict]]:
        """가상 모드의 **정원** - 있든 없든 여기 드는 팩 전부. 표의 차례 그대로."""
        spec = self.ARTIST_THUMB_VIRTUAL_MODES.get(str(mode or "").strip())
        if not spec:
            return []
        prefix = str(spec.get("prefix") or "")
        drop = tuple(spec.get("exclude_contains") or ())
        roster = []
        for key, info in self.ARTIST_THUMB_MODES.items():
            if not key.startswith(prefix):
                continue
            if any(piece in key for piece in drop):
                continue
            roster.append((key, info))
        return roster

    def virtual_pending(self, mode: str) -> list[str]:
        """아직 **채워야 할** 구성원 - 없거나 낡은 것. 정원의 차례 그대로다.

        사용자 지정 2026-09-19: "하나라도 있으면 먼저 존재하는 파일부터 로드한 뒤,
        Update 규칙을 따라 사용자가 업데이트 하게 하고 천천히 채워나가도록".
        그래서 한 번에 다 받지 않는다 - [Update] 한 번에 **한 팩**씩 채운다.

        ⚠️ **없는 것이 먼저**고 낡은 것은 뒤다. 표 차례대로 집으면, 이미 보이는 팩을
           1.5GB 다시 받는 동안 아직 한 장도 없는 구간이 계속 비어 있다 - 그것은
           '채워나가는' 것이 아니다.
        """
        missing, stale = [], []
        for key, info in self._virtual_roster(mode):
            state = self._file_state(info)
            if not state["exists"]:
                missing.append(key)
            elif not state["available"]:
                stale.append(key)
        return missing + stale

    def _virtual_owner_map(self, mode: str) -> dict[str, str]:
        """작가 -> **그 작가의 그림을 가진 팩**. 앞 팩이 이긴다(표의 차례대로).

        값이 팩 키라 `artist in thumb_data` 와 `thumb_data.keys()` 가 그대로 쓰이고,
        그림 주소만 주인 팩으로 바뀐다 - 1.3GB 짜리 셋을 합쳐 담을 이유가 없다.
        """
        members = self.virtual_members(mode)
        # 구성원을 다 열어 둘 수 있어야 한 페이지가 팩을 왕복하지 않는다.
        self._data_cache_limit = max(1, len(members))
        # ⚠️ 표는 구성원(팩 키 · 파일 크기)이 그대로이고 **다 메모리에 있으면** 다시 만들지 않는다 - 목록 한 쪽마다
        #    4만 줄을 두 번 훑었다(2026-10-03). 하나라도 내려가 있으면 예전처럼 여기서 올린다(그림 요청이 팩을
        #    하나씩 뒤늦게 읽게 두지 않는다). 받아 쓰는 쪽은 읽기만 한다.
        stamp = tuple((key, self._file_state(self.ARTIST_THUMB_MODES[key])["size"]) for key in members)
        hit = self._owner_map_memo.get(mode)
        if hit is not None and hit[0] == stamp and all(key in self._data_cache for key in members):
            return hit[1]
        owner: dict[str, str] = {}
        complete = True
        try:
            for index, key in enumerate(members):
                # 팩 사이가 [중단] 을 볼 수 있는 틈이다 - 남은 팩을 읽지 않고 멈춘다(읽은 팩은 그대로 쥔다)
                self._raise_if_load_cancelled()
                self._load_group = {"group": mode, "index": index + 1, "total": len(members)}
                try:
                    data = self.load_data(key)
                except ArtistLoadCancelled:
                    raise
                except Exception:
                    complete = False
                    continue
                for artist in data.keys():
                    owner.setdefault(str(artist), key)
        finally:
            self._load_group = {}
            self._load_cancel = False
        if complete:
            self._owner_map_memo[mode] = (stamp, owner)
        return owner

    def _raise_if_load_cancelled(self) -> None:
        if self._load_cancel:
            self._load_cancel = False
            raise ArtistLoadCancelled("팩 불러오기를 중단했습니다.")

    def load_status(self) -> dict:
        """지금 읽고 있는 팩 · 메모리에 올라 있는 팩. 화면이 기다리는 동안 '무엇을 기다리는지' 묻는다.

        ⚠️ 잠금을 잡지 않는다 - 팩을 읽는 쪽이 잠금을 쥔 채 몇 초를 쓴다. 잡으면 답이 읽기가 끝난 뒤에야 나간다.
        """
        status = dict(self._load_status)
        if status.get("active"):
            status["elapsed"] = round(max(0.0, time.time() - float(status.pop("started_at", 0) or 0)), 1)
        else:
            status = {"active": False}
        status["loaded"] = list(self._data_cache.keys())
        return status

    def load_cancel(self) -> bool:
        """읽고 있는 팩이 있으면 그만두라고 적어 둔다. 멈추는 것은 읽는 쪽이 틈에서 본다(_raise_if_load_cancelled) -
        파일을 읽은 뒤 · 다음 팩으로 넘어가기 전. 파싱 중인 팩 하나는 끝까지 간다."""
        if not (self._load_status.get("active") or self._load_group):
            return False
        self._load_cancel = True
        return True

    def _mode_info(self, mode: str) -> dict:
        key = str(mode or "").strip()
        info = self.ARTIST_THUMB_MODES.get(key)
        if not info:
            raise KeyError("Unknown artist thumbnail mode")
        return info

    def _mode_path(self, mode: str) -> Path:
        info = self._mode_info(mode)
        primary = self._mode_download_path(info)
        legacy = self._path(info["path"])
        return primary if primary.exists() or not legacy.exists() else legacy

    def _mode_download_path(self, info: dict) -> Path:
        path = Path(info["path"])
        if path.is_absolute():
            return path
        try:
            return self.mode_data_root / path.relative_to("data")
        except ValueError:
            return self._path(path)

    def _file_state(self, info: dict) -> dict:
        path = self._mode_download_path(info)
        legacy = self._path(info["path"])
        if not path.exists() and legacy.exists():
            path = legacy
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        expected_size = int(info.get("expected_size") or 0)
        needs_update = bool(exists and expected_size and size != expected_size)
        return {
            "exists": exists,
            "available": bool(exists and not needs_update),
            "needs_update": needs_update,
            "size": size,
            "expected_size": expected_size,
            "size_mb": round(size / (1024 * 1024), 1) if exists else 0,
            "expected_size_mb": round(expected_size / (1024 * 1024), 1) if expected_size else 0,
            "sha256": str(info.get("sha256") or ""),
        }

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    def _dictionary_weights(self) -> dict[str, int]:
        """`artist_dictionary.py` 의 표(작가 -> 게시물 수). **파일이 그대로면 다시 읽지 않는다.**

        ⚠️ 받은 쪽은 고치지 않는다 - 고칠 쪽은 사본을 만든다(`_artist_weights`).
        ⚠️ 예전에는 부를 때마다 읽었다. 포터블은 바이트코드를 쓰지 않아(PYTHONDONTWRITEBYTECODE) 그때마다 2MB 소스를
           **컴파일**했고, 목록 한 쪽 · 검색 한 번 · 상태 조회마다 약 300ms 가 여기서 나갔다(2026-10-03 실측: 목록
           340~410ms 중 300ms. 개발 트리는 .pyc 가 있어 27ms 라 안 보였다).
        """
        dictionary_path = self.repo_root / "artist_dictionary.py"
        try:
            stat = dictionary_path.stat()
        except OSError:
            return {}
        stamp = (stat.st_mtime_ns, stat.st_size)
        memo = self._dictionary_memo
        if memo is not None and memo[0] == stamp:
            return memo[1]
        table: dict[str, int] = {}
        try:
            spec = importlib.util.spec_from_file_location("naia_artist_dictionary", dictionary_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                artist_dict = getattr(module, "artist_dict", {})
                if isinstance(artist_dict, dict):
                    table = {str(key): int(value or 0) for key, value in artist_dict.items()}
        except Exception as exc:
            _safe_log(
                f"🌐 Headless Artist Thumb: artist dictionary load failed — {exc}",
                f"[WARN] Headless Artist Thumb: artist dictionary load failed - {exc}",
            )
            return {}          # 못 읽은 것은 기억하지 않는다 - 다음에 다시 읽는다
        self._dictionary_memo = (stamp, table)
        return table

    def _artist_weights(self, mode: str = "") -> dict[str, int]:
        weights: dict[str, int] = dict(self._dictionary_weights())

        mode_key = str(mode or "").strip()
        if mode_key:
            try:
                data = self.load_data(mode_key)
                for artist in data.keys():
                    weights.setdefault(str(artist), 0)
            except Exception:
                pass
        return weights

    def _read_lines(self, path: Path) -> list[str]:
        try:
            if not path.exists():
                return []
            return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception as exc:
            _safe_log(
                f"🌐 Headless Artist Thumb: list read failed ({path}) — {exc}",
                f"[WARN] Headless Artist Thumb: list read failed ({path}) - {exc}",
            )
            return []

    def _write_lines(self, path: Path, values: list[str]) -> bool:
        """썼으면 True. 내용이 같아 건너뛰면 False."""
        path.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        cleaned = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        if path.exists() and self._read_lines(path) == cleaned:
            return False
        path.write_text("".join(f"{value}\n" for value in cleaned), encoding="utf-8")
        return True

    def _state_path(self) -> Path:
        return self.state_root / "artist_state.json"

    def _favorite_path(self) -> Path:
        return self.wildcards_root / "favorite_artist.txt"

    def _banned_path(self) -> Path:
        return self.state_root / "banned_artist.txt"

    def _options_path(self) -> Path:
        return self.state_root / "generate_options.json"

    def _favorite_thumbnail_cache_path(self) -> Path:
        return self.state_root / "favorite_thumbnail_cache.json"

    # ── 사용자가 생성한 썸네일 ─────────────────────────────────────────
    # Artist 탭에서 그 아티스트로 생성한 그림을 카드에 남긴다. 예전에는 어디에도
    # 저장하지 않아 브라우저 메모리(`resultMemory`)에만 있었고 재시작하면 사라졌다.
    def _generated_dir(self) -> Path:
        return self.state_root / "generated"

    def _generated_index_path(self) -> Path:
        return self._generated_dir() / "index.json"

    def _legacy_favorite_path(self) -> Path:
        return self.legacy_wildcards_root / "favorite_artist.txt"

    def _legacy_banned_path(self) -> Path:
        return self.legacy_state_root / "banned_artist.txt"

    def _options_mode(self, mode: str = "") -> str:
        mode_key = str(mode or "").strip().upper()
        if mode_key in self.ARTIST_THUMB_OPTION_MODES:
            return mode_key
        current_mode = str(self._mode_getter() or "").strip().upper()
        if current_mode in self.ARTIST_THUMB_OPTION_MODES:
            return current_mode
        return "NAI"

    def _normalize_options(self, data: Any, mode: str = "") -> dict:
        source = data if isinstance(data, dict) else {}
        legacy = {
            "prefix": str(source.get("prefix") or ""),
            "postfix": str(source.get("postfix") or ""),
        }
        raw_modes = source.get("modes") if isinstance(source.get("modes"), dict) else {}
        modes = {}
        for mode_key in self.ARTIST_THUMB_OPTION_MODES:
            values = raw_modes.get(mode_key) if isinstance(raw_modes.get(mode_key), dict) else {}
            prefix = values.get("prefix") if "prefix" in values else legacy["prefix"]
            postfix = values.get("postfix") if "postfix" in values else legacy["postfix"]
            modes[mode_key] = {
                "prefix": str(prefix or ""),
                "postfix": str(postfix or ""),
            }
        mode_key = self._options_mode(mode)
        selected = modes.get(mode_key, modes["NAI"])
        return {
            "version": 2,
            "mode": mode_key,
            "prefix": selected["prefix"],
            "postfix": selected["postfix"],
            "modes": modes,
            "random_tools": self._normalize_random_tools(source.get("random_tools")),
        }

    # ── 랜덤 도구(리모컨 하단 바 · 사용자 지시 2026-10-19) ─────────────────
    #  [생성 버튼 -> 랜덤 아티스트] [랜덤 가중치] [메인 랜덤 버튼 연결]. 셋 다 다음 실행에도 남는다(사용자 결정).
    #  `pool` 은 리모컨이 보고 있던 목록 조건(모드 · 필터 · 이름 검색)이다 - 창을 닫아도 메인 Random 이 이것으로 뽑는다.
    #  `link_pin` = 결과 화면 작가 패널의 [고정] 이 켜져 있다 - 메인 Random 이 뽑지 않고 `pin_artist` 를 붙인다
    #  (런타임 · 고정할 때만 바뀐다 - 격자에서 고른 `focus` 와 다르다).
    #  `pin_hold` = 그 [고정] 이 [생성 버튼 -> 랜덤 아티스트] 를 **빌려** 꺼 두었다(사용자 지정 2026-11-03). 토글은 상위
    #  정책이다 - 고정을 풀면 다시 켜고 정책을 돌려준다. 둘 다 이번 실행에만 산다(다른 토글과 같이).
    #  `source` = 메인 Random 이 작가를 뽑는 곳(사용자 지정 2026-11-04 · 결과 화면 [… 연동됨] 메뉴).
    #  tab = 아티스트 창 목록(`pool`) · favorites = 관심 작가 · group = 그룹 하나(`id` · 임시 그룹 포함).
    #  가중치는 출처와 상관없이 손잡이 · [랜덤 가중치](사용자 지정 - 그룹에 적힌 가중치는 안 쓴다).
    RANDOM_SOURCE_KINDS = ("tab", "favorites", "group")
    # main_exclusive = [다른 작가 숨김](결과 화면 작가 패널 · 사용자 지정 2026-11-06) - 붙인 작가 말고 다른 작가를 걷는다.
    # link_paused = [일시중단]([… 연동됨] 메뉴 · 사용자 지정 2026-11-14) - 연결은 켠 채 메인 Random 이 작가를 안 붙인다.
    #  다른 토글처럼 이번 실행에만 산다(사용자 결정). 연결을 끄면 같이 풀린다.
    RANDOM_TOOL_TOGGLES = ("gen_pick", "random_weight", "main_link", "pin_hold", "link_pin", "main_exclusive", "link_paused")
    RANDOM_TOOL_DEFAULTS = {
        "gen_pick": False,
        "random_weight": False,
        "main_link": False,
        "pin_hold": False,
        "link_pin": False,
        "main_exclusive": False,
        "link_paused": False,
        "weight_start": 0.85,
        "weight_end": 1.15,
        "weight_step": 0.05,
        "weight": 1.0,
    }

    def _normalize_random_tools(self, raw: Any) -> dict:
        source = raw if isinstance(raw, dict) else {}
        defaults = self.RANDOM_TOOL_DEFAULTS

        def number(key: str, low: float, high: float) -> float:
            try:
                value = float(source.get(key, defaults[key]))
            except (TypeError, ValueError):
                value = float(defaults[key])
            if not math.isfinite(value):
                value = float(defaults[key])
            return round(min(high, max(low, value)), 4)

        pool = source.get("pool") if isinstance(source.get("pool"), dict) else {}
        return {
            "gen_pick": bool(source.get("gen_pick", False)),
            "random_weight": bool(source.get("random_weight", False)),
            "main_link": bool(source.get("main_link", False)),
            "pin_hold": bool(source.get("pin_hold", False)),
            "link_pin": bool(source.get("link_pin", False)),
            "main_exclusive": bool(source.get("main_exclusive", False)),
            "link_paused": bool(source.get("link_paused", False)),
            "weight_start": number("weight_start", 0.0, 5.0),
            "weight_end": number("weight_end", 0.0, 5.0),
            "weight_step": number("weight_step", 0.01, 5.0),
            "weight": number("weight", 0.0, 5.0),
            "pool": {
                "mode": str(pool.get("mode") or "").strip()[:200],
                "filter": str(pool.get("filter") or "all").strip()[:200] or "all",
                "query": str(pool.get("query") or "").strip()[:200],
                # 아티스트 창 [검색](매칭 검색)이 켜져 있으면 그 결과가 풀이다(사용자 지정 2026-11-04).
                "search": self._normalize_search_pool(pool.get("search")),
            },
            # 아티스트 창에서 지금 고른 작가 - 작가 패널 [고정] 중이면 [메인 랜덤 버튼 연결] 이 이 작가를 붙인다.
            "focus": str(source.get("focus") or "").strip()[:300],
            "source": self._normalize_random_source(source.get("source")),
            # 아티스트 탭 구간(게시물 많은 순 목록을 100칸으로 · 사용자 지정 2026-11-04) · 이번 세션 중복 스킵(모든 출처).
            "range": self._normalize_random_range(source.get("range")),
            "skip_seen": bool(source.get("skip_seen", False)),
        }

    @staticmethod
    def _normalize_search_pool(raw: Any) -> dict | None:
        """매칭 검색 조건 {stack, order, thumbs}. 조건이 없으면 None(= 모드 · 필터 · 이름 검색 목록)."""
        if not isinstance(raw, dict):
            return None
        stack = raw.get("stack")
        if not isinstance(stack, list) or not stack:
            return None
        order = str(raw.get("order") or "wilson").strip()
        return {
            "stack": [step for step in stack[:20] if isinstance(step, dict)],
            "order": order if order in ("wilson", "posts", "count") else "wilson",
            "thumbs": "has" if str(raw.get("thumbs") or "").strip().lower() == "has" else "all",
        }

    def _search_pool_names(self, search: dict, mode_key: str, *, keep_banned: bool = False) -> list[str] | None:
        """매칭 검색 결과 전체(격자와 같은 순서 · 제외 작가 뺌 - `keep_banned` 면 격자 그대로). 팩이 없거나 조건이 틀리면 None.
        ⚠️ 격자 쪽수와 맞아야 한다 - 같은 `artist_search.search` · 같은 [썸네일 있음] 판정(`image_presence`)."""
        import time

        from core.artist_affinity import default_pack
        from core.artist_search import search as artist_search

        key = json.dumps([search, mode_key if search.get("thumbs") == "has" else ""], ensure_ascii=False, sort_keys=True)
        now = time.monotonic()
        with self._search_pool_lock:
            hit = self._search_pool_cache.get(key)
        if hit and now - hit[0] < 300:
            names = hit[1]
        else:
            only = self.image_presence(mode_key) if search.get("thumbs") == "has" else None
            try:
                result = artist_search(default_pack(), search.get("stack"), order=search.get("order") or "wilson",
                                       limit=10_000_000, offset=0, only=only)
            except Exception:  # noqa: BLE001 - 조건이 틀렸다 · 팩이 없다 = 원래 목록으로
                return None
            if result.get("state") != "ready":
                return None
            names = [str(row.get("artist") or "") for row in result.get("rows") or []]
            with self._search_pool_lock:
                if len(self._search_pool_cache) >= 8:
                    self._search_pool_cache.pop(next(iter(self._search_pool_cache)))
                self._search_pool_cache[key] = (now, names)
        if keep_banned:
            return names                                  # 검색 격자는 제외 작가도 보여 준다 - 쪽 번호는 이 순서로
        banned = set(self._banned())
        return [name for name in names if name and name not in banned]

    def _random_pool_list(self, mode_key: str, filter_key: str, query_text: str, search: Any = None):
        """랜덤이 뽑는 목록 - 매칭 검색이 걸려 있으면 그 결과, 아니면 모드 · 필터 · 이름 검색 목록(격자와 같은 길).
        (작가들, 목록 이름, 게시물 수, 그림 자료, 최근 기록 열쇠)"""
        search = self._normalize_search_pool(search)
        if search:
            names = self._search_pool_names(search, mode_key)
            if names is not None:
                try:
                    thumb_data = self.load_data(mode_key) if mode_key else {}
                except Exception:  # noqa: BLE001 - 그림 자료는 장식이다(풀은 검색 결과 그대로)
                    thumb_data = {}
                key = ("search", json.dumps(search, ensure_ascii=False, sort_keys=True), mode_key, 1)
                return names, "검색 결과", self._artist_weights(mode_key), thumb_data, key
        artists, filter_name, weights, thumb_data = self._list_artists(mode_key, filter_key, query_text,
                                                                      random_sample=True)
        return artists, filter_name, weights, thumb_data, (mode_key, filter_key, query_text, 1)

    @staticmethod
    def _normalize_random_range(raw: Any) -> list[int]:
        try:
            lo, hi = (int(round(float(value))) for value in list(raw)[:2])
        except Exception:  # noqa: BLE001 - 모르는 값 = 처음부터 끝까지
            return [0, 100]
        lo, hi = max(0, min(99, lo)), max(1, min(100, hi))
        return [lo, hi] if lo < hi else [0, 100]

    @staticmethod
    def random_range_bounds(total: int, range_pct: Any) -> tuple[int, int]:
        """목록 길이 · 구간(%) -> [start, end). 화면도 같은 셈(정수 내림)을 한다. 사람이 있으면 적어도 한 명."""
        lo, hi = ArtistThumbnailService._normalize_random_range(range_pct)
        total = max(0, int(total or 0))
        start, end = total * lo // 100, total * hi // 100
        if total and end <= start:
            end = min(total, start + 1)
            start = end - 1
        return start, end

    @staticmethod
    def random_range_order(artists: list[str], weights: dict) -> list[str]:
        """구간 슬라이더가 자르는 순서 = 늘 게시물 많은 순(사용자 지정 2026-11-04 - 검색 결과도 정렬해 자른다).
        검색 결과는 Wilson 등 검색 순서라 '상위 8%' 에 게시물 19개 작가가 섞였다. 같은 수는 원래 순서 · 수 모름 = 맨 뒤."""
        def posts(name: str) -> float:
            value = weights.get(name)
            return float(value) if isinstance(value, (int, float)) else -1.0
        return sorted(artists, key=posts, reverse=True)

    @staticmethod
    def random_bucket_posts(artists: list[str], weights: dict) -> list:
        """구간 손잡이가 보여 줄 게시물 수 - 100칸 저마다 [가장 적은, 가장 많은] 게시물 수(사용자 지정 2026-11-04).
        칸 = `random_range_bounds` 와 같은 셈(정수 내림). 사람이 없거나 수를 모르는 칸은 None.
        검색 결과처럼 게시물 순이 아닌 목록도 맞도록 칸마다 최소 · 최대를 센다(화면이 구간의 칸을 합친다)."""
        total = len(artists)
        out: list = []
        for k in range(100):
            values = [weights[name] for name in artists[total * k // 100: total * (k + 1) // 100]
                      if isinstance(weights.get(name), (int, float))]
            out.append([int(min(values)), int(max(values))] if values else None)
        return out

    def random_seen(self) -> set[str]:
        with self._random_seen_lock:
            return set(self._random_seen)

    def _mark_random_seen(self, artist: str) -> None:
        with self._random_seen_lock:
            self._random_seen.add(artist)

    @classmethod
    def _normalize_random_source(cls, raw: Any) -> dict:
        raw = raw if isinstance(raw, dict) else {}
        kind = str(raw.get("kind") or "tab").strip()
        if kind not in cls.RANDOM_SOURCE_KINDS:
            kind = "tab"
        gid = str(raw.get("id") or "").strip()[:200] if kind == "group" else ""
        if kind == "group" and not gid:
            kind = "tab"
        return {"kind": kind, "id": gid}

    def _random_groups(self) -> list[dict] | None:
        """작가 그룹 목록(`artist_groups.json` - 라우트의 그룹 저장소와 같은 파일). 못 읽으면 None."""
        from core.artist_groups import ArtistGroupStore
        try:
            return ArtistGroupStore(self.state_root).list()
        except Exception:  # noqa: BLE001 - 못 읽는 파일은 그룹 쪽이 알린다 · 여기선 아티스트 탭으로 뽑는다
            return None

    def random_source_names(self, source: dict, groups: list[dict] | None = None) -> list[str] | None:
        """출처의 작가(제외 작가 뺌 · 원래 순서). tab 이거나 그룹이 없어졌으면 None - 부르는 쪽이 아티스트 탭으로."""
        kind = source.get("kind")
        if kind == "favorites":
            names = self._favorites()
        elif kind == "group":
            groups = self._random_groups() if groups is None else groups
            group = next((g for g in groups or [] if g.get("id") == source.get("id")), None)
            if group is None:
                return None
            names = [str(item.get("artist") or "").strip() for item in group.get("items") or []]
        else:
            return None
        banned = set(self._banned())
        seen: set[str] = set()
        out = []
        for name in names:
            if name and name not in banned and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def random_sources(self) -> dict:
        """결과 화면 [… 연동됨] 메뉴 - 고를 수 있는 출처와 사람 수. 지금 출처가 없어졌으면 tab 으로 되돌려 둔다."""
        tools = self.random_tools()
        source = tools.get("source") or {"kind": "tab", "id": ""}
        pool = tools.get("pool") or {}
        query = str(pool.get("query") or "").strip().lower().replace("_", " ")
        skip = bool(tools.get("skip_seen"))
        seen = self.random_seen() if skip else set()

        def left(names: list[str]) -> int | None:
            return sum(1 for name in names if name not in seen) if skip else None

        try:
            artists, filter_name, weights, _t, _k = self._random_pool_list(
                str(pool.get("mode") or ""), str(pool.get("filter") or "all"), query, pool.get("search"))
            ranked = self.random_range_order(artists, weights)
            start, end = self.random_range_bounds(len(ranked), tools.get("range"))
            tab = {"filter_name": filter_name, "count": len(ranked), "query": str(pool.get("query") or ""),
                   "range_count": end - start, "remaining": left(ranked[start:end]),
                   "bucket_posts": self.random_bucket_posts(ranked, weights)}
        except Exception:  # noqa: BLE001 - 숫자는 장식이다
            tab = {"filter_name": "", "count": None, "query": "", "range_count": None, "remaining": None,
                   "bucket_posts": None}
        groups = self._random_groups() or []
        favorites = self.random_source_names({"kind": "favorites"}) or []
        rows = [{"kind": "favorites", "id": "", "name": "관심 작가", "count": len(favorites),
                 "remaining": left(favorites)}]
        # 임시 그룹(작가 패널 [기억] 칸)을 위로 - 나머지는 저장된 순서. 이름 없는 임시 창은 뺀다.
        slot = [g for g in groups if g.get("slot") == "link"]
        named = [g for g in groups if not g.get("temp")]
        for group in slot + named:
            names = self.random_source_names({"kind": "group", "id": group["id"]}, groups) or []
            rows.append({"kind": "group", "id": group["id"], "name": group["name"], "count": len(names),
                         "remaining": left(names), "slot": group.get("slot") == "link"})
        if source.get("kind") == "group" and not any(g.get("id") == source.get("id") for g in groups):
            source = self.set_random_source({"kind": "tab"})
        return {"source": source, "tab": tab, "sources": rows, "range": tools.get("range") or [0, 100],
                "skip_seen": skip}

    def set_random_source(self, source: Any) -> dict:
        """출처를 바꾼다(정규화한 값을 돌려준다)."""
        normalized = self._normalize_random_source(source)
        with self._options_lock:
            self._save_options_locked({"random_tools": {"source": normalized}}, internal=True)
        return normalized

    def set_random_source_options(self, *, range_value: Any = None, skip_seen: Any = None) -> dict:
        """아티스트 탭 구간 · 이번 세션 중복 스킵. 스킵을 끄면 '이미 뽑힌 작가' 를 비운다(사용자 지정 2026-11-04)."""
        changes: dict[str, Any] = {}
        if range_value is not None:
            changes["range"] = self._normalize_random_range(range_value)
        if skip_seen is not None:
            changes["skip_seen"] = bool(skip_seen)
        if changes:
            with self._options_lock:
                self._save_options_locked({"random_tools": changes}, internal=True)
        if skip_seen is not None and not skip_seen:
            with self._random_seen_lock:
                self._random_seen.clear()
        return self.random_tools()

    def draw_random_weight(self, tools: dict) -> float:
        """[랜덤 가중치] 켬 = start ~ end 를 step 간격으로 고른다. 끔 = 저장된 손잡이 값."""
        tools = self._normalize_random_tools(tools)
        if not tools["random_weight"]:
            return tools["weight"]
        start, end, step = tools["weight_start"], tools["weight_end"], tools["weight_step"]
        if end < start:
            start, end = end, start
        steps = int(math.floor((end - start) / step + 1e-9))
        return round(start + random.SystemRandom().randint(0, max(0, steps)) * step, 4)

    @staticmethod
    def format_artist_token(artist: str, weight: float, api_mode: str = "NAI", *, with_prefix: bool = True) -> str:
        """화면의 `formatArtistToken` 과 같은 서식. NAI = `w::artist:x ::` · 그 밖 = `(x:w)`(괄호 이스케이프).
        ⚠️ ANIMA 의 '@' 는 여기서 붙이지 않는다 - 보낼 때 `core.anima_artist_tags` 가 붙인다."""
        name = str(artist or "").strip()
        if not name:
            return ""
        try:
            value = float(weight)
        except (TypeError, ValueError):
            value = 1.0
        weighted = abs(value - 1.0) > 1e-9
        text = f"{value:.2f}".rstrip("0").rstrip(".") or "0"
        if str(api_mode or "NAI").strip().upper() == "NAI":
            body = f"artist:{name}" if with_prefix else name
            return f"{text}::{body} ::" if weighted else body
        body = re.sub(r"([()])", r"\\\1", name)
        return f"({body}:{text})" if weighted else body

    def random_tools(self) -> dict:
        return self.load_options().get("random_tools") or self._normalize_random_tools({})

    def main_random_token(self, api_mode: str) -> dict | None:
        """[메인 랜덤 버튼 연결] - 이번 랜덤 한 번에 얹을 작가 토큰(사용자 지정 2026-10-19).

        - 늘 저장된 목록에서 **무작위** 한 명 - 화면이 그 작가로 격자를 넘겨 고른다(`pick` · `page`).
          [생성 버튼 → 랜덤 아티스트] 와 상관없다(사용자 지시 2026-11-03 - 그 토글은 창의 Generate 단추 몫이다).
        - 작가 패널 [고정](`link_pin`) 중이면 뽑지 않고 그 작가(`pin_artist`) · 그 가중치(`weight` - [랜덤 가중치] 여도).
        뽑을 때 가중치는 손잡이 값, [랜덤 가중치] 면 매번 뽑는다. 꺼져 있거나 목록이 비면 None. 창이 닫혀 있어도 돈다."""
        # 고정 표(런타임)와 작가 · 가중치(파일)를 한 시점에서 읽는다 - 저장은 표를 먼저 바꾸고 파일을 쓴다(Codex 리뷰).
        with self._options_lock:
            tools = self.random_tools()
        if not tools.get("main_link") or tools.get("link_paused"):
            return None                            # 꺼짐 · [일시중단] - 이번 Random 에는 작가를 안 붙인다
        if tools.get("link_pin"):
            weight = tools["weight"]                # 고정 = 이 작가 · 이 가중치(패널 손잡이로 고친 값)
            artist = str(tools.get("pin_artist") or "").strip()   # 격자에서 다른 작가를 골라도 고정은 그대로
            if artist and artist in set(self._banned()):
                return None                       # 제외 작가는 고른 작가여도 붙이지 않는다(작가 패널 [숨김])
            token = self.format_artist_token(artist, weight, api_mode) if artist else ""
            return {"token": token, "artist": artist, "weight": weight, "pick": False} if token else None
        weight = self.draw_random_weight(tools)
        # [이번 세션 중복 스킵] - 이미 붙인 작가는 건너뛴다. 다 썼으면 `exhausted`(화면이 빨간 토스트) + 중복 허용으로 뽑는다.
        skip = bool(tools.get("skip_seen"))
        seen = self.random_seen() if skip else set()
        source = tools.get("source") or {}
        if source.get("kind") in ("favorites", "group"):
            # 관심 작가 · 그룹에서 뽑는다 - 창 격자와 다른 목록이라 창은 넘기지 않는다(`pick` 없음).
            # 비었으면 이번만 아티스트 탭에서 · 그룹이 지워졌으면 출처도 아티스트 탭으로 되돌린다(사용자 지정).
            names = self.random_source_names(source)
            if names is None and source.get("kind") == "group":
                self.set_random_source({"kind": "tab"})
            if names:
                fresh = [name for name in names if name not in seen]
                exhausted = skip and not fresh
                picked = self._random_sample(fresh or names, 1, ("source", source["kind"], source.get("id", ""), 1))
                if picked:
                    if skip:
                        self._mark_random_seen(picked[0])
                    token = self.format_artist_token(picked[0], weight, api_mode)
                    return {"token": token, "artist": picked[0], "weight": weight, "pick": False,
                            "source": source["kind"], "exhausted": exhausted} if token else None
        pool = tools.get("pool") or {}
        item = self.pick_random_artist(pool.get("mode", ""), pool.get("filter", "all"), pool.get("query", ""),
                                       range_pct=tools.get("range"), exclude=seen if skip else None,
                                       search=pool.get("search"))
        if not item:
            return None
        if skip:
            self._mark_random_seen(item["artist"])
        token = self.format_artist_token(item["artist"], weight, api_mode)
        return {"token": token, "artist": item["artist"], "weight": weight, "pick": True,
                "page": item.get("page"), "image_url": item.get("image_url", ""), "source": "tab",
                "exhausted": bool(item.get("exhausted"))} if token else None

    def load_options(self, mode: str = "") -> dict:
        path = self._options_path()
        if not path.exists():
            return self._with_runtime_toggles(self._normalize_options({}, mode))
        try:
            return self._with_runtime_toggles(self._normalize_options(json.loads(path.read_text(encoding="utf-8")), mode))
        except Exception as exc:
            _safe_log(
                f"🌐 Headless Artist Thumb: options load failed — {exc}",
                f"[WARN] Headless Artist Thumb: options load failed - {exc}",
            )
            return self._with_runtime_toggles(self._normalize_options({}, mode))

    def _with_runtime_toggles(self, options: dict) -> dict:
        """세 토글은 파일이 아니라 이번 실행의 값으로(사용자 지시 2026-10-19)."""
        tools = options.get("random_tools")
        if isinstance(tools, dict):
            tools.update(getattr(self, "_random_toggles", {}))
            tools["pin_artist"] = getattr(self, "_random_pin_artist", "") if tools.get("link_pin") else ""
        return options

    def save_options(self, options: dict) -> dict:
        with self._options_lock:
            return self._save_options_locked(options)

    # ── 결과 화면 작가 패널의 [고정](사용자 지정 2026-11-03) ──────────────────────
    #  고정 = `link_pin` 켬 + 붙일 작가(`focus`) · 가중치. 메인 Random 은 고정이 없으면 늘 뽑는다.
    #  [생성 버튼 -> 랜덤 아티스트] 는 상위 정책이다. 켜져 있을 때 고정하면 끄고 `pin_hold` 로 '고정이 껐다' 를
    #  기억한다. 고정을 풀면(또는 그 작가를 숨기면 · 연결을 끄면) 다시 켜고 표를 지운다. 정책이 원래 꺼져 있었으면
    #  토글은 건드리지 않는다. 사용자가 토글을 직접 누르면 정책을 되찾은 것이라 표만 지우고, 켰으면 무작위를
    #  원한 것이라 고정도 푼다.
    def link_pin(self, artist: str, weight: Any = None, pin: bool = True) -> dict:
        """고정(`pin`) = 다음 Random 도 이 작가 · 이 가중치. 해제 = 빌린 정책을 돌려준다. 돌려주는 값 = random_tools."""
        with self._options_lock:
            tools = self.load_options().get("random_tools") or {}
            changes: dict = {}
            if pin:
                name = str(artist or "").strip()
                if not name:
                    raise ValueError("artist is required")
                if name in set(self._banned()):
                    # 숨긴 작가는 붙이지 않는다(`main_random_token`) - 고정해도 아무것도 안 붙는 상태를 만들지 않는다.
                    raise ValueError("숨긴 작가는 고정할 수 없습니다 - [숨김] 을 먼저 푸세요.")
                changes.update(focus=name, link_pin=True, pin_artist=name)
                try:
                    value = float(weight)
                    if math.isfinite(value):
                        changes["weight"] = value
                except (TypeError, ValueError):
                    pass
                if tools.get("gen_pick"):
                    changes.update(gen_pick=False, pin_hold=True)
            else:
                if tools.get("link_pin"):
                    changes["link_pin"] = False
                if tools.get("pin_hold"):
                    changes.update(gen_pick=True, pin_hold=False)
            if not changes:
                return tools
            return self._save_options_locked({"random_tools": changes}, internal=True)["random_tools"]

    def set_random_weight(self, weight: Any) -> dict:
        """작가 패널 손잡이 - 랜덤 작가 가중치(아티스트 창 손잡이와 같은 값)만 바꾼다. 고정 · 정책은 그대로
        (사용자 지정 2026-11-03 - 바꾸면 고정하던 것을 바꿨다). 고정 중이면 고정 작가도 이 값을 쓴다. 돌려주는 값 = random_tools."""
        try:
            value = float(weight)
        except (TypeError, ValueError) as exc:
            raise ValueError("weight must be a number") from exc
        if not math.isfinite(value):
            raise ValueError("weight must be a number")
        with self._options_lock:
            return self._save_options_locked({"random_tools": {"weight": value}}, internal=True)["random_tools"]

    def release_link_pin(self, artist: str = "") -> bool:
        """고정을 풀고 빌린 정책을 돌려준다(`artist` 를 주면 그 작가를 고정한 때만). 풀었으면 True."""
        with self._options_lock:
            tools = self.load_options().get("random_tools") or {}
            if not tools.get("link_pin") and not tools.get("pin_hold"):
                return False
            if artist and str(tools.get("pin_artist") or "").strip() != str(artist).strip():
                return False
            changes: dict = {"link_pin": False}
            if tools.get("pin_hold"):
                changes.update(gen_pick=True, pin_hold=False)
            self._save_options_locked({"random_tools": changes}, internal=True)
            return True

    def _save_options_locked(self, options: dict, *, internal: bool = False) -> dict:
        requested_mode = options.get("mode") if isinstance(options, dict) else ""
        mode = self._options_mode(requested_mode)
        current = self.load_options(mode)
        if isinstance(options, dict):
            mode_values = current["modes"].setdefault(mode, {"prefix": "", "postfix": ""})
            if "prefix" in options:
                mode_values["prefix"] = str(options.get("prefix") or "")
            if "postfix" in options:
                mode_values["postfix"] = str(options.get("postfix") or "")
            # 랜덤 도구는 보낸 칸만 바꾼다(프리픽스 저장이 이것을 지우지 않게 · 반대도).
            if isinstance(options.get("random_tools"), dict):
                incoming = dict(options["random_tools"])
                pin_artist = incoming.pop("pin_artist", None)    # 고정 길(`link_pin`)만 바꾼다
                previous = current.get("random_tools", {})
                if not internal:
                    incoming.pop("pin_hold", None)        # 두 표는 고정 길(`link_pin` 메서드)만 다룬다
                    incoming.pop("link_pin", None)
                    if "main_link" in incoming and not incoming["main_link"]:
                        # 연결을 끄면 패널이 사라진다 - 보이지 않는 곳에 고정 · 빌린 정책 · 일시중단을 남기지 않는다
                        incoming["link_paused"] = False
                        if previous.get("link_pin"):
                            incoming["link_pin"] = False
                        if previous.get("pin_hold"):
                            incoming.update(gen_pick=True, pin_hold=False)
                    elif "gen_pick" in incoming:
                        if previous.get("pin_hold"):
                            incoming["pin_hold"] = False  # 사용자가 토글을 직접 눌렀다 - 정책을 되찾았다
                        if incoming["gen_pick"] and previous.get("link_pin"):
                            incoming["link_pin"] = False  # 무작위를 켰다 - 고정도 푼다
                current["random_tools"] = self._normalize_random_tools({**previous, **incoming})
                for key in self.RANDOM_TOOL_TOGGLES:
                    self._random_toggles[key] = bool(current["random_tools"].get(key))
                if internal and pin_artist is not None:
                    self._random_pin_artist = str(pin_artist).strip()[:300]
                if not current["random_tools"].get("link_pin"):
                    self._random_pin_artist = ""
                current["random_tools"]["pin_artist"] = self._random_pin_artist
        selected = current["modes"].get(mode, {"prefix": "", "postfix": ""})
        current["version"] = 2
        current["mode"] = mode
        current["prefix"] = selected.get("prefix", "")
        current["postfix"] = selected.get("postfix", "")
        path = self._options_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # 파일에는 세 토글을 꺼짐으로 쓴다 - 다시 켜면 꺼진 채 시작한다(돌려주는 값은 이번 실행의 값).
        on_disk = dict(current)
        if isinstance(current.get("random_tools"), dict):
            on_disk["random_tools"] = {**{k: v for k, v in current["random_tools"].items() if k != "pin_artist"},
                                       **{key: False for key in self.RANDOM_TOOL_TOGGLES}}
        path.write_text(json.dumps(on_disk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return current

    def _normalize_values(self, values: Any) -> list[str]:
        seen = set()
        normalized = []
        if not isinstance(values, (list, tuple, set)):
            return []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _merge_values(self, primary: Any, additions: Any) -> list[str]:
        return self._normalize_values([*self._normalize_values(primary), *self._normalize_values(additions)])

    def _normalize_state(self, data: Any, fallback: dict | None = None) -> dict:
        source = data if isinstance(data, dict) else {}
        fallback = fallback if isinstance(fallback, dict) else {}
        return {
            "version": 1,
            "favorites": self._normalize_values(source.get("favorites", fallback.get("favorites", []))),
            "banned": self._normalize_values(source.get("banned", fallback.get("banned", []))),
        }

    def _legacy_state(self) -> dict:
        return self._normalize_state({
            "favorites": self._merge_values(
                self._read_lines(self._favorite_path()),
                self._read_lines(self._legacy_favorite_path()),
            ),
            "banned": self._merge_values(
                self._read_lines(self._banned_path()),
                self._read_lines(self._legacy_banned_path()),
            ),
        })

    def _read_state_file(self, *, merge_legacy_additions: bool = True) -> dict:
        path = self._state_path()
        if not path.exists():
            raise FileNotFoundError(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"artist thumb state JSON is invalid: {path}: {exc}") from exc
        state = self._normalize_state(data)
        if merge_legacy_additions:
            legacy = self._legacy_state()
            state["favorites"] = self._merge_values(state["favorites"], legacy["favorites"])
            state["banned"] = self._merge_values(state["banned"], legacy["banned"])
        return state

    def _sync_state_mirrors(self, state: dict) -> None:
        normalized = self._normalize_state(state)
        favorites_written = self._write_lines(self._favorite_path(), normalized["favorites"])
        self._write_lines(self._banned_path(), normalized["banned"])
        if favorites_written and self._on_favorites_written is not None:
            try:
                self._on_favorites_written(self._favorite_path())
            except Exception as exc:  # 알림이 실패해도 관심 등록 자체는 성공이다
                _safe_log(
                    f"🌐 Headless Artist Thumb: favorite wildcard refresh failed — {exc}",
                    f"[WARN] Headless Artist Thumb: favorite wildcard refresh failed - {exc}",
                )

    def _write_state(self, state: dict) -> dict:
        normalized = self._normalize_state(state)
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        try:
            temp_path.replace(path)
        except PermissionError:
            path.write_text(payload, encoding="utf-8")
            try:
                temp_path.unlink(missing_ok=True)
            except PermissionError:
                pass
        self._sync_state_mirrors(normalized)
        return normalized

    def ensure_state(self) -> dict:
        with self._lock:
            if not self._state_path().exists():
                return self._write_state(self._legacy_state())
            return self._read_state_file()

    def _state(self) -> dict:
        with self._lock:
            return self._read_state_file()

    def _favorites(self) -> list[str]:
        return list(self._state().get("favorites", []))

    def favorite_artists(self) -> list[str]:
        """관심 작가 목록(등록 순서). '관심 작가' 그룹 창이 이것을 그대로 보여 준다."""
        return self._favorites()

    # ── 관심 작가 = 하나의 그룹 (사용자 지정 2026-09-26) ─────────────────────
    #  그룹 창에서 넣고·빼고·순서를 바꾸면 여기로 온다. 저장은 **관심 목록 하나**다 -
    #  그룹 파일에 사본을 두면 두 곳이 갈린다. `favorite_artist.txt` 와일드카드도
    #  `_write_state` 한 길로 따라간다.
    @staticmethod
    def _clean_favorite_name(value: Any) -> str:
        name = " ".join(str(value or "").split())
        if name.lower().startswith("artist:"):
            name = name[len("artist:"):].strip()
        return name if 0 < len(name) <= 200 else ""

    def add_favorites(self, artists: Any, mode: str = "") -> dict:
        names = [n for n in (self._clean_favorite_name(v) for v in (artists or [])) if n]
        with self._lock:
            state = self._state()
            favorites = list(state.get("favorites", []))
            fresh = [n for n in dict.fromkeys(names) if n not in favorites]
            if fresh:
                state["favorites"] = favorites + fresh
                self._write_state(state)
                for artist in fresh:
                    self._cache_favorite_from_loaded_mode(artist, mode)
        return {"added": len(fresh), "skipped": len(names) - len(fresh)}

    def remove_favorites(self, artists: Any) -> dict:
        names = {n for n in (self._clean_favorite_name(v) for v in (artists or [])) if n}
        with self._lock:
            state = self._state()
            favorites = list(state.get("favorites", []))
            kept = [a for a in favorites if a not in names]
            removed = [a for a in favorites if a in names]
            if removed:
                state["favorites"] = kept
                self._write_state(state)
                for artist in removed:
                    self._remove_favorite_thumbnail_cache(artist)
        return {"removed": len(removed)}

    def reorder_favorites(self, artists: Any) -> dict:
        """보낸 순서대로 앞에 세우고, 보내지 않은 것은 원래 순서로 뒤에 붙인다(그룹과 같은 규칙)."""
        wanted = [n for n in (self._clean_favorite_name(v) for v in (artists or [])) if n]
        with self._lock:
            state = self._state()
            favorites = list(state.get("favorites", []))
            front = [a for a in dict.fromkeys(wanted) if a in favorites]
            ordered = front + [a for a in favorites if a not in front]
            if ordered != favorites:
                state["favorites"] = ordered
                self._write_state(state)
        return {}

    def _banned(self) -> list[str]:
        return list(self._state().get("banned", []))

    def _generated_model_filters(self, weights: dict, banned_set: set[str]) -> list[dict]:
        """FILTER 하단의 '생성한 모델' 묶음. 앞에 구분선 항목을 하나 끼운다."""
        try:
            models = self.generated_models()
        except Exception:
            return []
        rows = []
        for entry in models:
            model_name = entry["name"]
            listed = [a for a in self.generated_artists_for_model(model_name)
                      if a in weights and a not in banned_set]
            if listed:
                rows.append({"key": entry["key"], "name": model_name, "count": len(listed)})
        if not rows:
            return []
        return [{"key": "__generated_sep__", "name": "생성한 모델", "count": 0,
                 "separator": True}, *rows]

    def _custom_filters(self, weights: dict | None = None, banned_set: set[str] | None = None) -> list[dict]:
        bases = [self.state_root]
        if self.legacy_state_root.resolve() != self.state_root.resolve():
            bases.append(self.legacy_state_root)
        filters = []
        weights = weights or self._artist_weights()
        banned_set = banned_set if banned_set is not None else set(self._banned())
        seen_keys = set()
        for base in bases:
            if not base.exists():
                continue
            for path in sorted(base.glob("*.txt")):
                if path.name == "banned_artist.txt":
                    continue
                key = f"custom:{path.stem}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                items = self._read_lines(path)
                filters.append({
                    "key": key,
                    "name": path.stem,
                    "count": len([artist for artist in items if artist in weights and artist not in banned_set]),
                })
        return filters

    def _normalize_thumbnail_cache(self, data: Any) -> dict:
        source = data if isinstance(data, dict) else {}
        raw_items = source.get("items", source.get("thumbnails", {}))
        if not isinstance(raw_items, dict):
            raw_items = {}
        items = {}
        for artist, value in raw_items.items():
            artist_name = str(artist or "").strip()
            if not artist_name:
                continue
            if isinstance(value, dict):
                thumbnail = str(value.get("thumbnail") or value.get("image") or "").strip()
                mode = str(value.get("mode") or "").strip()
                updated_at = str(value.get("updated_at") or "").strip()
            elif isinstance(value, (list, tuple)):
                thumbnail = str(value[0] if value else "").strip()
                mode = ""
                updated_at = ""
            else:
                thumbnail = str(value or "").strip()
                mode = ""
                updated_at = ""
            if thumbnail:
                items[artist_name] = {"mode": mode, "thumbnail": thumbnail, "updated_at": updated_at}
        return {"version": 1, "items": items}

    def _load_thumbnail_cache(self) -> dict:
        path = self._favorite_thumbnail_cache_path()
        if not path.exists():
            return {"version": 1, "items": {}}
        try:
            return self._normalize_thumbnail_cache(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise RuntimeError(f"artist thumb thumbnail cache JSON is invalid: {path}: {exc}") from exc

    def _write_thumbnail_cache(self, cache: dict) -> dict:
        normalized = self._normalize_thumbnail_cache(cache)
        path = self._favorite_thumbnail_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(path)
        return normalized

    def _cache_entry_from_data(self, artist: str, mode: str, thumb_data: dict) -> dict | None:
        artist_name = str(artist or "").strip()
        if not artist_name or not isinstance(thumb_data, dict):
            return None
        encoded_list = thumb_data.get(artist_name)
        if not isinstance(encoded_list, (list, tuple)) or not encoded_list:
            return None
        thumbnail = str(encoded_list[0] or "").strip()
        if not thumbnail:
            return None
        return {
            "mode": str(mode or "").strip(),
            "thumbnail": thumbnail,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def sync_favorite_thumbnail_cache(self, mode: str = "", thumb_data: dict | None = None) -> dict:
        mode_key = str(mode or "").strip()
        with self._lock:
            favorites = self._favorites()
            favorite_set = set(favorites)
            cache = self._load_thumbnail_cache()
            items = dict(cache.get("items") or {})
            changed = False
            removed = 0
            added = 0

            for artist in list(items.keys()):
                if artist not in favorite_set:
                    items.pop(artist, None)
                    removed += 1
                    changed = True

            missing_artists = [artist for artist in favorites if not items.get(artist, {}).get("thumbnail")]
            if mode_key and thumb_data is None:
                thumb_data = self._data_cache.get(mode_key)

            if mode_key and isinstance(thumb_data, dict):
                for artist in missing_artists:
                    entry = self._cache_entry_from_data(artist, mode_key, thumb_data)
                    if entry:
                        items[artist] = entry
                        added += 1
                        changed = True

            cache = self._write_thumbnail_cache({"version": 1, "items": items}) if changed else {"version": 1, "items": items}
            missing = len([artist for artist in favorites if not items.get(artist, {}).get("thumbnail")])
            return {
                "count": len(items),
                "added": added,
                "removed": removed,
                "missing": missing,
                "changed": changed,
                "path": str(self._favorite_thumbnail_cache_path()),
                "cache": cache,
            }

    def _cache_favorite_from_loaded_mode(self, artist: str, mode: str) -> bool:
        artist_name = str(artist or "").strip()
        mode_key = str(mode or "").strip()
        if not artist_name:
            return False
        with self._lock:
            # ⚠️ 모드를 모를 때(그룹 창에서 끌어 넣기)나 **가상 모드**(제 팩이 없어
            #    `_data_cache` 에 없다)에도 올라온 팩에서 찾는다 - 전에는 둘 다 사본 없이 끝났다.
            entry = (self._cache_entry_from_data(artist_name, mode_key, self._data_cache.get(mode_key) or {})
                     if mode_key else None) or self._loaded_thumbnail_entry(artist_name)
            if not entry:
                return False
            try:
                cache = self._load_thumbnail_cache()
            except Exception:
                cache = {"version": 1, "items": {}}
            items = dict(cache.get("items") or {})
            current = items.get(artist_name) or {}
            if current.get("thumbnail") == entry.get("thumbnail") and current.get("mode") == entry.get("mode"):
                return False
            items[artist_name] = entry
            self._write_thumbnail_cache({"version": 1, "items": items})
            return True

    def _remove_favorite_thumbnail_cache(self, artist: str) -> bool:
        artist_name = str(artist or "").strip()
        if not artist_name:
            return False
        with self._lock:
            try:
                cache = self._load_thumbnail_cache()
            except Exception:
                return False
            items = dict(cache.get("items") or {})
            if artist_name not in items:
                return False
            items.pop(artist_name, None)
            self._write_thumbnail_cache({"version": 1, "items": items})
            return True

    # ── 그룹 썸네일 사본 ───────────────────────────────────────────────
    #  그룹 창은 그림을 **지금 고른 모드의 팩**에서 찾는다. 다른 팩에서 끌어 온 작가는
    #  모드를 바꾸거나 새로고침하면 "No Image" 가 됐다(사용자 제보 2026-09-25: "복제해 올 때
    #  썸네일을 카피해 오지 않는다"). 관심 작가 캐시와 같은 방식으로 **그림 자체를** 복사해
    #  둔다 - 주소를 저장하면 팩을 바꾼 뒤 엉뚱한 그림이나 404 가 된다(믹스 띠와 같은 원칙).
    #  ⚠️ 복사는 **이미 메모리에 올라온 팩**에서만 한다. 팩 하나가 1.3GB(파싱 4초)라
    #     그림 한 장 때문에 새로 열지 않는다 - 사용자가 방금 본 그림의 팩은 올라와 있다.
    def _group_thumbnail_cache_path(self) -> Path:
        return self.state_root / "group_thumbnail_cache.json"

    def _load_group_thumbnail_cache(self) -> dict:
        path = self._group_thumbnail_cache_path()
        if not path.exists():
            return {"version": 1, "items": {}}
        try:
            return self._normalize_thumbnail_cache(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            # 파생 사본이다(원본은 팩) - 못 읽으면 빈 것으로 보고 다시 채운다.
            return {"version": 1, "items": {}}

    def _loaded_thumbnail_entry(self, artist: str) -> dict | None:
        for mode_key, data in list(self._data_cache.items()):
            entry = self._cache_entry_from_data(artist, mode_key, data)
            if entry:
                return entry
        return None

    def sync_group_thumbnail_cache(self, artists: Any) -> dict:
        """그룹에 든 작가 = 사본을 둔다. 어느 그룹에도 없게 된 작가의 사본은 지운다."""
        wanted = self._normalize_values(artists if isinstance(artists, (list, tuple, set)) else [])
        wanted_set = set(wanted)
        with self._lock:
            items = dict(self._load_group_thumbnail_cache().get("items") or {})
            added = removed = 0
            for artist in list(items.keys()):
                if artist not in wanted_set:
                    items.pop(artist, None)
                    self._image_cache.pop(("__group_cache__", artist), None)
                    removed += 1
            for artist in wanted:
                if items.get(artist, {}).get("thumbnail"):
                    continue
                entry = self._loaded_thumbnail_entry(artist)
                if entry:
                    items[artist] = entry
                    added += 1
            if added or removed:
                path = self._group_thumbnail_cache_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = path.with_name(f"{path.name}.tmp")
                temp_path.write_text(json.dumps({"version": 1, "items": items}, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
                temp_path.replace(path)
            missing = sum(1 for artist in wanted if not items.get(artist, {}).get("thumbnail"))
            return {"count": len(items), "added": added, "removed": removed, "missing": missing}

    def group_image_payload(self, artist: str) -> tuple[bytes, str]:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        cache_key = ("__group_cache__", artist_name)
        with self._lock:
            cached = self._image_cache.get(cache_key)
            if cached:
                return cached
            entry = (self._load_group_thumbnail_cache().get("items") or {}).get(artist_name) or {}
            encoded = entry.get("thumbnail")
        if not encoded:
            raise FileNotFoundError(f"Group artist thumbnail not found: {artist_name}")
        image_bytes, media_type = self._image_payload_from_encoded(encoded)
        with self._lock:
            if len(self._image_cache) > 512:
                self._image_cache.pop(next(iter(self._image_cache)), None)
            self._image_cache[cache_key] = (image_bytes, media_type)
        return image_bytes, media_type

    # ── 보기(벤치) 출력 ─────────────────────────────────────────────────
    #  보기 하나 = 벤치 조건 한 벌(`core/artist_bench_views.py`). 그 조건으로 뽑은 그림은
    #  작가마다 한 장, `bench_views/<보기>/<작가>.webp`. **사용자 생성 썸네일과 섞지 않는다** -
    #  기본 썸네일 자리를 벤치 그림이 덮으면 '보기를 끄면 원래 그림' 이 성립하지 않는다.
    def _view_dir(self, view_id: str) -> Path:
        return self.state_root / "bench_views" / self._safe_component(view_id, "view")

    def _view_file(self, view_id: str, artist: str) -> Path:
        return self._view_dir(view_id) / (self._safe_component(artist, "artist") + ".webp")

    @staticmethod
    def view_image_url(view_id: str, artist: str, stamp: int = 0) -> str:
        # `t=` 는 다시 뽑았을 때 브라우저가 옛 그림을 쓰지 않게 하는 표(파일 시각).
        return (f"/api/artist-thumb/view-image?view={quote(str(view_id), safe='')}"
                f"&artist={quote(str(artist), safe='')}&t={int(stamp)}")

    def view_images(self, view_id: str, artists: Any) -> dict[str, str]:
        """작가 -> 그 보기의 그림 주소(있는 것만). 폴더를 **한 번** 훑는다(3천 명도 한 번)."""
        vid = str(view_id or "").strip()
        folder = self._view_dir(vid) if vid else None
        if folder is None or not folder.is_dir():
            return {}
        stamps: dict[str, int] = {}
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.endswith(".webp") and entry.is_file():
                    stamps[entry.name] = int(entry.stat().st_mtime)
        out = {}
        for artist in artists if isinstance(artists, (list, tuple)) else []:
            name = str(artist or "").strip()
            stamp = stamps.get(self._safe_component(name, "artist") + ".webp")
            if name and stamp is not None:
                out[name] = self.view_image_url(vid, name, stamp)
        return out

    def save_view_thumbnail(self, pil_image: Any, artist: str, view_id: str) -> dict[str, Any] | None:
        """벤치 결과를 그 보기 칸에 남긴다. 같은 작가를 다시 뽑으면 덮어쓴다(사용자 생성과 같은 규칙)."""
        artist_name = str(artist or "").strip()
        vid = str(view_id or "").strip()
        if not artist_name or not vid or pil_image is None:
            return None
        from PIL import Image

        target = self._view_file(vid, artist_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        thumb = pil_image.copy()
        if thumb.mode not in ("RGB", "RGBA"):
            thumb = thumb.convert("RGB")
        thumb.thumbnail(self.GENERATED_THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
        tmp_path = target.with_name(target.name + ".tmp")
        thumb.save(tmp_path, "WEBP", quality=82)
        tmp_path.replace(target)
        return {"artist": artist_name, "view": vid,
                "url": self.view_image_url(vid, artist_name, int(target.stat().st_mtime))}

    def view_image_payload(self, view_id: str, artist: str) -> tuple[bytes, str]:
        artist_name = str(artist or "").strip()
        vid = str(view_id or "").strip()
        if not artist_name or not vid:
            raise ValueError("view and artist are required")
        try:
            return self._view_file(vid, artist_name).read_bytes(), "image/webp"
        except OSError as exc:
            raise FileNotFoundError(f"View thumbnail not found: {vid} / {artist_name}") from exc

    def view_generation_overrides(self, payload: dict, view: dict, schema: dict | None = None, *,
                                  current_model: str | None = None, managed_anima: bool = False) -> dict:
        """보기의 조건으로 생성한다. 글(prefix/postfix/네거티브) · 해상도 · 설정 · 시드는 **보기의 것**,
        작가 표기(`positive`)만 화면이 보낸다 - 표기 규칙(NAI `artist:` · Anima `@` · 괄호 이스케이프)은
        화면의 한 곳이 주인이다. 작가 태그는 **맨 앞**이다(작가 -> prefix -> postfix, 사용자 지정 2026-09-26 -
        NAIA 의 랜덤 생성이 작가를 PE prefix 앞에 붙이는 것과 같은 자리).

        ⚠️ 해상도는 **그대로** 쓴다(썸네일 해상도로 보정하지 않는다) - 비교 조건이다.
        ⚠️ 실행 모드 · 시드 고정 여부도 **보기가** 정한다(Codex 리뷰 2026-09-26 #6 · #7).
        `current_model` = 지금 백엔드에 올라 있는 모델(WEBUI 는 요청마다 모델을 바꾸지 않는다 - #5).
        """
        payload = payload if isinstance(payload, dict) else {}
        api_mode = str(view.get("api_mode") or "NAI").upper()
        merged = {
            **payload,
            # final_prompt 는 prefix, positive, postfix 차례로 잇는다 - 작가를 맨 앞에 두려고 자리를 바꿔 싣는다.
            "prefix": str(payload.get("positive") or ""),
            "positive": view.get("prefix", ""),
            "postfix": view.get("postfix", ""),
            "negative_prompt": view.get("negative", ""),
            "width": view.get("width"),
            "height": view.get("height"),
            "artist_thumb_use_active_resolution": True,
        }
        overrides = self.generation_overrides(merged)
        overrides["random_resolution"] = False
        overrides["auto_fit_resolution"] = False
        overrides["artist_thumb_view"] = str(view.get("id") or "")
        settings = view.get("settings") if isinstance(view.get("settings"), dict) else {}
        options = schema if isinstance(schema, dict) else {}
        for key, value in settings.items():
            # Only group-view requests reach this method. Keep their editable
            # settings (including rescale); ordinary requests inherit the session.
            if managed_anima and api_mode == "COMFYUI" and key in {"model", "sampler", "scheduler"}:
                continue
            if key in {"model", "sampler", "scheduler"}:
                allowed = options.get(f"options_{key}")
                if isinstance(allowed, list) and allowed and value not in allowed:
                    raise ValueError(f"'{value}' 은(는) 지금 {key} 선택지에 없습니다 - 보기를 고치거나 모드를 맞추세요")
            if key == "model" and api_mode == "WEBUI" and current_model and value and value != current_model:
                # WEBUI 요청에는 모델 칸이 없다(모델은 WebUI 전역 설정) - 실으면 조용히 버려져 다른 모델로 뽑힌다.
                raise ValueError(f"이 보기의 모델({value})이 지금 WEBUI 모델({current_model})과 다릅니다 - "
                                 "WEBUI 는 요청마다 모델을 바꾸지 못합니다. 모델을 맞추거나 보기를 고치세요")
            if key == "cfg_rescale" and api_mode == "WEBUI":
                continue
            param = {"scale": "cfg_scale",
                     "cfg_rescale": "rescale_cfg" if api_mode == "COMFYUI" else "cfg_rescale"}.get(key, key)
            overrides[param] = value
        seed = int(view.get("seed", -1))
        overrides["seed"] = seed
        # 안 실으면 메인 화면의 `seed_fixed=True` 가 남아 -1 이 0 으로 굳는다(매번 랜덤이 아니게 된다 - #7).
        overrides["seed_fixed"] = seed >= 0
        # 요청 본문의 `api_mode` 로 보기 검사를 비켜 가지 못하게 - 라우트가 이 값을 실행 모드로 쓴다(#6).
        overrides["api_mode"] = api_mode
        # 캐릭터: `main` = 메인 화면의 캐릭터(아무것도 싣지 않으면 생성이 늘 하던 대로 메인에서 가져온다).
        #         `own`  = **보기의 것만**. 보기에 없으면 메인 화면의 캐릭터가 늦게 끼어들지 못하게 막는다
        #                  (Late binding) - 안 막으면 켜 둔 캐릭터가 모든 벤치에 섞인다.
        if str(view.get("character_mode") or "own") == "main":
            return overrides
        characters = [c for c in (view.get("characters") or []) if str(c.get("prompt") or "").strip()]
        if characters and api_mode != "NAI":
            # 캐릭터 프롬프트는 NAI 요청에만 실린다 - 다른 백엔드에서는 조용히 사라진다(#5).
            raise ValueError("독립 캐릭터 프롬프트는 NAI 보기에서만 쓸 수 있습니다 - [메인] 으로 바꾸거나 캐릭터를 비우세요")
        if characters:
            overrides["characters"] = [str(c["prompt"]) for c in characters]
            overrides["uc"] = [str(c.get("uc") or "") for c in characters]
            overrides["character_positions"] = []
        else:
            overrides["_skip_character_late_binding"] = True
        return overrides

    def load_data(self, mode: str) -> dict:
        key = str(mode or "").strip()
        if not key:
            return {}
        if self.is_virtual_mode(key):
            # 가상 모드는 **제 팩이 없다**. 작가 -> 주인 팩 표가 그 자리를 대신한다.
            return self._virtual_owner_map(key)
        with self._lock:
            info = self._mode_info(key)
            file_state = self._file_state(info)
            # ⚠️ **낡아도 있으면 쓴다**(사용자 지정 2026-09-03).
            #    예전에는 `needs_update` 면 캐시를 버리고 예외를 던져서, 2.5GB 를 받는
            #    내내 그리드가 "No matching artists." 로 비어 있었다 - 옛 팩이 디스크에
            #    멀쩡히 있는데도 아무것도 못 봤다. 갱신은 **알리는 것**이지 막는 것이
            #    아니다. 다 받으면 파일 크기가 바뀌고, 아래 캐시 열쇠가 그걸 알아채
            #    새 팩으로 갈아 끼운다.
            cached = self._data_cache.get(key)
            if cached is not None and self._data_cache_size.get(key) == file_state["size"]:
                if key == "NAID4.5F-31000":
                    self.sync_favorite_thumbnail_cache(key, cached)
                return cached
            if not file_state["exists"]:
                self._data_cache.pop(key, None)
                self._data_cache_size.pop(key, None)
                raise FileNotFoundError(f"Artist thumbnail data not found: {self._mode_path(key)}")
            # 화면이 '무엇을 기다리는지' 볼 수 있게 적어 둔다(load_status). 가상 모드면 몇 번째 팩인지도.
            self._load_status = {"active": True, "mode": key, "label": str(info.get("label") or key),
                                 "size_mb": file_state["size_mb"], "started_at": time.time(), **self._load_group}
            try:
                text = self._mode_path(key).read_text(encoding="utf-8")
                # ⚠️ 파싱은 한 덩어리다(1.5GB · 약 2초 - 그동안 다른 요청은 못 돈다). 끼어들 틈은 파일을 읽는 동안뿐이라,
                #    그 사이 [중단] 이 왔으면 파싱 전에 멈춘다.
                self._raise_if_load_cancelled()
                data = json.loads(text)
                del text
            finally:
                self._load_status = {"active": False}
                if not self._load_group:
                    self._load_cancel = False
            if not isinstance(data, dict):
                raise ValueError("Artist thumbnail data is invalid")
            # ⚠️ 예전에는 여기서 캐시를 **통째로 비웠다**. 가상 모드는 팩 여럿에
            #    걸쳐 있어서 그러면 한 페이지를 그리는 동안 1.3GB 를 왕복한다 -
            #    한도만큼 남기고 가장 오래된 것부터 버린다.
            while len(self._data_cache) >= max(1, self._data_cache_limit):
                oldest = next(iter(self._data_cache))
                self._data_cache.pop(oldest, None)
                self._data_cache_size.pop(oldest, None)
            self._image_cache.clear()
            self._data_cache[key] = data
            self._data_cache_size[key] = file_state["size"]
            if key == "NAID4.5F-31000":
                self.sync_favorite_thumbnail_cache(key, data)
            return data

    @staticmethod
    def _format_count(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    def _base_list(
        self,
        filter_key: str,
        weights: dict,
        *,
        exclude_banned: bool = True,
        allow_banned_filter: bool = True,
    ) -> tuple[list[str], str]:
        key = str(filter_key or "all").strip() or "all"
        favorites = self._favorites()
        banned = self._banned()
        banned_set = set(banned)
        if key == "favorites":
            items = [artist for artist in favorites if artist in weights]
            return ([artist for artist in items if artist not in banned_set] if exclude_banned else items), "관심 작가"
        if key == "banned":
            if not allow_banned_filter:
                return [], "제외 작가"
            return [artist for artist in banned if artist in weights], "제외 작가"
        if key.startswith("model:"):
            model_name = key.split(":", 1)[1].strip()
            # 지금 모드 안에서만 (백엔드가 다르면 그림의 결이 다르다).
            items = [a for a in self.generated_artists_for_model(model_name) if a in weights]
            return ([a for a in items if a not in banned_set] if exclude_banned else items), model_name
        if key.startswith("custom:"):
            name = Path(key.split(":", 1)[1].strip()).name
            items = self._read_lines(self._path("artist_thumb") / f"{name}.txt")
            items = [artist for artist in items if artist in weights]
            return ([artist for artist in items if artist not in banned_set] if exclude_banned else items), name
        return [artist for artist in weights.keys() if artist not in banned_set], "전체 목록"

    def _random_sample(self, artists: list[str], sample_size: int, history_key: tuple[str, str, str, int]) -> list[str]:
        if sample_size <= 0 or not artists:
            return []
        with self._lock:
            recent = set(self._random_history.get(history_key, []))
        candidates = [artist for artist in artists if artist not in recent]
        if len(candidates) < sample_size:
            candidates = list(artists)
        picked = random.SystemRandom().sample(candidates, min(sample_size, len(candidates)))
        with self._lock:
            history = [artist for artist in self._random_history.get(history_key, []) if artist in artists]
            history.extend(picked)
            max_history = max(sample_size * 8, sample_size)
            self._random_history[history_key] = history[-max_history:]
            if len(self._random_history) > 64:
                self._random_history.pop(next(iter(self._random_history)), None)
        return picked

    def state(self) -> dict:
        weights = self._artist_weights()
        favorites = self._favorites()
        banned = self._banned()
        banned_set = set(banned)
        try:
            favorite_thumbnail_cache = self.sync_favorite_thumbnail_cache()
            favorite_thumbnail_cache.pop("cache", None)
        except Exception as exc:
            favorite_thumbnail_cache = {
                "count": 0,
                "added": 0,
                "removed": 0,
                "missing": len(favorites),
                "changed": False,
                "error": str(exc),
            }
        modes = []
        for key, info in self.ARTIST_THUMB_MODES.items():
            file_state = self._file_state(info)
            modes.append({
                "key": key,
                "label": str(info.get("label") or key),
                "available": file_state["available"],
                "needs_update": file_state["needs_update"],
                # ⚠️ 화면은 **`exists` 로 판단해야 한다.** `available` 은 "최신인가" 지
                #    "볼 수 있는가" 가 아니다 - 갱신 중에도 옛 팩이 있으면 그려야 한다
                #    (사용자 제보 2026-09-03: 2.5GB 받는 내내 빈 격자였다).
                "exists": file_state["exists"],
                "loaded": key in self._data_cache and file_state["exists"],
                "size": file_state["size"],
                "expected_size": file_state["expected_size"],
                "size_mb": file_state["size_mb"],
                "expected_size_mb": file_state["expected_size_mb"],
                "sha256": file_state["sha256"],
            })
        virtual_rows = []
        for key, spec in self.ARTIST_THUMB_VIRTUAL_MODES.items():
            members = self.virtual_members(key)
            pending = self.virtual_pending(key)
            # 다음에 채울 한 팩. 이것이 [Download]/[Update] 가 실제로 받는 대상이다.
            nxt = self.ARTIST_THUMB_MODES.get(pending[0]) if pending else None
            nxt_state = self._file_state(nxt) if nxt else None
            virtual_rows.append({
                "key": key,
                "label": str(spec.get("label") or key),
                # ⚠️ `exists` 는 "지금 볼 수 있는가" 다 - 하나라도 있으면 참이고,
                #    그러면 화면은 **받는 화면 대신 목록**을 그린다(사용자 지정:
                #    "하나라도 있으면 먼저 존재하는 파일부터 로드").
                "exists": bool(members),
                # `available` 은 "다 찼는가". 빠진 것이 있으면 거짓이라 갱신 줄이 선다.
                "available": bool(members) and not pending,
                # 하나라도 있는데 빠진 것이 있다 = 갱신 줄로 한 팩씩 채운다.
                # 하나도 없으면 갱신이 아니라 **받기**다(그때는 받는 화면이 뜬다).
                "needs_update": bool(members) and bool(pending),
                "loaded": any(m in self._data_cache for m in members),
                "size": 0,
                "expected_size": 0,
                "size_mb": 0,
                # 받는 화면이 적을 용량 - 다음 한 팩의 것이다(전부의 합이 아니다).
                "expected_size_mb": (nxt_state or {}).get("expected_size_mb", 0),
                "sha256": "",
                "virtual": True,
                "accent": bool(spec.get("accent")),
                "members": members,
                "pending": pending,
                "next_member": pending[0] if pending else "",
                "next_label": str((nxt or {}).get("label") or (pending[0] if pending else "")),
            })
            # 권하는 판은 **맨 위**로(사용자 지정). 나머지 가상 모드는 제자리.
            if spec.get("pin_top"):
                modes.insert(0, virtual_rows[-1])
            else:
                modes.append(virtual_rows[-1])
        return {
            "modes": modes,
            "filters": [
                {"key": "all", "name": "전체 목록", "count": len(self._base_list("all", weights)[0])},
                {"key": "favorites", "name": "관심 작가", "count": len(self._base_list("favorites", weights)[0])},
                {"key": "banned", "name": "제외 작가", "count": len([artist for artist in banned if artist in weights])},
                *self._custom_filters(weights, banned_set),
                # 생성한 모델 목록. 전체/관심/제외와 성격이 달라 구분선으로 가른다
                # (사용자 지정 2026-08-26).
                *self._generated_model_filters(weights, banned_set),
            ],
            "artist_count": len(weights),
            "favorites": favorites,
            "banned": banned,
            "options": self.load_options(),
            "download": self.download_snapshot(),
            "favorite_thumbnail_cache": favorite_thumbnail_cache,
        }

    def _list_artists(self, mode_key: str, filter_key: str, query_text: str, *, random_sample: bool):
        """목록 조건(모드 · 필터 · 이름 검색)에 드는 작가 - 격자 · 랜덤 한 명 뽑기가 **같은 길**을 쓴다."""
        thumb_data = self.load_data(mode_key) if mode_key else {}
        weights = self._artist_weights(mode_key)
        base_list, filter_name = self._base_list(
            filter_key,
            weights,
            exclude_banned=True,
            allow_banned_filter=not random_sample,
        )
        if thumb_data:
            thumb_keys = set(thumb_data.keys())
            base_list = [artist for artist in base_list if artist in thumb_keys]
        if query_text:
            base_list = [artist for artist in base_list if query_text in artist.lower().replace("_", " ")]
        base_list = sorted(base_list, key=lambda artist: weights.get(artist, 0), reverse=True)
        return base_list, filter_name, weights, thumb_data

    def pick_random_artist(self, mode: str = "", filter_key: str = "all", query: str = "",
                           per_page: int = 48, *, range_pct: Any = None, exclude: set[str] | None = None,
                           search: Any = None) -> dict | None:
        """지금 목록에서 한 명(제외 작가는 빠진다 · 최근에 뽑힌 몇 명은 피한다). 비면 None.
        `page` = 격자(같은 정렬 · `per_page`)에서 그 작가가 있는 쪽 - 화면이 그 쪽으로 넘겨 카드를 고른다(사용자 지시 2026-10-19)."""
        mode_key = str(mode or "").strip()
        filter_key = str(filter_key or "all").strip() or "all"
        query_text = str(query or "").strip().lower().replace("_", " ")
        # 아티스트 창 [검색] 이 켜져 있으면 그 결과(격자와 같은 순서라 `page` 도 그 격자의 쪽이다 · 사용자 지정 2026-11-04).
        artists, _name, weights, thumb_data, history_key = self._random_pool_list(mode_key, filter_key, query_text,
                                                                                  search)
        grid = artists                       # 쪽 번호를 세는 목록 = 화면 격자
        if history_key[0] == "search":
            filter_key = "all"
            # 검색 격자는 제외 작가도 보인다 - 뽑기는 뺀 목록에서, 쪽은 격자 순서로(Codex 릴리즈 리뷰 11-04).
            grid = self._search_pool_names(self._normalize_search_pool(search), mode_key, keep_banned=True) or artists
        # 메인 Random 만 - 구간(게시물 많은 순 100칸)과 이미 뽑힌 작가(중복 스킵). 다 빠지면 구간 안에서 중복 허용.
        candidates = artists
        if range_pct is not None and self._normalize_random_range(range_pct) != [0, 100]:
            ranked = self.random_range_order(artists, weights)       # 구간 = 게시물 많은 순(검색 결과도)
            start, end = self.random_range_bounds(len(ranked), range_pct)
            candidates = ranked[start:end]
        exhausted = False
        if exclude:
            fresh = [artist for artist in candidates if artist not in exclude]
            exhausted = bool(candidates) and not fresh
            candidates = fresh or candidates
        picked = self._random_sample(candidates, 1, history_key)
        if not picked:
            return None
        artist = picked[0]
        per_page = max(12, min(96, int(per_page or 48)))       # build_list 와 같은 범위
        index = grid.index(artist) if artist in grid else artists.index(artist)
        image_url = self._image_url_resolver(mode_key, filter_key, thumb_data)(artist)
        return {
            "artist": artist,
            "weight": self._format_count(weights.get(artist, 0)),
            "favorite": artist in set(self._favorites()),
            "banned": False,
            "has_image": bool(image_url),
            "image_url": image_url,
            "total": len(artists),
            "index": index,
            "page": index // per_page,
            "exhausted": exhausted,
        }

    def build_list(
        self,
        mode: str = "",
        filter_key: str = "all",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        random_sample: bool = False,
    ) -> dict:
        mode_key = str(mode or "").strip()
        query_text = str(query or "").strip().lower().replace("_", " ")
        base_list, filter_name, weights, thumb_data = self._list_artists(
            mode_key, filter_key, query_text, random_sample=random_sample)
        total = len(base_list)
        per_page = max(12, min(96, int(per_page or 48)))
        page = max(0, int(page or 0))
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page >= total_pages:
            page = max(0, total_pages - 1)
        if random_sample:
            artists = self._random_sample(
                base_list,
                min(per_page, total),
                (mode_key, str(filter_key or "all"), query_text, per_page),
            )
        else:
            artists = base_list[page * per_page:page * per_page + per_page]
        favorite_set = set(self._favorites())
        banned_set = set(self._banned())
        item_image_url = self._image_url_resolver(mode_key, filter_key, thumb_data)
        return {
            "mode": mode_key,
            "filter": str(filter_key or "all"),
            "filter_name": filter_name,
            "query": query,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "random": bool(random_sample),
            "excluded_count": len(banned_set),
            "items": [
                {
                    "artist": artist,
                    "weight": self._format_count(weights.get(artist, 0)),
                    "favorite": artist in favorite_set,
                    "banned": artist in banned_set,
                    "has_image": bool(item_image_url(artist)),
                    "image_url": item_image_url(artist),
                }
                for artist in artists
            ],
        }

    def describe_artists(self, mode: str = "", artists: Any = None, view: str = "") -> dict:
        """이름 목록 -> 격자 카드와 **같은 모양**의 항목들. 그룹 창이 쓴다.

        ⚠️ 그림 주소 규칙은 `_image_url_resolver` 하나다 - 격자와 그룹 창이 서로 다른
           그림을 보여 주면 "같은 작가인데 왜 다르냐" 가 된다.
        목록에 없는 이름(사전에 없는 작가)도 버리지 않는다 - 사용자가 넣은 것이다.
        """
        mode_key = str(mode or "").strip()
        names = []
        seen = set()
        for raw in (artists if isinstance(artists, list) else [])[:2000]:
            name = " ".join(str(raw or "").split())
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        thumb_data = self.load_data(mode_key) if mode_key else {}
        weights = self._artist_weights(mode_key)
        favorite_set = set(self._favorites())
        banned_set = set(self._banned())
        item_image_url = self._image_url_resolver(mode_key, "all", thumb_data)
        view_urls = self.view_images(view, names) if view else {}
        return {
            "mode": mode_key,
            "view": str(view or ""),
            "items": [
                {
                    "artist": artist,
                    "weight": self._format_count(weights.get(artist, 0)),
                    "known": artist in weights,
                    "favorite": artist in favorite_set,
                    "banned": artist in banned_set,
                    "has_image": bool(item_image_url(artist)),
                    "image_url": item_image_url(artist),
                    # 보기를 물었을 때만. 없으면 빈 값 - 화면이 '미생성' 막을 덮는다.
                    **({"view_image_url": view_urls.get(artist, "")} if view else {}),
                }
                for artist in names
            ],
        }

    def _copy_cache_names(self, path: Path, loader: Callable[[], dict]) -> frozenset:
        """사본 캐시(관심 · 그룹)에 그림이 든 **이름들**. 파일이 그대로면 다시 읽지 않는다.

        ⚠️ 관심 캐시는 그림을 통째로 담아 크다(사용자 포터블 18MB · 160명, 2026-09-30 실측) -
           읽기만 40ms 라, 그림 규칙을 세울 때마다 읽으면 격자 한 쪽 · 검색 한 번마다 그만큼 든다.
           쓰는 쪽은 늘 임시 파일로 갈아 끼운다(`replace`) - 그러면 **파일 번호**가 바뀐다.
           시각만 보면 윈도의 시각 눈금(수 ms) 안에 같은 크기로 두 번 쓴 것을 못 가른다.
        """
        try:
            stat = path.stat()
        except OSError:
            stat = None
        if stat is None:
            # 파일이 없으면 기억하지 않고 **읽개에게 그대로 묻는다**(없으면 빈 것을 즉시 낸다).
            # ⚠️ 여기서 빈 것을 지어내면 읽개를 갈아 끼운 쪽(시험)의 답을 가로챈다.
            try:
                return frozenset((loader().get("items") or {}).keys())
            except Exception:
                return frozenset()
        stamp = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        hit = self._copy_names_memo.get(str(path))
        if hit is not None and hit[0] == stamp:
            return hit[1]
        try:
            names = frozenset((loader().get("items") or {}).keys())
        except Exception:
            names = frozenset()     # 못 읽는 사본은 없는 것으로 본다(전부터 그랬다)
        self._copy_names_memo[str(path)] = (stamp, names)
        return names

    def _image_source_resolver(self, mode_key: str, filter_key: str, thumb_data: dict):
        """작가 이름 -> 썸네일 주소. 순서가 규약이다(아래 주석).

        ⚠️ 가상 모드에서는 `thumb_data` 의 값이 **주인 팩 키**다. 그림은 그 팩이 내야
           하므로 주소의 `mode=` 도 거기로 간다 - 가상 키를 그대로 실으면 이미지
           라우트가 "모르는 모드" 로 400 을 낸다.
        """
        virtual = self.is_virtual_mode(mode_key)
        # 사본은 **있느냐만** 본다(그림은 제 라우트가 따로 낸다) - 그래서 이름만 쥔다.
        favorite_thumb_items = self._copy_cache_names(self._favorite_thumbnail_cache_path(),
                                                      self._load_thumbnail_cache)
        group_thumb_items = self._copy_cache_names(self._group_thumbnail_cache_path(),
                                                   self._load_group_thumbnail_cache)

        # ⚠️ **지금 모드의 것만 본다.** 백엔드가 다르면 그림의 결이 전혀 다르다.
        api_key = self._generated_api_key()
        try:
            generated_models = self.generated_index().get(api_key, {})
        except Exception:
            generated_models = {}
        # 모델 필터로 보고 있으면 **그 모델의** 그림을 보여 준다. 아니면 가장 최근 것.
        filter_model = (str(filter_key or "")[len("model:"):]
                        if str(filter_key or "").startswith("model:") else "")
        generated_lookup: dict[str, str] = {}
        if filter_model:
            for artist_name in generated_models.get(self._generated_model_key(filter_model), {}):
                generated_lookup[artist_name] = filter_model
        else:
            newest: dict[str, tuple[str, str]] = {}
            for model_name, entries in generated_models.items():
                for artist_name, entry in entries.items():
                    stamp = entry.get("updated_at") or ""
                    if artist_name not in newest or stamp > newest[artist_name][0]:
                        newest[artist_name] = (stamp, model_name)
            generated_lookup = {a: m for a, (_stamp, m) in newest.items()}

        def source(artist: str) -> tuple:
            # ⚠️ 순서가 규약이다(사용자 결정 2026-08-26): 모드 팩 -> 즐겨찾기 캐시 ->
            #    사용자가 생성한 것. 사용자 썸네일은 **빈 칸을 메꾸는 용도**지 공식 팩
            #    그림을 밀어내지 않는다. 모드를 안 고르면 앞의 둘이 대부분 비어 있어
            #    실질적으로 사용자 썸네일이 먼저 보인다(즐겨찾기 123명 제외).
            if mode_key and artist in thumb_data:
                owner = str(thumb_data[artist]) if virtual else mode_key
                return ("pack", owner)
            if artist in favorite_thumb_items:
                return ("favorite",)
            # 그룹 사본은 관심 캐시와 같은 층이다 - 팩 그림의 복사본이라 사용자 썸네일보다 앞.
            if artist in group_thumb_items:
                return ("group",)
            if artist in generated_lookup:
                return ("generated", generated_lookup[artist], api_key)
            return ()

        return source

    def _image_url_resolver(self, mode_key: str, filter_key: str, thumb_data: dict):
        source = self._image_source_resolver(mode_key, filter_key, thumb_data)

        def item_image_url(artist: str) -> str:
            selected = source(artist)
            if not selected:
                return ""
            if selected[0] == "pack":
                return f"/api/artist-thumb/image?mode={quote(selected[1], safe='')}&artist={quote(artist, safe='')}"
            if selected[0] == "favorite":
                return f"/api/artist-thumb/favorite-image?artist={quote(artist, safe='')}"
            if selected[0] == "group":
                return f"/api/artist-thumb/group-image?artist={quote(artist, safe='')}"
            return self._generated_image_url(artist, selected[1], selected[2])

        return item_image_url

    def image_presence(self, mode: str = "") -> Callable[[str], bool]:
        """이름 -> **카드에 그림이 뜨는가**. 아티스트 검색의 [썸네일 있음] 이 쓴다.

        ⚠️ 규칙을 따로 세우지 않는다 - 격자 · describe 와 같은 `_image_source_resolver` 다.
           검색이 '있다' 고 한 작가가 격자에서 No Image 로 뜨면 그 토글은 거짓말이 된다.
        ⚠️ 모드 팩을 못 읽으면(안 받았다 · 모르는 키) 팩 그림만 빠진다 - 관심 · 그룹 ·
           생성 사본은 그대로 센다. 검색이 통째로 죽을 일은 아니다.
        """
        mode_key = str(mode or "").strip()
        try:
            thumb_data = self.load_data(mode_key) if mode_key else {}
        except Exception:
            thumb_data = {}
        source = self._image_source_resolver(mode_key, "all", thumb_data)
        return lambda artist: bool(source(artist))

    def capture_artist_images(self, mode: str, artists: list[str]) -> tuple[dict[str, bytes], list[str]]:
        """URL과 저장 그림은 같은 출처를 고른다. 가상 팩도 주인 팩으로 해석한다."""
        mode_key = str(mode or "").strip()
        source = self._image_source_resolver(mode_key, "all", self.load_data(mode_key) if mode_key else {})
        images, warnings = {}, []
        for artist in dict.fromkeys(artists):
            selected = source(artist)
            if not selected:
                continue
            try:
                if selected[0] == "pack":
                    payload = self.image_payload(selected[1], artist)
                elif selected[0] == "favorite":
                    payload = self.favorite_image_payload(artist)
                elif selected[0] == "group":
                    payload = self.group_image_payload(artist)
                else:
                    payload = self.generated_image_payload(artist, selected[1], selected[2])
                images[artist] = payload[0]
            except (OSError, ValueError) as exc:
                warnings.append(f"{artist}: 썸네일을 읽지 못했습니다 ({exc})")
        return images, warnings

    @staticmethod
    def media_type(image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    def _image_payload_from_encoded(self, encoded: Any) -> tuple[bytes, str]:
        encoded_text = str(encoded or "")
        if encoded_text.startswith("data:") and "," in encoded_text:
            encoded_text = encoded_text.split(",", 1)[1]
        raw = base64.b64decode(encoded_text)
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(raw))
            image.load()
            if image.width > 170:
                image = image.crop((85, 0, image.width - 85, image.height))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            output = io.BytesIO()
            # optimize 는 쓰지 않는다 - 허프만 표를 다시 짜느라 인코딩이 3.1ms -> 1.2ms 로 2.5배 느린데 파일은 2% 줄 뿐이다
            # (2026-10-03 실측, 768px 팩 그림 60장: 6개 동시 230ms -> 115ms). 격자 한 쪽이 처음 뜨는 시간이 여기서 나온다.
            image.save(output, format="JPEG", quality=86)
            return output.getvalue(), "image/jpeg"
        except Exception:
            return raw, self.media_type(raw)

    def image_payload(self, mode: str, artist: str) -> tuple[bytes, str]:
        mode_key = str(mode or "").strip()
        artist_name = str(artist or "").strip()
        if not mode_key:
            raise ValueError("mode is required")
        if not artist_name:
            raise ValueError("artist is required")
        cache_key = (mode_key, artist_name)
        with self._lock:
            cached = self._image_cache.get(cache_key)
            if cached:
                return cached
        data = self.load_data(mode_key)
        encoded_list = data.get(artist_name)
        if not encoded_list or not encoded_list[0]:
            raise FileNotFoundError(f"Artist thumbnail not found: {artist_name}")
        image_bytes, media_type = self._image_payload_from_encoded(encoded_list[0])
        with self._lock:
            if len(self._image_cache) > 512:
                self._image_cache.pop(next(iter(self._image_cache)), None)
            self._image_cache[cache_key] = (image_bytes, media_type)
        return image_bytes, media_type

    # ── 지금 쓰는 작가만 (아티스트 태그 관리 창 · 사용자 지시 2026-11-11) ────────────────────────
    #  팩을 메모리에 올리지 않는다. 팩마다 작가의 바이트 자리를 한 번 훑어 적어 두고(`artist_thumb/pack_index/`),
    #  그 뒤로는 필요한 작가의 자리만 읽는다. 1.37GB 팩 실측: 통째 3.7초 · 3.9GB -> 13명 10~20ms · 21MB.

    @staticmethod
    def _pack_family(mode: str) -> str:
        return str(mode or "").strip().split("-")[0]

    def _used_mode_key(self, mode: str = "") -> str:
        mode_key = str(mode or "").strip()
        if not mode_key:
            api = str(self._mode_getter() or "NAI").upper()
            mode_key = {"COMFYUI": "ANIMA", "WEBUI": "NoobNAI"}.get(api, "NAID5-CURATED")
        return mode_key

    def _used_pack_roster(self, mode: str = "") -> list[str]:
        """이 계열의 팩 전부를 찾는 차례대로 - 고른 모드의 팩이 먼저, 그다음 같은 계열(NAID5 · ANIMA ...)의 나머지.
        받았든 안 받았든. 찾을 때는 받은 것만(`_used_pack_order`), 아티스트 태그 관리 창은 안 받은 것을 권한다."""
        mode_key = self._used_mode_key(mode)
        if self.is_virtual_mode(mode_key):
            first = self.virtual_members(mode_key, existing_only=False)
        else:
            first = [mode_key] if mode_key in self.ARTIST_THUMB_MODES else []
        family = self._pack_family(mode_key)
        rest = [key for key in self.ARTIST_THUMB_MODES if self._pack_family(key) == family and key not in first]
        return first + rest

    def _used_pack_order(self, mode: str = "") -> list[str]:
        """찾아볼 팩의 차례(`_used_pack_roster`) 중 받은 것만."""
        return [key for key in self._used_pack_roster(mode) if self._file_state(self.ARTIST_THUMB_MODES[key])["exists"]]

    def used_pack_offers(self, mode: str = "") -> dict:
        """아티스트 태그 관리 창의 [받기] 띠(사용자 지시 2026-11-13) - 이 계열의 팩과 받았는지.

        어느 작가가 어느 팩에 드는지는 짐작하지 않는다 - 이름의 숫자가 게시물 수 구간인 것은 NAID5 일부뿐이다
        (Curated · STYLISH · ANIMA 는 다르다). 받기는 실제 팩 키로 `start_download` 를 부른다(한 번에 하나).
        """
        mode_key = self._used_mode_key(mode)
        packs = []
        for key in self._used_pack_roster(mode_key):
            info = self.ARTIST_THUMB_MODES[key]
            state = self._file_state(info)
            packs.append({
                "key": key,
                "label": str(info.get("label") or key),
                "exists": bool(state["exists"]),
                "needs_update": bool(state["needs_update"]),
                "expected_size_mb": state["expected_size_mb"],
            })
        return {"family": self._pack_family(mode_key), "packs": packs}

    def _pack_index(self, key: str):
        """팩의 자리 색인. 팩이 없거나 못 읽으면 None. 팩이 갈렸으면(크기 · 시각) 다시 훑는다."""
        from core.artist_pack_index import ArtistPackIndex

        if key not in self.ARTIST_THUMB_MODES:
            return None
        with self._pack_index_lock:
            index = self._pack_indexes.get(key)
            # 지금 고르는 파일의 색인이어야 한다 - 옛 자리(legacy)의 팩으로 색인한 뒤 새 자리에 팩이 생기면 `_mode_path` 는
            # 새 파일을 고르는데, 옛 파일이 그대로라는 것만 보면 옛 그림을 계속 낸다(Codex 리뷰 2026-11-12 #5).
            path = self._mode_path(key)
            if index is not None and index.path == path and index.is_current():
                return index
            try:
                index = ArtistPackIndex(path, self.state_root / "pack_index" / f"{path.name}.idx.json")
            except Exception as exc:
                _safe_log(f"🌐 Headless Artist Thumb: pack index failed ({key}) — {exc}",
                          f"[WARN] Headless Artist Thumb: pack index failed ({key}) - {exc}")
                return None
            if index.signature is None:
                return None
            self._pack_indexes[key] = index
            return index

    def used_artist_tiles(self, names: list[str], mode: str = "") -> list[dict]:
        """작가 이름들 -> 타일(이름 · 게시물 수 · 그림 주소). 그림이 없으면 `image_url` 이 빈 글이다.

        팩은 차례대로 보고, 전부 찾으면 남은 팩은 훑지 않는다(첫 색인은 팩마다 몇 초가 든다).
        """
        from urllib.parse import quote

        wanted: list[str] = []
        for name in names:
            clean = " ".join(str(name or "").split())
            if clean and clean.casefold() not in {w.casefold() for w in wanted}:
                wanted.append(clean)
        found: dict[str, tuple[str, str]] = {}
        for key in self._used_pack_order(mode):
            missing = [name for name in wanted if name not in found]
            if not missing:
                break
            index = self._pack_index(key)
            if index is None:
                continue
            for name in missing:
                actual = index.find(name)
                if actual is not None:
                    found[name] = (key, actual)
        weights = self._dictionary_weights()
        rows = []
        for name in wanted:
            key, actual = found.get(name, ("", ""))
            rows.append({
                "name": actual or name,
                "count": int(weights.get(actual or name) or weights.get(name.lower()) or 0),
                "pack": key,
                "pack_label": str(self.ARTIST_THUMB_MODES[key].get("label") or key) if key else "",
                "image_url": (f"/api/artist-thumb/used-image?mode={quote(key, safe='')}"
                              f"&artist={quote(actual, safe='')}") if key else "",
            })
        return rows

    def used_image_payload(self, mode: str, artist: str) -> tuple[bytes, str]:
        """`image_payload` 와 같은 그림을 팩을 올리지 않고 낸다(같은 캐시를 쓴다)."""
        mode_key = str(mode or "").strip()
        artist_name = str(artist or "").strip()
        if not mode_key or not artist_name:
            raise ValueError("mode and artist are required")
        cache_key = (mode_key, artist_name)
        with self._lock:
            cached = self._image_cache.get(cache_key)
            if cached:
                return cached
        index = self._pack_index(mode_key)
        actual = index.find(artist_name) if index is not None else None
        if actual is None:
            raise FileNotFoundError(f"Artist thumbnail not found: {artist_name}")
        payload = self._image_payload_from_encoded(index.read(actual))
        with self._lock:
            if len(self._image_cache) > 512:
                self._image_cache.pop(next(iter(self._image_cache)), None)
            self._image_cache[cache_key] = payload
        return payload

    GENERATED_THUMB_MAX_SIZE = (896, 1152)
    GENERATED_UNKNOWN_MODEL = "unknown"

    # 인덱스 = {"version": 3, "items": {api_mode: {model: {artist: {filename, updated_at}}}}}
    #
    # ⚠️ **api_mode 가 맨 위 층이다**(사용자 지정 2026-08-26). 앱은 이미 모드별 파라미터
    #    plane(`remote_param_planes`)을 갖고 있고, 백엔드가 다르면 같은 아티스트라도
    #    그림의 결이 전혀 다르다. 게다가 WEBUI/COMFYUI 의 `model` 은 체크포인트 파일
    #    이름이라 NAI 의 모델 키와 성격이 다르고, ComfyUI LOCKED 워크플로우나 모델을
    #    못 읽은 경우 모두 `unknown` 으로 떨어져 **백엔드끼리 섞인다** - 그 충돌을 막는다.
    # ⚠️ 그 아래가 모델(폴더)이다. 같은 모델이라도 아티스트마다 한 장씩.
    def generated_index(self) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
        """읽기 실패는 빈 dict 로 삼킨다(썸네일 하나 때문에 탭이 죽으면 안 된다)."""
        try:
            data = json.loads(self._generated_index_path().read_text(encoding="utf-8"))
        except Exception:
            return {}
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, dict) or int(data.get("version") or 0) < 3:
            # v1(평면) · v2(모델만)는 버린다 - 배포 전 형식이라 쓰는 사람이 없다.
            return {}
        out: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
        for api_mode, models in items.items():
            if not isinstance(models, dict):
                continue
            mode_bucket: dict[str, dict[str, dict[str, str]]] = {}
            for model, entries in models.items():
                if not isinstance(entries, dict):
                    continue
                bucket = {}
                for artist, entry in entries.items():
                    if isinstance(entry, dict) and entry.get("filename"):
                        bucket[str(artist)] = {
                            "filename": str(entry.get("filename")),
                            "updated_at": str(entry.get("updated_at") or ""),
                        }
                if bucket:
                    mode_bucket[str(model)] = bucket
            if mode_bucket:
                out[str(api_mode)] = mode_bucket
        return out

    def _write_generated_index(self, index: dict) -> None:
        target = self._generated_index_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_name(target.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"version": 3, "items": index}, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(target)

    @staticmethod
    def _safe_component(value: str, fallback: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*]', "_", str(value or "").strip()).strip(". ")
        return safe or fallback

    def _current_api_mode(self) -> str:
        try:
            return str(self._mode_getter() or "").strip().upper() or "NAI"
        except Exception:
            return "NAI"

    def _generated_api_key(self, api_mode: str = "") -> str:
        return self._safe_component(api_mode or self._current_api_mode(), "NAI").upper()

    def _generated_model_key(self, model: str) -> str:
        return self._safe_component(model, self.GENERATED_UNKNOWN_MODEL)

    def save_generated_thumbnail(self, pil_image: Any, artist: str, model: str = "",
                                 api_mode: str = "") -> dict[str, Any] | None:
        """생성 결과를 (api_mode, 모델, 아티스트) 칸에 남긴다. **매번 덮어쓴다**(사용자 결정).

        ⚠️ 최종 경로에 바로 쓰면 덮어쓰는 동안 들어온 GET 이 **잘린 파일**을 받는다.
           임시 파일 -> replace 로 맞춘다(캐릭터 뷰어와 같은 방식).
        """
        artist_name = str(artist or "").strip()
        if not artist_name or pil_image is None:
            return None
        from PIL import Image

        api_key = self._generated_api_key(api_mode)
        model_key = self._generated_model_key(model)
        target_dir = self._generated_dir() / api_key / model_key
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = self._safe_component(artist_name, "artist") + ".webp"
        target = target_dir / filename

        thumb = pil_image.copy()
        if thumb.mode not in ("RGB", "RGBA"):
            thumb = thumb.convert("RGB")
        thumb.thumbnail(self.GENERATED_THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
        tmp_path = target.with_name(target.name + ".tmp")
        thumb.save(tmp_path, "WEBP", quality=82)
        tmp_path.replace(target)

        with self._lock:
            index = self.generated_index()
            index.setdefault(api_key, {}).setdefault(model_key, {})[artist_name] = {
                "filename": filename,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._write_generated_index(index)
            # 덮어썼으니 이전 바이트를 물고 있는 캐시를 버린다.
            for key in list(self._image_cache):
                if key[:1] == ("__generated__",) and key[-1] == artist_name:
                    self._image_cache.pop(key, None)
        return {
            "artist": artist_name,
            "api_mode": api_key,
            "model": model_key,
            "filename": filename,
            "url": self._generated_image_url(artist_name, model_key, api_key),
            "count": sum(len(m) for models in index.values() for m in models.values()),
        }

    @staticmethod
    def _generated_image_url(artist: str, model: str = "", api_mode: str = "") -> str:
        url = f"/api/artist-thumb/generated-image?artist={quote(str(artist), safe='')}"
        if model:
            url += f"&model={quote(str(model), safe='')}"
        if api_mode:
            url += f"&api={quote(str(api_mode), safe='')}"
        return url

    def _generated_entry(self, artist: str, model: str = "",
                         api_mode: str = "") -> tuple[str, str, str] | None:
        """(api_key, model_key, filename). 모델을 안 주면 그 모드 안에서 **가장 최근** 것."""
        api_key = self._generated_api_key(api_mode)
        models = self.generated_index().get(api_key, {})
        if model:
            model_key = self._generated_model_key(model)
            entry = models.get(model_key, {}).get(artist)
            return (api_key, model_key, entry["filename"]) if entry else None
        best: tuple[str, str, str] | None = None   # (updated_at, model, filename)
        for model_key, entries in models.items():
            entry = entries.get(artist)
            if not entry:
                continue
            stamp = entry.get("updated_at") or ""
            if best is None or stamp > best[0]:
                best = (stamp, model_key, entry["filename"])
        return (api_key, best[1], best[2]) if best else None

    def generated_models(self, api_mode: str = "") -> list[dict[str, Any]]:
        """지금 모드에서 생성 썸네일이 있는 모델 목록. FILTER 하단에 나열된다."""
        models = self.generated_index().get(self._generated_api_key(api_mode), {})
        return [
            {"key": f"model:{model}", "name": model, "count": len(entries)}
            for model, entries in sorted(models.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            if entries
        ]

    def generated_artists_for_model(self, model: str, api_mode: str = "") -> list[str]:
        models = self.generated_index().get(self._generated_api_key(api_mode), {})
        return sorted(models.get(self._generated_model_key(model), {}).keys())

    def generated_image_payload(self, artist: str, model: str = "",
                                api_mode: str = "") -> tuple[bytes, str]:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        cache_key = ("__generated__", self._generated_api_key(api_mode), str(model or ""), artist_name)
        with self._lock:
            cached = self._image_cache.get(cache_key)
            if cached:
                return cached
            found = self._generated_entry(artist_name, str(model or ""), api_mode)
        if not found:
            raise FileNotFoundError(f"Generated artist thumbnail not found: {artist_name}")
        api_key, model_key, filename = found
        path = self._generated_dir() / api_key / model_key / filename
        try:
            payload = (path.read_bytes(), "image/webp")
        except OSError as exc:
            raise FileNotFoundError(f"Generated artist thumbnail unreadable: {artist_name}") from exc
        with self._lock:
            if len(self._image_cache) > 512:
                self._image_cache.pop(next(iter(self._image_cache)), None)
            self._image_cache[cache_key] = payload
        return payload

    def favorite_image_payload(self, artist: str) -> tuple[bytes, str]:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        cache_key = ("__favorite_cache__", artist_name)
        with self._lock:
            cached = self._image_cache.get(cache_key)
            if cached:
                return cached
            entry = (self._load_thumbnail_cache().get("items") or {}).get(artist_name) or {}
            encoded = entry.get("thumbnail")
        if not encoded:
            raise FileNotFoundError(f"Favorite artist thumbnail not found: {artist_name}")
        image_bytes, media_type = self._image_payload_from_encoded(encoded)
        with self._lock:
            if len(self._image_cache) > 512:
                self._image_cache.pop(next(iter(self._image_cache)), None)
            self._image_cache[cache_key] = (image_bytes, media_type)
        return image_bytes, media_type

    def set_favorite(self, artist: str, favorite: bool, mode: str = "") -> dict:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        with self._lock:
            state = self._state()
            favorites = list(state.get("favorites", []))
            if favorite and artist_name not in favorites:
                favorites.append(artist_name)
            elif not favorite and artist_name in favorites:
                favorites = [item for item in favorites if item != artist_name]
            state["favorites"] = favorites
            self._write_state(state)
            if favorite:
                self._cache_favorite_from_loaded_mode(artist_name, mode)
            else:
                self._remove_favorite_thumbnail_cache(artist_name)
        return self.state()

    def set_banned(self, artist: str, banned: bool, *, return_state: bool = True) -> dict:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        with self._lock:
            state = self._state()
            banned_list = list(state.get("banned", []))
            if banned and artist_name not in banned_list:
                banned_list.append(artist_name)
            elif not banned and artist_name in banned_list:
                banned_list = [item for item in banned_list if item != artist_name]
            state["banned"] = banned_list
            if banned:
                state["favorites"] = [item for item in state.get("favorites", []) if item != artist_name]
            self._write_state(state)
        if banned:
            self.release_link_pin(artist_name)   # 숨긴 작가를 고정해 두었으면 정책을 돌려준다
        return self.state() if return_state else {"artist": artist_name, "banned": bool(banned)}

    @staticmethod
    def final_prompt(payload: dict) -> str:
        prompt_parts = []
        for key in ("prefix", "positive", "postfix"):
            value = str(payload.get(key) or "").strip()
            if value:
                prompt_parts.append(value)
        return ", ".join(prompt_parts).strip()

    def random_prompt_override(
        self,
        artist_prompt: str,
        module_settings: dict | None = None,
        anchor_groups: dict | None = None,
    ) -> dict:
        """이번 생성 한 번에만 씌울 PE 설정.

        `artist_prompt` 는 **첫 앵커보다 앞에 있는 블럭들**이다 - 예전처럼 prefix 앞에
        붙는다. 앵커 그룹은 글에 박힌 `<anchor:ID>` 자리에서 펼쳐지므로 여기서는 그대로
        실어 보내기만 한다(펼치는 것은 PE 훅 = `core.artist_anchor`).

        ⚠️ 둘 중 **하나만** 있으면 된다. 모든 블럭이 앵커에 들어가면 앞에 붙일 것이
           없다 - 예전 계약(`artist_prompt` 필수)이 그 경우를 막고 있었다.
        """
        from core.artist_anchor import normalize_groups

        artist_value = str(artist_prompt or "").strip().rstrip(",").strip()
        groups = normalize_groups(anchor_groups)
        if not artist_value and not groups:
            raise ValueError("artist_prompt or anchor_groups is required")
        settings = module_settings if isinstance(module_settings, dict) else {}
        pre_prompt = str(settings.get("pre_prompt") or "").strip()
        if artist_value:
            merged_pre = f"{artist_value}, {pre_prompt}" if pre_prompt else artist_value
        else:
            merged_pre = pre_prompt
        return {
            "pre_prompt": merged_pre,
            "post_prompt": str(settings.get("post_prompt") or ""),
            "auto_hide": str(settings.get("auto_hide_prompt") or settings.get("auto_hide") or ""),
            "preprocessing_options": dict(settings.get("preprocessing_options") or {}),
            "anchor_groups": groups,
        }

    def _resolution_allowed(self, width: int, height: int) -> bool:
        if width <= 0 or height <= 0:
            return False
        if width % 64 != 0 or height % 64 != 0:
            return False
        return width * height <= MAX_1MP_PIXELS

    def coerce_resolution(self, width: Any, height: Any) -> tuple[int, int]:
        pair = nearest_standard_1mp_resolution(width, height)
        if self._resolution_allowed(*pair):
            return pair
        return (832, 1216)

    def generation_overrides(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        final_positive = self.final_prompt(payload)
        if not final_positive:
            raise ValueError("prompt is empty")
        negative = str(payload.get("negative_prompt") or "")
        try:
            width = int(payload.get("width") or 832)
            height = int(payload.get("height") or 1216)
        except Exception:
            width, height = 832, 1216
        use_active_resolution = str(payload.get("artist_thumb_use_active_resolution", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        } or payload.get("artist_thumb_use_active_resolution") is True
        if not use_active_resolution:
            width, height = self.coerce_resolution(width, height)
        request_id = str(payload.get("request_id") or uuid.uuid4().hex)
        artist_name = str(payload.get("artist") or "").strip()
        overrides = {
            "input": final_positive,
            "_raw_input": final_positive,
            "negative_prompt": negative,
            "width": width,
            "height": height,
            "resolution": f"{width} x {height}",
            "artist_thumb_request": True,
            "artist_thumb_request_id": request_id,
            "artist_thumb_artist": artist_name,
            "_remote_queue_source": "Artist Thumb",
            "_remote_queue_label": artist_name,
        }
        if use_active_resolution:
            for key in (
                "api_mode",
                "resolution",
                "random_resolution",
                "auto_fit_resolution",
                "resolution_preset_enabled",
                "resolution_preset",
                "enable_hr",
                "hr_scale",
                "hr_upscaler",
                "denoising_strength",
                "hires_steps",
                "hr_cfg",
                "hires_preset_swap",
                "webui_hiresfix_assist",
                "webui_hiresfix_assist_target",
            ):
                if key in payload:
                    overrides[key] = payload.get(key)
            overrides["width"] = width
            overrides["height"] = height
            overrides.setdefault("resolution", f"{width} x {height}")
            overrides["artist_thumb_use_active_resolution"] = True
        else:
            overrides["random_resolution"] = False
        return overrides

    def validate_download_file(self, mode: str, path: Path) -> int:
        file_size = Path(path).stat().st_size
        if file_size < (1024 * 1024):
            raise ValueError(f"다운로드된 파일이 너무 작습니다 ({file_size / 1024:.1f} KB)")
        mode_info = self._mode_info(mode)
        expected_size = int(mode_info.get("expected_size") or 0)
        if expected_size and file_size != expected_size:
            raise ValueError(f"다운로드된 파일 크기가 예상과 다릅니다 ({file_size} / {expected_size} bytes)")
        expected_sha256 = str(mode_info.get("sha256") or "").upper()
        if expected_sha256:
            self._set_download_state(message="다운로드 파일을 검증하는 중...")
            actual_sha256 = self._file_sha256(path)
            if actual_sha256 != expected_sha256:
                raise ValueError(f"다운로드된 파일 해시가 예상과 다릅니다 ({actual_sha256})")
        return file_size

    def download_snapshot(self) -> dict:
        with self._lock:
            return dict(self._download_state)

    def _set_download_state(self, **updates) -> dict:
        with self._lock:
            self._download_state.update(updates)
            self._download_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._download_state)

    def start_download(self, mode: str) -> dict:
        key = str(mode or "").strip()
        # 가상 모드는 제 파일이 없다 - **다음에 채울 한 팩**으로 넘긴다(사용자 지정
        # 2026-09-19: "천천히 채워나가도록"). 한 번에 다 받지 않는 것이 요점이라
        # 여기서 목록을 돌리지 않고 맨 앞 하나만 집는다.
        if self.is_virtual_mode(key):
            pending = self.virtual_pending(key)
            if not pending:
                return self._set_download_state(
                    active=False, mode=key, percent=100,
                    message="이미 다 받았습니다.", error="", done=True,
                )
            key = pending[0]
        info = self._mode_info(key)
        path = self._mode_download_path(info)
        url = str(info.get("url") or "")
        if not url:
            raise ValueError(f"download url is not configured: {key}")
        file_state = self._file_state(info)
        if file_state["available"]:
            return self._set_download_state(
                active=False,
                mode=key,
                percent=100,
                downloaded_mb=file_state["size_mb"],
                total_mb=file_state["size_mb"],
                message="이미 다운로드되어 있습니다.",
                error="",
                done=True,
            )
        with self._lock:
            if self._download_state.get("active"):
                return dict(self._download_state)
            self._download_cancel.clear()
            self._download_state.update({
                "active": True,
                "mode": key,
                "percent": 0,
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "message": "다운로드 준비 중...",
                "error": "",
                "done": False,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            worker = threading.Thread(
                target=self._run_download,
                args=(key, path, url),
                daemon=True,
                name=f"artist-thumb-download-{key}",
            )
            self._download_thread = worker
            worker.start()
            return dict(self._download_state)

    def cancel_download(self) -> dict:
        state = self.download_snapshot()
        if state.get("active"):
            self._download_cancel.set()
            return self._set_download_state(message="다운로드 취소 중...")
        return state

    def _run_download(self, mode: str, target_path: Path, url: str) -> None:
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(url, headers={"User-Agent": "NAIA/2.0.71 ArtistThumb Headless"})
            self._set_download_state(message="다운로드 연결 중...")
            with urllib.request.urlopen(request, timeout=30) as response:
                total_size = int(response.headers.get("content-length", 0) or 0)
                total_mb = round(total_size / (1024 * 1024), 1) if total_size else 0.0
                downloaded = 0
                last_update = 0.0
                with temp_path.open("wb") as output:
                    while True:
                        if self._download_cancel.is_set():
                            raise InterruptedError("다운로드가 취소되었습니다.")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_update >= 0.25:
                            percent = min(100, int((downloaded * 100) / total_size)) if total_size else 0
                            downloaded_mb = round(downloaded / (1024 * 1024), 1)
                            self._set_download_state(
                                percent=percent,
                                downloaded_mb=downloaded_mb,
                                total_mb=total_mb,
                                message=(
                                    f"다운로드 중... {percent}% ({downloaded_mb}/{total_mb} MB)"
                                    if total_size else f"다운로드 중... {downloaded_mb} MB"
                                ),
                            )
                            last_update = now
            file_size = self.validate_download_file(mode, temp_path)
            temp_path.replace(target_path)
            with self._lock:
                self._data_cache.clear()
                self._image_cache.clear()
            size_mb = round(file_size / (1024 * 1024), 1)
            self._set_download_state(
                active=False,
                mode=mode,
                percent=100,
                downloaded_mb=size_mb,
                total_mb=size_mb,
                message=f"다운로드 완료 ({size_mb} MB)",
                error="",
                done=True,
            )
        except InterruptedError as exc:
            temp_path.unlink(missing_ok=True)
            self._set_download_state(active=False, mode=mode, message=str(exc), error=str(exc), done=False)
        except urllib.error.HTTPError as exc:
            temp_path.unlink(missing_ok=True)
            message = f"HTTP 오류 {exc.code}: {exc.reason}"
            self._set_download_state(active=False, mode=mode, message=message, error=message, done=False)
        except urllib.error.URLError as exc:
            temp_path.unlink(missing_ok=True)
            message = f"네트워크 오류: {exc.reason}"
            self._set_download_state(active=False, mode=mode, message=message, error=message, done=False)
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            message = f"다운로드 실패: {exc}"
            self._set_download_state(active=False, mode=mode, message=message, error=message, done=False)
