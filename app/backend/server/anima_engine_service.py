"""HTTP composition for the managed engine; no frontend dependency."""
from __future__ import annotations

import copy
import os
import traceback
from datetime import datetime
from pathlib import Path
from threading import RLock

from core.anima_engine import diagnostics, integration, manifest, mode_release
from core.anima_engine.install import AnimaInstallJob, adopt_installed_engine, app_version, validate_root
from core.anima_engine.runtime import (AnimaEngineRuntime, ManagedEngineError, REGISTRY, REGISTRY_LOCK, TRACE_CHARS,
                                       engine_unet_names, get_runtime, read_log_since, register_runtime, reserve_vram)
from core.anima_engine.settings import (consent_agreed, forget_unet_catalog, license_bundle, license_text, load_settings,
                                        lora_catalog, quick_receipt, read_json, record_consent, save_lora_chain,
                                        save_settings, unet_catalog, unet_folders)
from core.anima_engine.settings import (delete_lora_thumb, lora_folder, lora_thumb, lora_triggers,
                                        png_from_image, put_lora_thumb, read_lora_thumb, set_lora_keyword)
from core.anima_engine.profile import ProfileError

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
        self.last_error = None     # 마지막 요청 오류(검사 · 설치 · 엔진 켜기 …) - 진단 정보에 싣는다
        self.last_checks = None    # 마지막 PC 검사 결과(OS · GPU · 공간)

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
            plan = self._job().inspect(body.get("engine_root"), body.get("model_dirs"))
            self.last_checks = plan["checks"]
            return {"ok": True, "plan": plan}

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
            self.last_checks = plan["checks"]
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
        was_anima = mode_release.anima_active(self.context)
        integration.token_manager_of(self.context).save_token("comfyui_engine", engine)
        # 메인 셀렉트의 COMFYUI 로 바꿔 ANIMA 모드를 떠났으면 10초 뒤 엔진을 내린다 · 돌아왔으면 취소(mode_release)
        mode_release.note(self.context, was_anima)
        return {"ok": True, "comfyui_engine": engine}

    def start_engine(self):
        rt = get_runtime(self.context)
        if rt is None:
            raise ManagedEngineError("ENGINE_NOT_READY")
        rt.ensure_running()
        return {"ok": True, "engine": rt.status()}

    def engine_log(self, since=None):
        """엔진이 켜지는 동안 ComfyUI 가 적는 것 - 생성 화면의 임시 콘솔이 since 부터 이어 받는다(엔진 상태와 함께)."""
        settings = load_settings(self.save_root)
        with REGISTRY_LOCK:
            rt = REGISTRY.get(str(Path(settings.engine_root).resolve())) if settings.engine_root else None
        engine = rt.status() if rt else {"state": "stopped", "port": None, "pid": None, "started_at": None,
                                         "code": None, "message": ""}
        if not settings.engine_root:
            return {"ok": True, "engine": engine, "text": "", "since": 0}
        text, nxt = read_log_since(Path(settings.engine_root) / "state/engine.log", since)
        return {"ok": True, "engine": engine, "text": text, "since": nxt}

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

    def remember_error(self, action, exc):
        """요청이 실패했다 - 진단 정보의 '마지막 요청 오류' 로. 어디서 났는지(Traceback)까지 - except 안에서 부른다."""
        self.last_error = {"action": action, "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                           "code": getattr(exc, "code", "") or type(exc).__name__,
                           "message": getattr(exc, "message", "") or str(exc),
                           "detail": str(getattr(exc, "detail", "") or ""),
                           "trace": traceback.format_exc()[-TRACE_CHARS:]}

    def diagnostics(self):
        """실패 화면의 [자세히] · [에러 로그 복사] - 제보에 붙여 넣을 텍스트 하나(core/anima_engine/diagnostics.py)."""
        status = self.status()
        settings = load_settings(self.save_root)
        journal = read_json(Path(settings.engine_root) / "state/job.json") if settings.engine_root else {}
        job = self.job
        with REGISTRY_LOCK:
            rt = REGISTRY.get(str(Path(settings.engine_root).resolve())) if settings.engine_root else None
        text = diagnostics.build_report(
            settings=settings, install=status["install"], journal=journal,
            job_trace=getattr(job, "_trace", "") or "", job_phases=list(getattr(job, "_completed", []) or []),
            request_error=self.last_error, checks=self.last_checks, engine=status["engine"],
            engine_error=getattr(rt, "last_error", None), comfyui_engine=status["comfyui_engine"])
        return {"ok": True, "text": text}

    def loras(self):
        settings = load_settings(self.save_root)
        entries = lora_catalog(settings)
        available = [{**{k: v for k, v in x.items() if k != "path"},
                      "keyword": (settings.lora_keywords or {}).get(x["name"], ""),
                      "triggers": lora_triggers(x["path"]) if not x["conflict"] else [],
                      "thumb": lora_thumb(settings, x)[1]} for x in entries]
        return {"ok": True, "available": available,
                "chain": settings.lora_chain, "warnings": ["LoRA 이름이 겹칩니다: " + x["name"] for x in entries if x["conflict"]]}

    def put_loras(self, chain):
        chain, warnings = save_lora_chain(self.save_root, chain)
        return {"ok": True, "chain": chain, "warnings": warnings}

    def put_keyword(self, body):
        # LoRA 예약어(09-30) - 프롬프트에 lora:예약어:강도 로 적어 켠다. 빈 값이면 지운다.
        name, keyword = str(body.get("name") or ""), str(body.get("keyword") or "").strip()
        try:
            keywords = set_lora_keyword(self.save_root, name, keyword)
        except ProfileError as exc:
            if exc.code == "LORA_KEYWORD_TAKEN":
                raise ManagedEngineError(exc.code, f"'{keyword}' 은(는) 이미 다른 LoRA 의 예약어입니다: {exc.field}") from None
            if exc.code == "LORA_KEYWORD_INVALID":
                raise ManagedEngineError(exc.code, "예약어는 글자 · 숫자 · _ . - 로 48자까지 적어 주세요(공백 · 쉼표 · 콜론 · 괄호 없이).") from None
            raise
        return {"ok": True, "name": name, "keyword": keywords.get(name, "")}

    def read_thumb(self, name):
        return read_lora_thumb(load_settings(self.save_root), name)

    def put_thumb(self, name, data):
        return {"ok": True, "thumb": put_lora_thumb(load_settings(self.save_root), name, data)}

    def delete_thumb(self, name):
        delete_lora_thumb(load_settings(self.save_root), name)
        return {"ok": True}

    def history_candidates(self, name):
        # PNG 칸의 [히스토리] - 이 세션의 생성 히스토리(결과 저장소)에서 고른다. 저장소가 없는 판이면 빈 목록.
        store = getattr(self.context, "result_store", None)
        return {"ok": True, "candidates": store.lora_candidates(name) if store is not None else []}

    def thumb_from_history(self, body):
        # 고른 히스토리 그림을 PNG(768 안쪽)로 줄여 PNG 넣기와 같은 자리에 쓴다(put_lora_thumb 가 다시 검사한다)
        store = getattr(self.context, "result_store", None)
        item = store.get_item(str(body.get("history_id") or "")) if store is not None else None
        if item is None or getattr(item, "image", None) is None:
            raise ManagedEngineError("HISTORY_NOT_FOUND", "히스토리에서 그 그림이 사라졌습니다 - 다시 고르세요.")
        return self.put_thumb(str(body.get("name") or ""), png_from_image(item.image))

    def open_lora_folder(self, body):
        folder = lora_folder(load_settings(self.save_root), body.get("name"))
        os.startfile(str(folder))
        return {"ok": True, "path": str(folder)}

    # ---- PARAMS Model 줄 [Manage](사용자 지정 09-30) — 모델 폴더 열기 · 내장 ComfyUI 새로고침으로 모델 갱신 ----

    def models(self):
        """지금 고를 수 있는 모델 · 뺀 파일 · 모델 폴더(ComfyUI 가 찾는 차례). 훑기만 한다(엔진은 안 묻는다)."""
        settings = load_settings(self.save_root)
        catalog = unet_catalog(settings)
        return {"ok": True, "models": [x["name"] for x in catalog["available"]], "skipped": catalog["skipped"],
                "folders": unet_folders(settings)}

    def refresh_models(self, body=None, *, may_restart=False):
        """[새로고침] — 폴더를 다시 훑고, 엔진이 켜져 있으면 내장 ComfyUI 에게도 목록을 다시 읽힌다(engine_unet_names).
        엔진을 켜지는 않는다 — 꺼져 있으면 다음 생성이 켤 때 새 목록을 읽는다. 그래도 엔진이 못 본 모델이 있으면(켠 뒤 폴더
        설정이 바뀌었다 등) 이 PC 에서 · 쉬고 있을 때만 엔진을 내린다(may_restart) — 다음 생성이 새 목록으로 켠다.
        새로 찾음 · 사라짐의 기준 = 화면의 Model 칸에 지금 보이는 목록(body.known). 없으면 훑기 전 캐시 — 하위 폴더를
        만들면 윗 폴더 시각이 바뀌어 캐시가 이미 새 파일을 담으므로 기준으로는 화면 목록이 맞다."""
        settings = load_settings(self.save_root)
        known = (body or {}).get("known")
        if isinstance(known, list):
            before = {str(name) for name in known[:4096] if isinstance(name, str)}
        else:
            before = {x["name"] for x in unet_catalog(settings)["available"]}
        forget_unet_catalog()
        catalog = unet_catalog(settings)
        names = [x["name"] for x in catalog["available"]]
        engine = {"state": "stopped", "checked": False, "missing": [], "restarted": False}
        with REGISTRY_LOCK:
            rt = REGISTRY.get(str(Path(settings.engine_root).resolve())) if settings.engine_root else None
        if rt is not None and rt.status()["state"] == "running":
            engine["state"] = "running"
            try:
                listed = engine_unet_names(rt.url)
                engine["checked"] = True
                engine["missing"] = [name for name in names if name not in listed]
            except Exception as exc:          # 묻지 못했다 - 목록은 그대로 돌려주고 까닭만 싣는다
                engine["error"] = f"{type(exc).__name__}: {exc}"
            if engine["missing"] and may_restart and not rt.queue_busy():
                rt.stop()
                engine["restarted"] = True
        return {"ok": True, "models": names, "added": [name for name in names if name not in before],
                "removed": sorted(before - set(names)), "skipped": catalog["skipped"],
                "folders": unet_folders(settings), "engine": engine}

    def open_model_folder(self, body):
        """모델 폴더를 탐색기로 — 화면이 보낸 번호(models 의 folders 차례)만 받는다(경로를 받지 않는다)."""
        folders = unet_folders(load_settings(self.save_root))
        index = int(body.get("index", 0))
        if not 0 <= index < len(folders):
            raise ProfileError("PARAM_OUT_OF_RANGE", field="index")
        folder = folders[index]
        if not folder["exists"]:
            raise ManagedEngineError("PATH_INVALID", "모델 폴더가 없습니다: " + folder["path"])
        os.startfile(folder["path"])
        return {"ok": True, "path": folder["path"]}


def licenses_payload():
    return {"ok": True, "bundle_sha256": license_bundle(),
            "items": [{**{k: x[k] for k in ("id", "title", "applies_to", "license", "source_url", "sha256")},
                       "text_url": "/api/anima-engine/licenses/" + x["id"]} for x in manifest.LICENSES],
            "notices": manifest.ATTRIBUTION_NOTICES}
