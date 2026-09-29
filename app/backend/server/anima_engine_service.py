"""HTTP composition for the managed engine; no frontend dependency."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from threading import RLock

from core.anima_engine import integration, manifest
from core.anima_engine.install import AnimaInstallJob, adopt_installed_engine, app_version, validate_root
from core.anima_engine.runtime import (AnimaEngineRuntime, ManagedEngineError, REGISTRY, REGISTRY_LOCK,
                                       get_runtime, register_runtime, reserve_vram)
from core.anima_engine.settings import (consent_agreed, license_bundle, license_text, load_settings, lora_catalog,
                                        quick_receipt, record_consent, save_lora_chain, save_settings, unet_catalog)
from core.anima_engine.settings import (delete_lora_thumb, lora_folder, lora_thumb, lora_triggers,
                                        put_lora_thumb, read_lora_thumb)

_SERVICES = {}
_LOCK = RLock()


def service_for(context):
    key = str(integration.save_root_of(context).resolve())
    with _LOCK:
        if key not in _SERVICES:
            _SERVICES[key] = AnimaEngineService(context)
        return _SERVICES[key]


class AnimaEngineService:
    def __init__(self, context, *, job_factory=AnimaInstallJob):
        self.context = context
        self.save_root = integration.save_root_of(context)
        self.job_factory = job_factory
        self.job = None
        self.lock = RLock()

    def forbidden(self):
        paths = getattr(self.context, "runtime_paths", None)
        return [getattr(self.context, "repo_root", None), Path(__file__).resolve().parents[3],
                getattr(paths, "user_root", None)]

    def _job(self):
        if self.job is None:
            settings = load_settings(self.save_root)
            self.job = self.job_factory(save_root=self.save_root, settings=settings, forbidden_roots=self.forbidden(),
                                       on_ready=self._on_ready,
                                       runtime_factory=lambda root, runtime_id: AnimaEngineRuntime(
                                           root, runtime_id=runtime_id, idle_minutes=settings.idle_minutes,
                                           reserve_vram_gb=reserve_vram(self.context, settings)))
        return self.job

    def adopt_installed(self):
        """표준 자리에 이미 끝난 설치가 있으면 가져다 쓴다(adopt_installed_engine) - 기동 · 상태 조회가 부른다."""
        if load_settings(self.save_root).engine_root:
            return None      # 흔한 길 - 자물쇠 없이(복구하는 prepare 는 해시하는 동안 자물쇠를 오래 쥔다)
        # prepare() 와 줄을 세운다: 가져다 쓰기로 정한 뒤 prepare 가 만든 설치 작업을 아래 self.job = None 이 지우면
        # 설치는 돌지만 상태 · 취소 · 엔진 선택(_select)이 다른 작업을 본다(Codex 09-29).
        with self.lock:
            adopted = adopt_installed_engine(self.save_root, forbidden_roots=self.forbidden())
            if adopted:
                # 설치 작업은 만들 때의 설정(engine_root 없음)을 쥐고 있다 - 새 자리로 다시 만든다. 설치 중이면
                # engine_root 가 이미 있어 여기로 오지 않는다.
                self.job = None
                print("ANIMA: adopted an installed engine", flush=True)
            return adopted

    def _on_ready(self, runtime):
        register_runtime(runtime)
        if self.job and self.job._select:
            integration.token_manager_of(self.context).save_token("comfyui_engine", "managed")

    def status(self):
        self.adopt_installed()
        settings = load_settings(self.save_root)
        install = self._job().snapshot()
        receipt = quick_receipt(settings)
        if install["state"] != "preparing" and receipt:
            install = {**install, "state": "ready"}
        ready = bool(receipt) and install["state"] != "preparing"
        with REGISTRY_LOCK:
            rt = REGISTRY.get(str(Path(settings.engine_root).resolve())) if settings.engine_root else None
        # 모델 폴더 칸 밑 한 줄(찾은 모델 · 뺀 파일)용 — 설치가 끝났을 때만 훑는다(2초 캐시)
        models = unet_catalog(settings) if ready else {"available": [], "skipped": []}
        return {"ok": True, "profile": {"id": manifest.PROFILE_ID, "revision": manifest.PROFILE_REVISION, "runtime_id": manifest.RUNTIME_ID},
                "comfyui_engine": "managed" if integration.managed_selected(self.context) else "external", "ready": ready,
                "install": install, "engine": rt.status() if rt else {"state": "stopped", "port": None, "pid": None, "started_at": None, "code": None, "message": ""},
                "receipt": {k: receipt.get(k) for k in ("gpu", "system_stats", "created_at")} if receipt else None,
                "consent": {"agreed": consent_agreed(self.save_root), "bundle_sha256": license_bundle()},
                # default_dir = [초기화] 로 돌아가는 지정 위치(엔진의 모델 폴더) — 화면이 경로 칸에 보인다
                "models": {"available": [x["name"] for x in models["available"]], "skipped": models["skipped"],
                           "default_dir": str(Path(settings.engine_root) / "models" / "diffusion_models") if settings.engine_root else ""},
                "settings": {k: settings.data[k] for k in ("engine_root", "model_dirs", "lora_dirs", "unet_dirs", "idle_minutes",
                                                           "reserve_vram_gb")}}

    def inspect(self, body):
        with self.lock:
            if self._job().snapshot()["state"] == "preparing":
                raise ManagedEngineError("JOB_RUNNING", "설치가 진행 중입니다.")
            return {"ok": True, "plan": self._job().inspect(body.get("engine_root"), body.get("model_dirs"))}

    def prepare(self, body):
        with self.lock:
            if "consent" in body:
                record_consent(self.save_root, body["consent"], app_version())
            elif not consent_agreed(self.save_root):
                raise ManagedEngineError("CONSENT_REQUIRED", "라이선스 동의가 필요합니다.")
            if self._job().snapshot()["state"] == "preparing":
                return {"ok": True, "joined": True, "status": self.status()}
            # Validate and persist root before start; all expensive checks run off the event loop.
            updates = {k: body[k] for k in ("engine_root", "model_dirs") if k in body}
            self.update_settings(updates)
            force = body.get("force_verify", False) is True
            job = self._job()
            if not force and quick_receipt(job.settings):
                return self._use_installed(body)
            job._force = force
            plan = job.inspect()
            for check in plan["checks"]:
                if not check["ok"]:
                    raise ManagedEngineError(check["code"], check["message"])
            if not job.settings.engine_root:
                save_settings(self.save_root, {"engine_root": plan["engine_root"]})
                self.job = None
                job = self._job()
                if not force and quick_receipt(job.settings):
                    return self._use_installed(body)
            result = job.start(select_on_ready=body.get("select_on_ready", True) is True, force_verify=force)
            return {"ok": True, "joined": result["joined"], "status": self.status()}

    def _use_installed(self, body):
        """고른 자리에 이미 끝난 설치가 있다('설치 (0KB)') - 받을 것도, PC 검사(설치 공간 · GPU)도, 엔진을 켜서 다시
        시험할 것도 없다. 가져다 쓴다(사용자 제보 09-29 · 공간 검사가 먼저 막았다 - Codex 09-29). 설치를 마친 것과 같게
        엔진 선택도 따른다(select_on_ready)."""
        if body.get("select_on_ready", True) is True:
            integration.token_manager_of(self.context).save_token("comfyui_engine", "managed")
        return {"ok": True, "joined": False, "status": self.status()}

    def cancel(self):
        self._job().cancel()
        return {"ok": True, "status": self.status()}

    def select(self, engine):
        if engine not in ("managed", "external"):
            raise ManagedEngineError("PARAM_OUT_OF_RANGE", "엔진 선택을 확인해 주세요.")
        if engine == "managed" and not integration.managed_ready(self.context):
            raise ManagedEngineError("ENGINE_NOT_READY", "ANIMA 엔진 준비를 먼저 완료해 주세요.")
        integration.token_manager_of(self.context).save_token("comfyui_engine", engine)
        return {"ok": True, "comfyui_engine": engine}

    def start_engine(self):
        rt = get_runtime(self.context)
        if rt is None:
            raise ManagedEngineError("ENGINE_NOT_READY")
        rt.ensure_running()
        return {"ok": True, "engine": rt.status()}

    def stop_engine(self):
        if self._job().snapshot()["state"] == "preparing":
            raise ManagedEngineError("JOB_RUNNING", "설치 중에는 취소를 사용해 주세요.")
        settings = load_settings(self.save_root)
        with REGISTRY_LOCK:
            rt = REGISTRY.get(str(Path(settings.engine_root).resolve())) if settings.engine_root else None
        if rt:
            rt.stop()
        return {"ok": True, "engine": self.status()["engine"]}

    def update_settings(self, body):
        with self.lock:
            if self.job and self.job.snapshot()["state"] == "preparing":
                raise ManagedEngineError("JOB_RUNNING", "설치가 진행 중입니다.")
            updates = {k: v for k, v in body.items()
                       if k in ("engine_root", "model_dirs", "lora_dirs", "unet_dirs", "idle_minutes", "reserve_vram_gb")}
            current = load_settings(self.save_root)
            # 폴더가 바뀌면 엔진을 다시 켜야 ComfyUI 가 읽는다 — 생성 중에는 막는다
            folders = [k for k in ("lora_dirs", "unet_dirs") if k in updates and updates[k] != current.data[k]]
            if folders and current.engine_root:
                with REGISTRY_LOCK:
                    rt = REGISTRY.get(str(Path(current.engine_root).resolve()))
                if rt and rt.queue_busy():
                    what = "LoRA" if "lora_dirs" in folders else "모델"
                    raise ManagedEngineError("JOB_RUNNING", f"생성이 끝난 뒤 {what} 폴더를 변경해 주세요.")
            if "engine_root" in updates:
                if not updates["engine_root"]:
                    raise ManagedEngineError("PATH_INVALID", "설치 경로를 확인해 주세요.")
                if updates["engine_root"] != current.engine_root:
                    if current.engine_root and (Path(current.engine_root) / "receipt.json").exists():
                        raise ManagedEngineError("PATH_INVALID", "설치 완료 후 엔진 루트를 변경할 수 없습니다.")
                    updates["engine_root"] = str(validate_root(updates["engine_root"], forbidden=self.forbidden()))
            settings = save_settings(self.save_root, updates)
            if folders and settings.engine_root:
                # ComfyUI 는 폴더를 켤 때 읽는다 - 내려 두면 다음 생성이 새 폴더로 다시 켠다(모델 경로 파일은 켤 때 쓴다)
                with REGISTRY_LOCK:
                    rt = REGISTRY.get(str(Path(settings.engine_root).resolve()))
                if rt:
                    rt.stop()
            self.job = None
            return {"ok": True, "settings": copy.deepcopy(settings.data)}

    def loras(self):
        settings = load_settings(self.save_root)
        entries = lora_catalog(settings)
        available = [{**{k: v for k, v in x.items() if k != "path"},
                      "triggers": lora_triggers(x["path"]) if not x["conflict"] else [],
                      "thumb": lora_thumb(settings, x)[1]} for x in entries]
        return {"ok": True, "available": available,
                "chain": settings.lora_chain, "warnings": ["LoRA 이름이 겹칩니다: " + x["name"] for x in entries if x["conflict"]]}

    def put_loras(self, chain):
        chain, warnings = save_lora_chain(self.save_root, chain)
        return {"ok": True, "chain": chain, "warnings": warnings}

    def read_thumb(self, name):
        return read_lora_thumb(load_settings(self.save_root), name)

    def put_thumb(self, name, data):
        return {"ok": True, "thumb": put_lora_thumb(load_settings(self.save_root), name, data)}

    def delete_thumb(self, name):
        delete_lora_thumb(load_settings(self.save_root), name)
        return {"ok": True}

    def open_lora_folder(self, body):
        folder = lora_folder(load_settings(self.save_root), body.get("name"))
        os.startfile(str(folder))
        return {"ok": True, "path": str(folder)}


def licenses_payload():
    return {"ok": True, "bundle_sha256": license_bundle(),
            "items": [{**{k: x[k] for k in ("id", "title", "applies_to", "license", "source_url", "sha256")},
                       "text_url": "/api/anima-engine/licenses/" + x["id"]} for x in manifest.LICENSES],
            "notices": manifest.ATTRIBUTION_NOTICES}
