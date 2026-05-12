import sys

import keyring
from keyring.errors import PasswordDeleteError
from cryptography.fernet import Fernet


class SecureTokenManager:
    """토큰을 시스템 키링에 안전하게 암호화하여 저장하고 관리하는 클래스.

    Windows 자격 증명 관리자(또는 호환 백엔드)가 동작하지 않는 환경
    (예: VaultSvc 비활성화, Credential Manager 컴포넌트 누락, 그룹 정책
    차단, vault 손상 등)에서는 in-memory 저장으로 자동 폴백한다.
    폴백 모드에서는 토큰이 프로세스 종료와 함께 사라진다는 점을
    ``persistent`` 속성으로 노출한다.
    """

    SERVICE_NAME = "NAIA_APP"

    def __init__(self):
        self._memory_store: dict[str, str] = {}
        self.persistent: bool = True
        self.last_error: str | None = None

        try:
            self.key = self._get_or_create_key()
            self.cipher = Fernet(self.key)
        except Exception as exc:
            self.persistent = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.key = Fernet.generate_key()
            self.cipher = Fernet(self.key)
            print(
                "⚠️ 시스템 자격 증명 저장소(Windows Credential Manager 등)에 "
                "접근할 수 없어 이번 세션 한정 in-memory 모드로 전환합니다. "
                "토큰은 앱 종료 시 사라지며 다음 실행에 다시 입력해야 합니다 "
                f"(원인: {self.last_error}).",
                file=sys.stderr,
            )

    def _get_or_create_key(self) -> bytes:
        """암호화 키를 키링에서 가져오거나 새로 생성하여 저장"""
        key = keyring.get_password(self.SERVICE_NAME, "encryption_key")
        if key:
            return key.encode()

        new_key = Fernet.generate_key()
        keyring.set_password(self.SERVICE_NAME, "encryption_key", new_key.decode())
        return new_key

    def save_token(self, service_key: str, token: str):
        """토큰을 암호화하여 시스템 키링에 저장. 실패 시 in-memory 폴백."""
        if not token:
            return
        encrypted_token = self.cipher.encrypt(token.encode()).decode()

        if self.persistent:
            try:
                keyring.set_password(self.SERVICE_NAME, service_key, encrypted_token)
                print(f"✅ {service_key} 토큰을 안전하게 저장했습니다.")
                return
            except Exception as exc:
                self.persistent = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(
                    f"⚠️ {service_key} 토큰을 자격 증명 저장소에 쓰지 못해 "
                    f"이번 세션만 in-memory로 보관합니다 (원인: {self.last_error}).",
                    file=sys.stderr,
                )

        self._memory_store[service_key] = encrypted_token

    def delete_token(self, service_key: str) -> bool:
        """저장된 토큰을 삭제. 실패 시 in-memory 상태와 오류 정보를 보존."""
        if self.persistent:
            try:
                keyring.delete_password(self.SERVICE_NAME, service_key)
                self._memory_store.pop(service_key, None)
                print(f"✅ {service_key} 토큰을 삭제했습니다.")
                return True
            except PasswordDeleteError:
                self._memory_store.pop(service_key, None)
                print(f"ℹ️ {service_key} 토큰이 이미 비어 있습니다.")
                return True
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(
                    f"⚠️ {service_key} 토큰을 자격 증명 저장소에서 삭제하지 못했습니다 "
                    f"(원인: {self.last_error}).",
                    file=sys.stderr,
                )
                return False

        self._memory_store.pop(service_key, None)
        print(f"✅ {service_key} 토큰을 삭제했습니다.")
        return True

    def get_token(self, service_key: str) -> str:
        """시스템 키링에서 토큰을 복호화하여 반환. in-memory 폴백 우선 조회."""
        encrypted_token = self._memory_store.get(service_key)
        if not encrypted_token and self.persistent:
            try:
                encrypted_token = keyring.get_password(self.SERVICE_NAME, service_key)
            except Exception as exc:
                self.persistent = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                encrypted_token = None

        if encrypted_token:
            try:
                decrypted_token = self.cipher.decrypt(encrypted_token.encode()).decode()
                return decrypted_token
            except Exception:
                # 키가 변경되었거나 데이터가 손상된 경우
                return ""
        return ""
