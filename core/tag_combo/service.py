# -*- coding: utf-8 -*-
"""조합 추천 서비스 - 모델 LRU 와 질의 파사드.

## 메모리

인원 그룹 13개를 전부 상주시키면 실측 1.5GB 다(역인덱스 포함). 사용자가 인원
설정을 바꿀 때만 모델이 바뀌므로 **바이트 예산 LRU** 로 두세 개만 들고 있는다.

⚠️ 엔트리 수가 아니라 **바이트**로 센다. 개수로 세면 161MB 짜리 두 개가 겹쳐
올라간다. 그리고 새 모델의 역인덱스를 만들기 **전에** 옛 모델을 버린다.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

from .bundle import ComboBundle
from .download import BUNDLE_NAME, BundleDownloader
from .model import ComboModel
from .person import PERSON_GROUPS, person_group_of
from .query import ComboQuery, Policy

DEFAULT_BUDGET = 400 * 1024 * 1024      # 상주 모델 합계 상한

# 인원 태그는 그룹을 정의하므로 그룹 안에서 확률이 1.0 이다 - 조건부 정보가 없다.
# 질의에서 빼야 나머지 태그로 좁혀진다.
_PERSON_TAGS = frozenset({"1girl", "1boy", "solo", "2girls", "2boys",
                          "multiple girls", "multiple boys"})


def resolve_dirs(repo_root: Path,
                 runtime_data_dir: Path | str | None = None) -> tuple[Path, list[Path]]:
    """(내려받을 곳, 찾을 곳들).

    저장소 관례는 **`runtime_paths.data_dir` -> `repo_root/data`** 순이다
    (`core/event_corpus_index.py:9`, quick_search / event_preset 과 같다).

    이걸 안 지키면 두 곳 다 틀린다:
      - 소스 실행: 179MB 를 **git 저장소 안에** 받는다
      - 포터블: `resources/naia-backend/data/` 에 받는데 업데이트가 그 폴더를
        갈아엎으면 사라진다(v2.0.29 설치 파손 전례)

    쓰기는 언제나 런타임 data_dir 이다. 읽기는 저장소 쪽도 본다 - 개발 중에
    방금 구운 모델을 쓰려면 그게 필요하다.

    ⚠️ `runtime_data_dir` 은 **호출부가 `context.runtime_paths` 에서 넘겨라.**
    여기서 다시 계산하면 부트스트랩과 갈릴 수 있다 - 부트스트랩은
    `portable=explicit_repo_root` 로 부르는데(`core/headless_context_bootstrap.py:38`)
    재계산은 `NAIA_PORTABLE` 환경변수만 본다. 지금은 Electron 셸이
    `NAIA_USER_DATA_DIR` 을 넘겨서 우연히 같지만, 백엔드를 직접 띄우면 갈린다.
    """
    repo = Path(repo_root) / "data" / "tag_combo"
    try:
        if runtime_data_dir is not None:
            rt = Path(runtime_data_dir) / "tag_combo"
        else:
            from core.runtime_paths import resolve_runtime_paths
            rt = Path(resolve_runtime_paths(Path(repo_root)).data_dir) / "tag_combo"
    except Exception:      # noqa: BLE001 - 경로 해석 실패로 기능이 죽지는 않는다
        return repo, [repo]
    # 저장소 쪽을 먼저 찾는다: 개발자가 방금 구운 것이 내려받은 것보다 우선이다.
    return rt, [repo, rt]


class ComboService:
    def __init__(self, data_dir: Path, *, budget: int = DEFAULT_BUDGET,
                 policy: Policy | None = None,
                 search_dirs: list[Path] | None = None):
        self.dir = Path(data_dir)
        self.search_dirs = [Path(p) for p in (search_dirs or [data_dir])]
        self.budget = int(budget)
        self.policy = policy or Policy()
        self._lru: "OrderedDict[str, tuple[ComboModel, ComboQuery]]" = OrderedDict()
        self._lock = threading.Lock()
        self._bundle: ComboBundle | None = None
        self._bundle_bad = ""
        self._bad_sig: tuple = ()      # 실패를 기록한 시점의 파일 지문
        self._bad_groups: set[str] = set()   # 본문이 깨져 못 쓰는 그룹
        self.downloader = BundleDownloader(self.dir)
        # 오프라인 레시피 뱅크. 없으면 None 이고, 그러면 옛 온라인 경로로 떨어진다.
        self._bank_loaded = False
        self._bank = None
        self._bank_error = ""       # 조용한 성능 저하를 드러내는 자리

    # ---- 다운로드 ----------------------------------------------------
    def _have_models(self) -> bool:
        """받을 필요가 **없는지**. 기준은 '파일이 있다'가 아니라 '13그룹을 다 쓸 수 있다'.

        처음엔 파일 존재만 봤다가 Codex 게이트에서 두 구멍이 드러났다:

        1. **깨진 번들도 존재는 한다.** 그러면 영원히 `ready` 인데 그룹은 0개고,
           다시 받을 길이 없다(프론트는 `bundleError` 를 안 읽는다).
        2. **느슨한 `.ncsr` 하나로 전체를 갈음했다.** `1girl_solo` 만 있는 사람은
           인원 수를 바꾸는 순간 빈 화면을 보는데 다운로드는 시작되지 않는다.

        그래서 `available()` 로 실제 열리는 그룹을 세고, 13개를 다 덮을 때만 참이다.
        `available()` 은 번들 인덱스만 읽으므로 179MB 를 적재하지 않는다.
        """
        return set(self.available()) >= set(PERSON_GROUPS)

    def ensure_bundle(self, *, retry: bool = False) -> dict:
        """Interactive 를 열 때 부른다. 이미 있으면 아무것도 안 한다."""
        if self._have_models():
            st = self.downloader.status()
            st["state"] = "ready"
            return st
        return self.downloader.retry() if retry else self.downloader.start()

    def download_status(self) -> dict:
        st = self.downloader.status()
        groups = self.available()          # bundle() 을 거치므로 _bundle_bad 가 갱신된다
        if st.get("state") in ("idle", "ready") and set(groups) >= set(PERSON_GROUPS):
            st["state"] = "ready"
        elif st.get("state") == "ready":
            # 파일은 있는데 13그룹을 못 채운다 - 깨졌거나 일부만 있다.
            # 여기서 ready 라고 하면 프론트가 안내를 지우고 사용자는 빈 화면만 본다.
            st["state"] = "incomplete"
        st["loose"] = [g for g in PERSON_GROUPS if self._loose(g) is not None]
        st["groups"] = groups
        st["missing"] = [g for g in PERSON_GROUPS if g not in set(groups)]
        b = self._bundle
        st["activeBundle"] = str(b.path) if b is not None else ""
        if self._bundle_bad:
            st["bundleError"] = self._bundle_bad
        return st

    # ---- 모델 --------------------------------------------------------
    def bundle(self) -> ComboBundle | None:
        """배포판이 내려받은 단일 파일. 없거나 깨졌으면 None.

        느슨한 `.ncsr` 이 있으면 그쪽이 우선이다 - 개발 중에 방금 구운 모델을
        두고 옛 번들을 읽으면 뭘 고쳤는지 알 수 없다.
        """
        if self._bundle is not None:
            return self._bundle
        sig = self._bundle_sig()
        if self._bundle_bad and sig == self._bad_sig:
            return None            # 같은 파일로 또 실패할 필요는 없다
        # **깨진 번들 하나가 성한 번들을 가리면 안 된다.** 첫 후보만 열고 포기하면
        # 저장소의 손상된 번들 때문에 런타임에 정상적으로 받아둔 번들을 영영 못
        # 쓴다(Codex 게이트 실증: groups=[] 인데 상태는 ready).
        errs = []
        for d in self.search_dirs:
            p = d / BUNDLE_NAME
            if not p.exists():
                continue
            try:
                self._bundle = ComboBundle(p)
                return self._bundle
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errs.append(f"{p.name}@{d.name}: {type(exc).__name__}: {exc}")
        self._bundle_bad = "; ".join(errs)[:400]
        self._bad_sig = sig
        return None

    def _on_bundle_corrupt(self, b: ComboBundle, group: str, exc: Exception) -> None:
        """그룹 본문이 깨졌다 - 다시 받을 수 있는 상태로 되돌린다.

        인덱스만으로는 이걸 못 잡는다. `available()` 은 인덱스를 읽으므로 본문이
        깨져도 13그룹을 그대로 보고하고, 그러면 상태는 영원히 `ready` 인데 그
        그룹만 조용히 죽어 있다 - **자동 복구 경로가 없다.**

        그래서 **내려받은 파일에 한해** `.bad-<그룹>` 으로 치우고 실패를 지운다.
        다음 `ensure_bundle()` 이 없는 파일을 보고 다시 받는다. sha256 검증이
        있으니 원격이 나쁘면 무한 재시도로 가지 않는다.

        저장소/개발자가 만든 번들은 **건드리지 않는다.** 남의 빌드 산출물 이름을
        말없이 바꾸면 안 된다 - 보고만 하고 그대로 둔다.
        """
        self._bundle_bad = f"{group}: {type(exc).__name__}: {exc}"[:400]
        self._bad_groups.add(group)       # available() 에서 빠져 have_models 가 거짓이 된다
        p = Path(b.path)
        if p.parent != self.dir:
            # 내려받은 것이 아니면 손대지 않는다. **깨진 그룹만** 빼고 나머지
            # 12개는 계속 쓴다 - 처음엔 번들 전체를 버렸는데, 개발자 번들 한
            # 그룹이 상하면 13그룹이 다 죽었다. 과하다.
            return
        self._bundle = None
        try:
            p.rename(p.with_suffix(p.suffix + f".bad-{group}"))
            self._bad_sig = ()            # 파일이 사라졌으니 다시 받게 둔다
            self._bad_groups.clear()      # 새로 받을 파일에 옛 낙인을 물려주지 않는다
            safe = f"corrupt group {group}; quarantined bundle for re-download"
            print(f"[tag-combo] {safe.encode('ascii', 'replace').decode('ascii')}")
        except OSError:
            self._bad_sig = self._bundle_sig()

    def _bundle_sig(self) -> tuple:
        """디스크의 번들 지문. 파일이 바뀌면 실패 기록을 버리기 위한 것이다.

        실패를 영구 캐시하면 **다시 받아도 안 읽는다** - 깨진 번들이 한 번
        기록되는 순간 그 세션은 영영 조합 추천이 없다. 조언 카드에서 실패를
        `null` 로 영구 캐시해 같은 사고를 낸 전례가 있다.
        """
        out = []
        for d in self.search_dirs:
            p = d / BUNDLE_NAME
            try:
                s = p.stat()
                out.append((str(p), s.st_size, s.st_mtime_ns))
            except OSError:
                out.append((str(p), -1, 0))
        return tuple(out)

    def _loose(self, group: str) -> Path | None:
        return next((d / f"{group}.ncsr" for d in self.search_dirs
                     if (d / f"{group}.ncsr").exists()), None)

    def available(self) -> list[str]:
        """실제로 **열리는** 그룹. 인덱스에 이름이 있는 것과는 다르다.

        본문이 깨져 못 읽은 그룹(`_bad_groups`)은 뺀다. 안 그러면 13을 보고하고
        `_have_models()` 가 참이 되어 복구가 영영 시작되지 않는다.
        """
        loose = [g for g in PERSON_GROUPS if self._loose(g) is not None]
        b = self.bundle()
        if b is None:
            return [g for g in loose if g not in self._bad_groups]
        seen = set(loose)
        out = loose + [g for g in PERSON_GROUPS
                       if g in b.entries and g not in seen]
        return [g for g in out if g not in self._bad_groups]

    def _resident_bytes(self) -> int:
        return sum(m.nbytes for m, _ in self._lru.values())

    def _get(self, group: str) -> tuple[ComboModel, ComboQuery] | None:
        with self._lock:
            hit = self._lru.get(group)
            if hit is not None:
                self._lru.move_to_end(group)
                return hit
            loose = self._loose(group)
            path = loose if loose is not None else self.dir / f"{group}.ncsr"
            meta = body = None
            if loose is None:
                b = self.bundle()
                if b is None or group not in b.entries:
                    return None
                try:
                    meta, body = b.read(group)
                except Exception as exc:      # noqa: BLE001 - 아래 주석 참조
                    # ⚠️ 좁게 잡으면 **호출부로 새어나간다.** 원래
                    # `(OSError, ValueError, KeyError)` 였는데, 그룹 본문이 깨지면
                    # `zlib.error` 가 나고 그건 셋 중 무엇도 아니다. 실측:
                    # `1girl_solo` 본문에 0 을 2KB 쓰면 recommend() 가 그대로 터진다.
                    self._on_bundle_corrupt(b, group, exc)
                    return None
            # **들어올 모델의 크기를 알고 자리를 비운다.**
            #
            # 처음엔 `resident > budget * 0.6` 으로 썼는데, 161MB 모델 하나는
            # 400MB 예산의 60%(240MB)를 못 넘어서 두 번째가 그대로 얹혔다 —
            # 실측 상주 324MB / RSS 544MB 로, 막겠다던 겹침을 정확히 허용했다
            # (Codex 게이트). 사이드카만 읽어 들어올 크기를 먼저 재고, 그만큼
            # 자리가 날 때까지 비운다.
            try:
                incoming = (ComboModel.peek_bytes(path) if meta is None
                            else ComboModel.size_from_meta(meta))
            except (OSError, ValueError, KeyError):
                incoming = 0
            while self._lru and self._resident_bytes() + incoming > self.budget:
                self._lru.popitem(last=False)
            model = ComboModel(path, meta=meta, blob=body)
            model.ensure_inverted()
            entry = (model, ComboQuery(model, self.policy))
            self._lru[group] = entry
            # 추정이 빗나갔을 때의 최후 정리. 방금 넣은 것은 남긴다.
            while len(self._lru) > 1 and self._resident_bytes() > self.budget:
                self._lru.popitem(last=False)
            return entry

    # ---- 레시피 뱅크 --------------------------------------------------
    def bank(self):
        """오프라인 레시피 뱅크. 한 번만 읽고 캐시한다."""
        if not self._bank_loaded:
            self._bank_loaded = True
            try:
                from .bank import load as _load
                self._bank = _load(self.search_dirs, self.bundle())
            except Exception as exc:   # noqa: BLE001 - 뱅크가 없어도 기능은 돌아야 한다
                # ⚠️ **삼키되 말은 해라.** 예전엔 조용히 None 이 됐는데, 그러면
                # 옛 형식 번들을 만났을 때 기능이 죽는 대신 **온라인 폴백으로
                # 조용히 내려앉는다** - 추천이 다시 니치해지는데 아무도 모른다
                # (Codex 지적, 실증: 형식 NRB2 번들에 반환 None, stdout 빈 문자열).
                # 상태에도 남겨서 `/api/tag-combo/groups` 로 보인다.
                self._bank = None
                self._bank_error = f"{type(exc).__name__}: {exc}"[:200]
                safe = self._bank_error.encode("ascii", "replace").decode("ascii")
                print(f"[tag-combo] recipe bank unavailable: {safe}")
        return self._bank

    def bank_error(self) -> str:
        """뱅크를 못 읽은 이유. 읽기 전이면 먼저 읽어 본다."""
        self.bank()
        return self._bank_error

    # ---- 질의 --------------------------------------------------------
    def recommend(self, tags: Iterable[str], *, group: str = "") -> dict[str, Any]:
        want = [str(t).strip() for t in tags if str(t).strip()]
        grp = group or person_group_of(set(want))
        if grp not in PERSON_GROUPS:
            return {"error": f"unknown person group: {grp}", "group": grp,
                    "combos": []}

        # **뱅크가 있으면 그쪽이 답이다.** 온라인 경로는 게시물당 한 묶음만
        # 지명해서 흔하면서 적합한 태그를 구조적으로 놓친다(`embarrassed` 의
        # 87.5% 인 `blush` 가 한 번도 지명되지 않는다). 뱅크는 그걸 오프라인
        # 전수로 캔 것이고, 조회는 사전 접근 한 번이다.
        bk = self.bank()
        # **그룹이 뱅크에 아예 없으면 기권이 아니라 폴백이다.** 부분 빌드 상태에서
        # 기권으로 처리하면 안 구운 그룹이 통째로 죽는다 - 그건 데이터가 없는
        # 것이지 "권할 것이 없다" 는 판단이 아니다.
        if bk is not None and bk.anchors(grp):
            probe = [t for t in want if t.lower() not in _PERSON_TAGS] or want
            r = bk.lookup(probe, grp, top_k=self.policy.top_k,
                          min_coverage=self.policy.min_coverage,
                          flat_top=self.policy.flat_top,
                          flat_min_p=self.policy.flat_min_p)
            # ⚠️ **`tags`(평면 나열)를 반드시 함께 흘린다.** 화면은 묶음이 아니라
            # 이걸 쓴다. 처음엔 `combos` 만 담아 보내서 뱅크는 멀쩡한데 화면이
            # 통째로 기권했다 - 조회는 되는데 전달이 안 된 것이라 원인을 찾는 데
            # 한참 걸렸다. 그래서 판정도 둘 중 하나만 있으면 답으로 본다.
            if r["combos"] or r.get("tags"):
                return {
                    "group": grp, "anchor": r["anchor"], "source": "bank",
                    "matched": 0, "bundleSize": 0, "usedPrompt": [r["anchor"]],
                    "backedOff": False, "weak": False,
                    "tags": r.get("tags") or [],
                    "combos": [{"tags": c["tags"], "support": c["support"],
                                "coverage": c.get("coverage", 0.0),
                                "bits": 0.0} for c in r["combos"]],
                }
            # 뱅크가 기권했으면 **기권이 답이다.** 온라인으로 흘려보내면 예전의
            # 니치 추천이 그대로 돌아온다(`smile` -> evil grin 0.10%).
            return {"group": grp, "source": "bank", "combos": [],
                    "abstained": True, "reason": r.get("reason", ""),
                    "matched": 0, "bundleSize": 0, "usedPrompt": [],
                    "backedOff": False, "weak": False}

        entry = self._get(grp)
        if entry is None:
            return {"error": "model not built", "group": grp, "combos": [],
                    "available": self.available()}
        model, q = entry
        # 인원 태그는 그룹을 정의하므로 그룹 안에서 확률이 1.0 이다 - 조건부 정보가
        # 없다. 질의에서 빼야 나머지 태그로 좁혀진다.
        person_tags = {"1girl", "1boy", "solo", "2girls", "2boys",
                       "multiple girls", "multiple boys"}
        probe = [t for t in want if t not in person_tags] or want
        r = q.recommend(probe)
        return {
            "group": grp,
            "matched": r.matched,
            "bundleSize": r.bundle_size,
            "usedPrompt": r.used_prompt,
            "backedOff": r.backed_off,
            "weak": r.weak,
            "combos": [{"tags": c.tags, "support": c.support,
                        "bits": round(c.surprisal, 1)} for c in r.combos],
            "modelPosts": model.header.posts,
        }
