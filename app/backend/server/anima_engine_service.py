"""HTTP composition for the managed engine; no frontend dependency."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from threading import RLock

from core.anima_engine import integration, manifest
from core.anima_engine.install import AnimaInstallJob, app_version, validate_root
from core.anima_engine.runtime import (AnimaEngineRuntime, ManagedEngineError, REGISTRY, REGISTRY_LOCK,
                                       get_runtime, register_runtime, reserve_vram)
from core.anima_engine.settings import (consent_agreed, license_bundle, license_text, load_settings, lora_catalog,
                                        quick_receipt, record_consent, save_lora_chain, save_settings, write_model_config)
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

    def _on_ready(self, runtime):
        register_runtime(runtime)
        if self.job and self.job._select:
            integration.token_manager_of(self.context).save_token("comfyui_engine", "managed")

    def status(self):
        settings = load_settings(self.save_root)
        install = self._job().snapshot()
        receipt = quick_receipt(settings)
        if install["state"] != "preparing" and receipt:
            install = {**install, "state": "ready"}
        ready = bool(receipt) and install["state"] != "preparing"
        with REGISTRY_LOCK:
            rt = REGISTRY.get(str(Path(settings.engine_root).resolve())) if settings.engine_root else None
        return {"ok": True, "profile": {"id": manifest.PROFILE_ID, "revision": manifest.PROFILE_REVISION, "runtime_id": manifest.RUNTIME_ID},
                "comfyui_engine": "managed" if integration.managed_selected(self.context) else "external", "ready": ready,
                "install": install, "engine": rt.status() if rt else {"state": "stopped", "port": None, "pid": None, "started_at": None, "code": None, "message": ""},
                "receipt": {k: receipt.get(k) for k in ("gpu", "system_stats", "created_at")} if receipt else None,
                "consent": {"agreed": consent_agreed(self.save_root), "bundle_sha256": license_bundle()},
                "settings": {k: settings.data[k] for k in ("engine_root", "model_dirs", "lora_dirs", "idle_minutes", "reserve_vram_gb")}}

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
            job = self._job()
            job._force = body.get("force_verify", False) is True
            plan = job.inspect()
            for check in plan["checks"]:
                if not check["ok"]:
                    raise ManagedEngineError(check["code"], check["message"])
            if not job.settings.engine_root:
                save_settings(self.save_root, {"engine_root": plan["engine_root"]})
                self.job = None
                job = self._job()
            result = job.start(select_on_ready=body.get("select_on_ready", True) is True,
                               force_verify=body.get("force_verify", False) is True)
            return {"ok": True, "joined": result["joined"], "status": self.status()}

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
            updates = {k: v for k, v in body.items() if k in ("engine_root", "model_dirs", "lora_dirs", "idle_minutes", "reserve_vram_gb")}
            current = load_settings(self.save_root)
            if "lora_dirs" in updates and updates["lora_dirs"] != current.lora_dirs and current.engine_root:
                with REGISTRY_LOCK:
                    rt = REGISTRY.get(str(Path(current.engine_root).resolve()))
                if rt and rt.queue_busy():
                    raise ManagedEngineError("JOB_RUNNING", "생성이 끝난 뒤 LoRA 폴더를 변경해 주세요.")
            if "engine_root" in updates:
                if not updates["engine_root"]:
                    raise ManagedEngineError("PATH_INVALID", "설치 경로를 확인해 주세요.")
                if updates["engine_root"] != current.engine_root:
                    if current.engine_root and (Path(current.engine_root) / "receipt.json").exists():
                        raise ManagedEngineError("PATH_INVALID", "설치 완료 후 엔진 루트를 변경할 수 없습니다.")
                    updates["engine_root"] = str(validate_root(updates["engine_root"], forbidden=self.forbidden()))
            settings = save_settings(self.save_root, updates)
            if "lora_dirs" in updates:
                receipt = quick_receipt(settings)
                if receipt:
                    write_model_config(settings, {k: v["path"] for k, v in receipt["models"].items()})
                    # New search paths are read by ComfyUI at startup.
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
