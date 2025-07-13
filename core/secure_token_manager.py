import keyring
from cryptography.fernet import Fernet

class SecureTokenManager:
    """토큰을 시스템 키링에 안전하게 암호화하여 저장하고 관리하는 클래스"""
    
    SERVICE_NAME = "NAIA_APP" # 키링에서 사용할 서비스 이름

    def __init__(self):
        self.key = self._get_or_create_key()
        self.cipher = Fernet(self.key)

    def _get_or_create_key(self) -> bytes:
        """암호화 키를 키링에서 가져오거나 새로 생성하여 저장"""
        key = keyring.get_password(self.SERVICE_NAME, "encryption_key")
        if key:
            return key.encode()
        
        new_key = Fernet.generate_key()
        keyring.set_password(self.SERVICE_NAME, "encryption_key", new_key.decode())
        return new_key

    def save_token(self, service_key: str, token: str):
        """토큰을 암호화하여 시스템 키링에 저장"""
        if not token:
            return
        encrypted_token = self.cipher.encrypt(token.encode())
        keyring.set_password(self.SERVICE_NAME, service_key, encrypted_token.decode())
        print(f"✅ {service_key} 토큰을 안전하게 저장했습니다.")

    def get_token(self, service_key: str) -> str:
        """시스템 키링에서 토큰을 복호화하여 반환"""
        encrypted_token = keyring.get_password(self.SERVICE_NAME, service_key)
        if encrypted_token:
            try:
                decrypted_token = self.cipher.decrypt(encrypted_token.encode()).decode()
                return decrypted_token
            except Exception:
                # 키가 변경되었거나 데이터가 손상된 경우
                return ""
        return ""