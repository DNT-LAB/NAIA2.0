"""Anima Ref Adapter v2 - 관리형 엔진의 추가 구성 요소(사용자 지정 2026-11-05: ANIMA 모드 전용 REF).

엔진 설치(영수증 · PROFILE_REVISION · 동의 묶음)와 따로 간다 - 이것이 없거나 깨져도 엔진은 그대로 '준비됨' 이고, 참조를 켠
생성만 거절한다. 받는 것 셋(전부 고정 판 · SHA-256 확인):
  - 노드  ArcAnima/ComfyUI-Anima-Ref-Adapter 0.2.0(커밋 COMMIT) -> runtime/.../custom_nodes/ComfyUI-Anima-Ref-Adapter
  - 가중치 anima_ref_adapter_v2_r64.safetensors(HF 판 고정)    -> <engine_root>/models/ref_adapter/
           ⚠️ engine_root/models/loras 에 두지 않는다 - 그 폴더는 NAIA 의 LoRA 목록(lora_catalog)이 훑는다.
           ComfyUI 에는 모델 경로 파일의 naia_ref_adapter 칸(settings.write_model_config)으로 loras 에 보인다.
  - NAIA 노드 naia-ref-spectrum-key(이 저장소의 nodes/naia_ref_spectrum_key.py) - Spectrum 이 참조 뺀 계산을 진짜 계산과
           한 예측기에 섞어 그림을 노이즈로 만드는 것을 막는다(원격 실측 11-05: MAE 94 -> 14, 끈 기준과 같은 그림).
노드는 ComfyUI 가 켤 때만 읽는다 - 설치 뒤 엔진이 켜져 있으면 쉬고 있을 때 내리고, 아니면 참조를 켠 다음 생성이 다시 켠다
(integration.prepare_managed_request).
"""
from __future__ import annotations

import hashlib
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import manifest
from .settings import atomic_json, read_json

COMMIT = "99c222e1c2da472f4b514583b2dbd1b5afb4bdd9"
NODE_DIR = "ComfyUI-Anima-Ref-Adapter"
_RAW = "https://raw.githubusercontent.com/ArcAnima/ComfyUI-Anima-Ref-Adapter/" + COMMIT + "/"
NODE_FILES = [
    {"path": "__init__.py", "size": 35839, "sha256": "5f6efe5745385bd28d3dda47a6b8e7c103b4f6edf33a9d883abf9c26bc5b405d"},
    {"path": "LICENSE", "size": 11358, "sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"},
    {"path": "pyproject.toml", "size": 338, "sha256": "4e24c90202cec62ae91a67e725593c42a3f65c599f346e4fffcf84b7537d5d6d"},
]
for _item in NODE_FILES:
    _item["url"] = _RAW + _item["path"]
WEIGHT = {"filename": "anima_ref_adapter_v2_r64.safetensors", "size": 183605032,
          "sha256": "71dda6079e18d354e16e3347bc49a9b710afd9495c378efbb833d30cac9cb81b",
          "url": "https://huggingface.co/ElectronGirl/anima-ref-adapter/resolve/"
                 "b729afd0c3307f27438df42697ccafaecf051d26/anima_ref_adapter_v2_r64.safetensors"}
KEY_NODE_DIR = "naia-ref-spectrum-key"
KEY_NODE_SOURCE = Path(__file__).resolve().parent / "nodes" / "naia_ref_spectrum_key.py"
NODE_CLASSES = ("LoadImage", "AnimaRefAdapter", "NaiaRefSpectrumKey")
# 화면의 [받기] 옆에 보이는 것 - 글은 엔진 묶음에 이미 있는 같은 본문(같은 SHA-256)을 연다.
# url = 원저자 페이지(사용자 지시 2026-11-05: 우리는 받아 쓰기만 하니 이름을 원저자 페이지 링크로).
LICENSES = [
    {"name": "ComfyUI-Anima-Ref-Adapter 0.2.0", "license": "Apache-2.0", "text_id": "apache2_qwen",
     "url": "https://github.com/ArcAnima/ComfyUI-Anima-Ref-Adapter"},
    {"name": "anima_ref_adapter_v2_r64", "license": "CircleStone Non-Commercial v1.2", "text_id": "circlestone_nc",
     "url": "https://huggingface.co/ElectronGirl/anima-ref-adapter"},
]
DOWNLOAD_BYTES = WEIGHT["size"] + sum(x["size"] for x in NODE_FILES)

_JOBS: dict[str, "RefAdapterInstall"] = {}
_JOBS_LOCK = threading.Lock()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def key_node_sha256() -> str:
    return _sha256(KEY_NODE_SOURCE)


def comfy_dir(engine_root) -> Path:
    return Path(engine_root) / "runtime" / manifest.RUNTIME_ID / "ComfyUI_windows_portable" / "ComfyUI"


def weight_dir(engine_root) -> Path:
    return Path(engine_root) / "models" / "ref_adapter"


def receipt_path(engine_root) -> Path:
    return Path(engine_root) / "state" / "ref_adapter.json"


def installed(engine_root) -> bool:
    """빠른 판정(영수증 + 크기) - 해시는 설치 때 확인했다. 엔진을 다시 풀면(복구) custom_nodes 가 비어 여기서 걸린다."""
    if not engine_root:
        return False
    root = Path(engine_root)
    receipt = read_json(receipt_path(root))
    if (receipt.get("commit"), receipt.get("weight_sha256"), receipt.get("runtime_id")) != (
            COMMIT, WEIGHT["sha256"], manifest.RUNTIME_ID):
        return False
    try:
        if (weight_dir(root) / WEIGHT["filename"]).stat().st_size != WEIGHT["size"]:
            return False
        nodes = comfy_dir(root) / "custom_nodes"
        for item in NODE_FILES:
            if (nodes / NODE_DIR / item["path"]).stat().st_size != item["size"]:
                return False
        key = nodes / KEY_NODE_DIR / "__init__.py"
        # NAIA 노드는 이 판의 것과 같아야 한다(작은 파일 - 해시로)
        return key.is_file() and receipt.get("key_sha256") == key_node_sha256() == _sha256(key)
    except OSError:
        return False


def status(engine_root) -> dict:
    job = job_for(engine_root) if engine_root else None
    state = job.snapshot() if job else {"state": "idle", "percent": 0, "message": "", "error": ""}
    ready = installed(engine_root)
    if ready and state["state"] != "installing":
        state = {**state, "state": "ready"}
    return {"installed": ready, **state, "download_mb": round(DOWNLOAD_BYTES / 1048576),
            "licenses": [{**x, "text_url": "/api/anima-engine/licenses/" + x["text_id"]} for x in LICENSES]}


def job_for(engine_root) -> "RefAdapterInstall":
    key = str(Path(engine_root).resolve())
    with _JOBS_LOCK:
        if key not in _JOBS:
            _JOBS[key] = RefAdapterInstall(Path(key))
        return _JOBS[key]


def _replace_verified(source: Path, target: Path, sha256: str) -> None:
    """검증된 사본으로 바꾼다(하드 링크일 수 있는 기존 파일을 덮어쓰지 않는다 - install.py 와 같은 규칙)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp-" + uuid.uuid4().hex)
    try:
        shutil.copyfile(source, temporary)
        if _sha256(temporary) != sha256:
            raise OSError("copied file hash mismatch: " + target.name)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


class RefAdapterInstall:
    """[받기] 한 번 = 스레드 하나. 받은 것은 cache/ref_adapter 와 models/ref_adapter 에 남아 다시 받을 때 쓴다."""

    def __init__(self, engine_root: Path, *, downloader=None, stop_idle_engine=None):
        self.root = Path(engine_root)
        self._lock = threading.Lock()
        self._thread = None
        self._state = {"state": "idle", "percent": 0, "message": "", "error": ""}
        self._downloader = downloader
        self._stop_idle_engine = stop_idle_engine

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _set(self, **updates):
        with self._lock:
            self._state.update(updates)

    def start(self) -> dict:
        from .runtime import ADDON_INSTALLING, INSTALLING, REGISTRY_LOCK
        with self._lock:
            if self._state["state"] == "installing":
                return dict(self._state)
            # 엔진 설치 · 복구와 서로 막는다 - 확인과 등록을 한 자물쇠 안에서(엔진 설치 start 도 같은 자물쇠로 본다)
            with REGISTRY_LOCK:
                if str(self.root) in INSTALLING:
                    raise RuntimeError("ENGINE_INSTALLING")
                ADDON_INSTALLING.add(str(self.root))
            self._state = {"state": "installing", "percent": 0, "message": "받는 중…", "error": ""}
            self._thread = threading.Thread(target=self._run, daemon=True, name="anima-ref-adapter-install")
            self._thread.start()
            return dict(self._state)

    def wait(self, timeout=None):
        thread = self._thread
        if thread:
            thread.join(timeout)

    def _download(self, url, target: Path, sha256: str, size: int, done_before: int):
        if target.is_file() and target.stat().st_size == size and _sha256(target) == sha256:
            return
        if self._downloader is not None:
            self._downloader(url, target, sha256, size)
            return
        from core.llama_model_download import LlamaModelDownloadService
        service = LlamaModelDownloadService(target, url=url, sha256=sha256, expected_size=size)
        service.start()
        while True:
            state = service.snapshot()
            if not state["active"]:
                break
            got = int(float(state.get("downloaded_mb") or 0) * 1048576)
            self._set(percent=min(99, int((done_before + got) * 100 / DOWNLOAD_BYTES)))
            service.wait(0.2)
        if not service.snapshot()["done"]:
            raise OSError(service.snapshot().get("error") or "download failed")

    def _run(self):
        finished = False
        try:
            if not (comfy_dir(self.root) / "main.py").is_file():
                raise OSError("ANIMA 엔진 설치를 찾지 못했습니다.")
            cache = self.root / "cache" / "ref_adapter"
            done = 0
            for item in NODE_FILES:
                self._download(item["url"], cache / item["path"], item["sha256"], item["size"], done)
                done += item["size"]
            weight = weight_dir(self.root) / WEIGHT["filename"]
            self._download(WEIGHT["url"], weight, WEIGHT["sha256"], WEIGHT["size"], done)
            self._set(percent=99, message="설치 중…")
            nodes = comfy_dir(self.root) / "custom_nodes"
            for item in NODE_FILES:
                _replace_verified(cache / item["path"], nodes / NODE_DIR / item["path"], item["sha256"])
            key_sha = key_node_sha256()
            _replace_verified(KEY_NODE_SOURCE, nodes / KEY_NODE_DIR / "__init__.py", key_sha)
            atomic_json(receipt_path(self.root), {
                "version": 1, "commit": COMMIT, "weight_sha256": WEIGHT["sha256"], "key_sha256": key_sha,
                "runtime_id": manifest.RUNTIME_ID, "installed_at": datetime.now().astimezone().isoformat()})
            # 켜져 있는 엔진은 새 노드를 모른다 - 쉬고 있으면 내린다(다음 생성이 새로 켠다)
            (self._stop_idle_engine or stop_idle_engine)(self.root)
            self._finish(state="ready", percent=100, message="Ref Adapter 준비 완료", error="")
            finished = True
        except Exception as exc:          # 화면에 까닭을 보인다 - 다시 누르면 받은 것은 건너뛴다
            self._finish(state="failed", message="Ref Adapter 설치에 실패했습니다.", error=f"{type(exc).__name__}: {exc}")
            finished = True
        finally:
            # 예외 밖의 탈출(BaseException)만 - 이 작업이 아직 닫히지 않았으면 닫는다. 이미 닫았으면(finished) 손대지
            # 않는다: 그 뒤에 들어온 재시도 작업의 'installing' 을 이 작업이 닫으면 안 된다.
            if not finished:
                self._finish(state="failed", message="Ref Adapter 설치가 중단됐습니다.", error="")

    def _finish(self, **state):
        """끝 상태를 보이는 일과 표식을 거두는 일을 한 자물쇠 구간에서 - 그 사이에 재시도(start)가 끼어 새 작업의
        표식을 이 작업이 지우지 않게(start 도 self._lock 안에서 상태를 보고 표식을 적는다 - Codex 재리뷰 2026-11-05)."""
        from .runtime import ADDON_INSTALLING, REGISTRY_LOCK
        with self._lock:
            with REGISTRY_LOCK:
                ADDON_INSTALLING.discard(str(self.root))
            self._state.update(state)


def stop_idle_engine(engine_root) -> bool:
    from .runtime import REGISTRY, REGISTRY_LOCK
    with REGISTRY_LOCK:
        runtime = REGISTRY.get(str(Path(engine_root).resolve()))
    if runtime is None or runtime.queue_busy():
        return False
    # NAIA 가 보내고 받는 중이면(in_use) 내리지 않는다 - 그 판정과 내리기를 한 자물쇠 안에서
    return runtime.stop_if_unused()
