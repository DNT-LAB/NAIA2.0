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
        # 검역을 **할 수 없는** 자리에서 불량 번들을 만났다는 기록(저장소 경로).
        # 비어 있지 않으면 상태가 `error` 로 앉는다 - 안 그러면 ready/incomplete
        # 를 오가며 프론트가 2초 폴링을 영원히 돈다(Codex 2차 지적 2026-08-17).
        self._blocked = ""
        self._bank_sig: tuple = ()  # 뱅크를 읽은 시점의 파일 지문
        self._bank_lock = threading.Lock()   # 적재 중 반쪽 상태를 남에게 안 보인다

    # ---- 다운로드 ----------------------------------------------------
    def bank_groups(self) -> list[str]:
        """뱅크가 실제로 답할 수 있는 인원 그룹. 화면 추천의 유일한 출처다.

        ⚠️ **"앵커 표가 비어 있지 않다" 로 세면 안 된다.** 앵커마다 `{}` 만 들어
        있어도 13그룹으로 세어져 `ready()` 가 참이 됐다 - 조회는 전부
        `anchor not in bank` 로 기권하는데 다운로드도 시작되지 않았다(Codex 2차
        지적 2026-08-17). 검증(`bundle.bank_answerable_groups`)과 **같은 눈**을
        쓴다. 갈리면 "검증은 떨어뜨렸는데 서비스는 13이라고 센다" 가 된다.
        """
        bk = self.bank()
        if bk is None:
            return []
        from .bundle import bank_answerable_groups
        ok = set(bank_answerable_groups({"groups": getattr(bk, "groups", None) or {}}))
        return [g for g in PERSON_GROUPS if g in ok]

    def ready(self) -> bool:
        """받을 필요가 **없는지**.

        기준은 **뱅크가 13그룹을 답할 수 있는가** 다. 배포 번들에는 그룹 모델이
        들어가지 않는다(203MB -> 15MB) - 화면 추천은 전적으로 레시피 뱅크에서
        나오고, 모델은 개발 머신에서 뱅크를 캐는 데만 쓴다.

        예전 기준은 '13그룹 모델을 다 쓸 수 있다' 였는데, 그대로 두면 부속만 담은
        번들을 받은 설치가 **영원히 `incomplete`** 가 된다(Codex 지적 2026-08-17).

        모델 기준으로 판정하던 시절의 두 구멍은 뱅크 기준에도 그대로 적용된다:
        깨진 파일도 존재는 하므로 파일 존재로 보면 안 되고, 일부만 있는 것으로
        전체를 갈음해서도 안 된다. 그래서 '13그룹을 다 덮을 때만 참' 이다.
        """
        return set(self.bank_groups()) >= set(PERSON_GROUPS)

    # 옛 이름. 호출부가 아직 남아 있을 수 있어 남겨 둔다 - 의미는 새 기준이다.
    def _have_models(self) -> bool:
        return self.ready()

    def _bundle_verdict(self) -> list[str]:
        """받는 곳의 번들이 **쓸 수 있는가.** 못 쓰면 이유들, 쓸 수 있으면 빈 목록.

        판정과 처분(검역)을 나눠 둔다 - 저장소 경로에서는 처분을 못 하는데 판정은
        해야 하기 때문이다. 한 함수에 섞어 뒀더니 저장소 경로에서 판정 자체를
        건너뛰어 상태가 `ready ↔ incomplete` 를 오갔다(Codex 2차 지적).
        """
        p = self.downloader.path
        if not p.is_file():
            return []
        try:
            from .bundle import ComboBundle
            b = ComboBundle(p)
            bad = b.verify_all()
            # **`verify_all` 만으로는 부족하다.** version 1(NCSB1)은 부속이 없는
            # 것이 정상이라 통과한다 - 그런데 배포 이름을 단 그 파일에는 뱅크가
            # 없으니 서비스는 영원히 `incomplete` 다(Codex 실증:
            # `legacy_v1_empty_verify_all []` / `ensure_state ready`).
            # 받는 곳의 현재 이름은 **부속을 담은 version 2** 여야 한다.
            if not bad and int(b.index.get("version") or 1) < 2:
                bad = ["legacy:v1-without-aux"]
            return list(bad)
        except Exception:              # noqa: BLE001 - 열지도 못하면 그것도 불량이다
            return ["unreadable"]

    def quarantine_bad_bundle(self) -> str:
        """받는 곳에 **있는데 쓸 수 없는** 번들을 치운다. 이름을 돌려준다.

        ⚠️ **이게 없으면 무한 폴링에 갇힌다.** `downloader.start()` 는 파일
        존재만 보고 곧장 ready 를 낸다. 그런데 그 파일이 부분/손상/옛 형식이면
        서비스가 다시 `incomplete` 로 바꾸고, 프론트는 "다시 받는 중" 을 2초마다
        영원히 폴링한다 - 복구 경로가 없다(Codex 지적 2026-08-17). v4 이름 변경은
        옛 v3 설치만 구제하고, 잘못 올린 v4 에는 아무 도움이 안 된다.
        """
        p = self.downloader.path
        if not p.is_file():
            return ""
        # ⚠️ **저장소 번들은 절대 건드리지 않는다.** 보통은 받는 곳이 런타임
        # data_dir 이라 문제가 없는데, 런타임 경로 해석이 실패하면 `resolve_dirs`
        # 가 저장소 `data/tag_combo` 를 받는 곳으로 돌려준다(Codex 지적). 그러면
        # 개발자가 방금 구운 산출물을 말없이 `.bad` 로 바꾸게 된다.
        #
        # ⚠️ 그런데 **그냥 `return ""` 하면 아까 고친 무한 루프가 되돌아온다.**
        # 파일은 그대로 남고 -> `start()` 는 있다고 ready 를 내고 ->
        # `download_status()` 는 다시 incomplete 로 내린다. 재다운로드도 안 되고
        # 안정적인 오류 착지도 없다(Codex 2차 실증 2026-08-17). 치우지 않는 것은
        # 맞지만, **막혔다는 사실을 남겨** 상태가 `error` 로 앉게 한다 - 프론트는
        # error 에서 2초 폴링을 멈춘다.
        in_repo = False
        try:
            in_repo = p.resolve().parent == (Path(__file__).resolve().parents[2]
                                            / "data" / "tag_combo")
        except OSError:
            return ""
        if in_repo:
            if self._bundle_verdict():
                self._blocked = ("bundle in repo data dir is unusable; "
                                 "rebuild it or fix the runtime data path")
            return ""
        bad = self._bundle_verdict()
        if not bad:
            return ""                  # 멀쩡하다 - 준비 안 된 이유가 다른 데 있다
        try:
            dst = p.with_suffix(p.suffix + ".bad")
            dst.unlink(missing_ok=True)
            p.replace(dst)
        except OSError:
            return ""
        self._bundle = None
        self._bundle_bad = ""
        self._bad_sig = ()
        self._bank_loaded = False      # 다음 조회가 다시 읽는다
        safe = f"quarantined unusable bundle ({bad[:2]}); will re-download"
        print(f"[tag-combo] {safe.encode('ascii', 'replace').decode('ascii')}")
        return dst.name

    def ensure_bundle(self, *, retry: bool = False) -> dict:
        """Interactive 를 열 때 부른다. 이미 있으면 아무것도 안 한다."""
        if self.ready():
            st = self.downloader.status()
            st["state"] = "ready"
            return st
        # 준비가 안 됐는데 파일은 있다 -> 그 파일이 불량인지 보고, 불량이면 치운다.
        # 치우지 않으면 아래 `start()` 가 "이미 있다" 며 ready 를 내고 끝난다.
        self.quarantine_bad_bundle()
        # 치울 수 **없는** 자리였다면(저장소 경로) `start()` 는 파일이 있다고
        # `ready` 를 내는데 그건 거짓이다 - 프론트는 그 말을 믿고 폴링도 안 하고
        # 안내도 안 띄운다(추천만 조용히 없다). 두 엔드포인트가 같은 말을 하게 한다.
        if self._blocked:
            st = self.downloader.status()
            st["state"] = "error"
            st["error"] = self._blocked
            return st
        return self.downloader.retry() if retry else self.downloader.start()

    def download_status(self) -> dict:
        st = self.downloader.status()
        # `available()` 을 먼저 불러 `_bundle_bad` 를 갱신한다(모델 목록은 이제
        # 준비 판정이 아니라 개발 정보다).
        groups = self.available()
        bgroups = self.bank_groups()
        ok = set(bgroups) >= set(PERSON_GROUPS)
        # **뱅크가 13그룹을 답할 수 있으면 그것이 ready 다 - 상태를 무엇이었든.**
        # 예전엔 `idle/ready` 에서만 승격해서, 지난 회차의 `error` 가 남아 있으면
        # 추천은 정상인데 API 는 error 였다(Codex 실증: `ready() True` /
        # `download_status error missing 0 bankGroups 13`). 프론트는 그 error 를 보고
        # "받지 못했습니다" 를 띄운다 - 실제로는 다 되어 있는데.
        if ok:
            st["state"] = "ready"
            st["error"] = ""
            self._blocked = ""         # 답이 나오면 막힘도 끝났다
        elif self._blocked:
            # **검역할 수 없는 자리의 불량 번들.** 파일을 치울 수 없으니 다시 받을
            # 수도 없다 - 그러면 `incomplete` 로 두면 안 된다(프론트가 2초마다
            # 영원히 폴링한다). `error` 는 프론트가 폴링을 멈추고 30초 뒤 한 번만
            # 재시도하는 상태다 - 사람이 손댈 수 있는 착지점이다.
            st["state"] = "error"
            st["error"] = self._blocked
        elif st.get("state") == "ready":
            # 파일은 있는데 뱅크가 13그룹을 못 채운다 - 깨졌거나 일부만 있다.
            # 여기서 ready 라고 하면 프론트가 안내를 지우고 사용자는 빈 화면만 본다.
            st["state"] = "incomplete"
        st["loose"] = [g for g in PERSON_GROUPS if self._loose(g) is not None]
        st["groups"] = groups                 # 모델(개발 머신에만 있다)
        st["bankGroups"] = bgroups            # 실제 답할 수 있는 그룹
        st["missing"] = [g for g in PERSON_GROUPS if g not in set(bgroups)]
        st["bank"] = bool(bgroups)
        if self._bank_error:
            st["bankError"] = self._bank_error
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

    def _bank_sig_now(self) -> tuple:
        """뱅크가 올 수 있는 **모든 경로**의 지문.

        `_bundle_sig()` 만 쓰면 안 된다 - 개발 머신에서는 느슨한
        `recipe_bank.json` 이 정상 경로이고(`bank.load` 가 그걸 먼저 본다),
        그 파일이 새로 생겨도 지문이 안 바뀌어 옛 `None` 을 계속 물었다
        (내 회귀 테스트가 잡았다).
        """
        from .bank import BANK_NAME
        out = list(self._bundle_sig())
        for d in self.search_dirs:
            p = d / BANK_NAME
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
        """오프라인 레시피 뱅크. 한 번만 읽고 캐시한다.

        ⚠️ **파일이 바뀌면 다시 읽는다.** 예전에는 첫 조회가 `None` 이면 그걸
        프로세스 수명 동안 물고 있었다. 그러면 **다운로드가 끝나도 뱅크가 안
        붙는다** - 사용자는 받기 전에 Interactive 를 한 번 열었을 뿐인데 재시작
        전까지 추천이 없다(Codex 지적 2026-08-17). 번들 지문으로 판정한다.

        ⚠️ **적재를 락 안에서 하고 끝난 것만 publish 한다.** 예전에는
        `_bank_loaded = True` 를 실제 load **앞에** 세우고 락이 없었다. 그러면
        동시에 들어온 status/recommend 요청이 중간의 `_bank=None` 을 본다
        (Codex 지적 2026-08-17) - 라우트는 스레드로 넘기므로 실제로 동시다.
        """
        sig = self._bank_sig_now()
        if self._bank_loaded and sig == self._bank_sig:
            return self._bank                      # 흔한 길: 락 없이 읽는다
        with self._bank_lock:
            # 락을 잡는 동안 남이 이미 같은 지문으로 채웠을 수 있다.
            if self._bank_loaded and sig == self._bank_sig:
                return self._bank
            got, err = None, ""
            try:
                from .bank import load as _load
                self._bundle = None    # 번들 핸들도 옛 파일을 가리킬 수 있다
                got = _load(self.search_dirs, self.bundle())
            except Exception as exc:   # noqa: BLE001 - 뱅크가 없어도 기능은 돌아야 한다
                # ⚠️ **삼키되 말은 해라.** 예전엔 조용히 None 이 됐는데, 그러면
                # 옛 형식 번들을 만났을 때 기능이 죽는 대신 조용히 성능이
                # 떨어졌다(실증: 형식 NRB2 번들에 반환 None, stdout 빈 문자열).
                # 상태에도 남겨서 `/api/tag-combo/groups` 로 보인다.
                err = f"{type(exc).__name__}: {exc}"[:200]
                safe = err.encode("ascii", "replace").decode("ascii")
                print(f"[tag-combo] recipe bank unavailable: {safe}")
            # 완성된 결과만 한 번에 내놓는다.
            self._bank, self._bank_error = got, err
            self._bank_sig = sig
            self._bank_loaded = True
            return self._bank

    def bank_error(self) -> str:
        """뱅크를 못 읽은 이유. 읽기 전이면 먼저 읽어 본다."""
        self.bank()
        return self._bank_error

    # ---- 질의 --------------------------------------------------------
    def recommend(self, tags: Iterable[str], *, group: str = "",
                  anchor: str = "") -> dict[str, Any]:
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
        # **그룹이 뱅크에 없으면 데이터 오류다.** 예전에는 온라인 모델로 폴백했다.
        # 그건 "부분 빌드 상태에서 안 구운 그룹이 통째로 죽는 것을 막는다" 는
        # 뜻이었는데, 배포에는 이제 모델이 안 가므로 폴백할 대상이 없다. 완전한
        # 13그룹 뱅크는 **빌드 게이트**가 보장한다(build_recipe_bank ->
        # build_tag_combo_bundle, 부속만 담기가 기본이고 그때 13그룹을 강제한다).
        # 그래도 없다면 그건 손상이지 "권할 것이 없다" 는 판단이 아니므로, 조용한
        # 니치 추천 대신 오류로 드러낸다(Codex 지적 2026-08-17).
        if bk is not None and not bk.anchors(grp):
            return {"error": "bank group missing", "group": grp, "combos": [],
                    "tags": [], "bankGroups": self.bank_groups(),
                    "detail": self._bank_error}
        if bk is not None and bk.anchors(grp):
            probe = [t for t in want if t.lower() not in _PERSON_TAGS] or want
            r = bk.lookup(probe, grp, top_k=self.policy.top_k,
                          min_coverage=self.policy.min_coverage,
                          flat_top=self.policy.flat_top,
                          flat_min_p=self.policy.flat_min_p,
                          prefer=anchor)
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

        # ⚠️ **제품 경로는 뱅크 전용이다. 온라인 모델로 떨어지지 않는다.**
        #
        # 여기 예전에 `self._get(grp)` -> `ComboQuery` 폴백이 있었다. 그러면 같은
        # 상태에서 **개발 머신과 배포가 다른 답을 낸다**(Codex 지적 2026-08-17):
        #
        #   느슨한 모델 있는 개발 머신: 뱅크가 없거나 깨져도 온라인이 답한다
        #   뱅크만 있는 배포:           같은 상태에서 오류
        #   다운로드 중 개발 머신:      옛 온라인 추천이 화면에 캐시된다
        #   다운로드 중 배포:           빈 카드
        #
        # 그러면 개발 중에는 절대 재현되지 않는 배포 전용 결함이 생긴다. 게다가
        # 온라인 경로는 게시물당 한 묶음만 지명해 `blush`(87.5%) 를 구조적으로
        # 놓치는 그 경로다 - 조용히 그쪽으로 내려앉는 것은 성능 저하다.
        #
        # `ComboQuery` 와 느슨한 모델은 오프라인 빌더와 감사 도구에만 남긴다.
        return {"error": "bank not ready", "group": grp, "combos": [], "tags": [],
                "bankGroups": self.bank_groups(), "detail": self._bank_error}
