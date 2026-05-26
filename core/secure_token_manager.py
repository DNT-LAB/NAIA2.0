import json
import os
import stat
import sys
from pathlib import Path

from cryptography.fernet import Fernet


class SecureTokenManager:
    """토큰을 로컬 JSON 파일에 저장/관리하는 클래스.

    이전 구현은 OS 키링(``keyring``)을 사용했으나, macOS Keychain이 토큰을
    읽을 때마다(특히 spawn되는 파이썬 바이너리/venv가 매번 달라질 때) 로그인
    키체인 암호를 반복 요구하여 헤드리스/포터블 런타임에서 사용성이 깨졌다.
    그래서 키링을 제거하고 사용자 config 디렉터리의 단일 JSON 파일에 저장한다.

    암호화 범위: **민감한 NAI 토큰(``nai_token``)만** Fernet 암호화한다.
    WEBUI/COMFYUI는 엔드포인트 URL(``webui_url``/``comfyui_url``)이므로 평문
    (비보안)으로 저장한다.

    보안 주의: 복호화 키가 동일 파일(같은 호스트)에 함께 보관되므로 NAI 토큰
    암호화도 OS secret store 수준의 보안이 아니라 "디스크상 평문 노출
    방지(obfuscation)" 수준이다. OS secret store가 없는 로컬 단일 사용자
    데스크톱 도구의 현실적 절충이며, 파일은 POSIX에서 0600 권한으로 생성한다.

    파일 IO가 불가한 환경에서는 in-memory 저장으로 자동 폴백하고
    (``persistent=False``), 이 경우 토큰은 프로세스 종료와 함께 사라진다.
    """

    SERVICE_NAME = "NAIA_APP"
    _FILE_NAME = "secure_tokens.json"
    # 암호화는 민감한 NAI 토큰에만 적용. WEBUI/COMFYUI는 URL이라 평문 저장.
    _ENCRYPTED_KEYS = {"nai_token"}

    def __init__(self, storage_path: str | Path | None = None):
        self._memory_store: dict[str, str] = {}
        self.persistent: bool = True
        self.last_error: str | None = None
        self.storage_path: Path = (
            Path(storage_path) if storage_path else self._default_storage_path()
        )

        try:
            data = self._read_file()
            stored_key = data.get("_key")
            if stored_key:
                self.key = stored_key.encode()
            else:
                self.key = Fernet.generate_key()
                data["_key"] = self.key.decode()
                data.setdefault("tokens", {})
                self._write_file(data)
            self.cipher = Fernet(self.key)
        except Exception as exc:
            self.persistent = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.key = Fernet.generate_key()
            self.cipher = Fernet(self.key)
            print(
                "⚠️ 토큰 저장 파일에 접근할 수 없어 이번 세션 한정 in-memory 모드로 "
                "전환합니다. 토큰은 앱 종료 시 사라지며 다음 실행에 다시 입력해야 "
                f"합니다 (원인: {self.last_error}).",
                file=sys.stderr,
            )

    def _default_storage_path(self) -> Path:
        from core.runtime_paths import resolve_runtime_paths

        return resolve_runtime_paths().config_dir / self._FILE_NAME

    def _read_file(self) -> dict:
        if self.storage_path.exists():
            content = self.storage_path.read_text(encoding="utf-8")
            data = json.loads(content) if content.strip() else {}
            return data if isinstance(data, dict) else {}
        return {}

    def _write_file(self, data: dict) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage_path.with_name(self.storage_path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.storage_path)
        if os.name == "posix":
            try:
                os.chmod(self.storage_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
            except OSError:
                pass

    def _encode(self, service_key: str, token: str) -> str:
        """저장용 변환: NAI 토큰만 암호화, 그 외(URL 등)는 평문."""
        if service_key in self._ENCRYPTED_KEYS:
            return self.cipher.encrypt(token.encode()).decode()
        return token

    def _decode(self, service_key: str, stored: str) -> str:
        """조회용 역변환: NAI 토큰만 복호화, 그 외는 평문 그대로."""
        if service_key in self._ENCRYPTED_KEYS:
            try:
                return self.cipher.decrypt(stored.encode()).decode()
            except Exception:
                # 키가 변경되었거나 데이터가 손상된 경우
                return ""
        return stored

    def save_token(self, service_key: str, token: str):
        """토큰을 JSON 파일에 저장(NAI만 암호화). 실패 시 in-memory 폴백."""
        if not token:
            return
        stored_value = self._encode(service_key, token)

        if self.persistent:
            try:
                data = self._read_file()
                data.setdefault("_key", self.key.decode())
                tokens = data.setdefault("tokens", {})
                tokens[service_key] = stored_value
                self._write_file(data)
                print(f"✅ {service_key} 토큰을 저장했습니다.")
                return
            except Exception as exc:
                self.persistent = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(
                    f"⚠️ {service_key} 토큰을 파일에 쓰지 못해 이번 세션만 "
                    f"in-memory로 보관합니다 (원인: {self.last_error}).",
                    file=sys.stderr,
                )

        self._memory_store[service_key] = stored_value

    def delete_token(self, service_key: str) -> bool:
        """저장된 토큰을 삭제. 실패 시 in-memory 상태와 오류 정보를 보존."""
        if self.persistent:
            try:
                data = self._read_file()
                tokens = data.get("tokens", {})
                if isinstance(tokens, dict):
                    tokens.pop(service_key, None)
                    data["tokens"] = tokens
                    self._write_file(data)
                self._memory_store.pop(service_key, None)
                print(f"✅ {service_key} 토큰을 삭제했습니다.")
                return True
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(
                    f"⚠️ {service_key} 토큰을 삭제하지 못했습니다 "
                    f"(원인: {self.last_error}).",
                    file=sys.stderr,
                )
                return False

        self._memory_store.pop(service_key, None)
        print(f"✅ {service_key} 토큰을 삭제했습니다.")
        return True

    def get_token(self, service_key: str) -> str:
        """JSON 파일에서 토큰을 조회(NAI만 복호화). in-memory 폴백 우선 조회."""
        stored = self._memory_store.get(service_key)
        if not stored and self.persistent:
            try:
                data = self._read_file()
                tokens = data.get("tokens", {})
                stored = tokens.get(service_key) if isinstance(tokens, dict) else None
            except Exception as exc:
                self.persistent = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                stored = None

        if stored:
            return self._decode(service_key, stored)
        return ""
