from cryptography.fernet import Fernet

import core.secure_token_manager as secure_token_manager
from core.secure_token_manager import SecureTokenManager


def test_secure_token_manager_uses_memory_store_when_keyring_init_fails(monkeypatch, capsys):
    class FailingKeyring:
        def get_password(self, _service, _key):
            raise RuntimeError("vault down")

        def set_password(self, _service, _key, _value):
            raise AssertionError("set_password should not be called")

    monkeypatch.setattr(secure_token_manager, "keyring", FailingKeyring())

    manager = SecureTokenManager()
    manager.save_token("nai_token", "secret")

    assert manager.persistent is False
    assert "vault down" in manager.last_error
    assert manager.get_token("nai_token") == "secret"
    assert "in-memory" in capsys.readouterr().err


def test_secure_token_manager_stops_keyring_writes_after_save_failure(monkeypatch):
    class WriteFailingKeyring:
        def __init__(self):
            self.key = Fernet.generate_key().decode()
            self.write_count = 0

        def get_password(self, _service, key):
            if key == "encryption_key":
                return self.key
            return None

        def set_password(self, _service, _key, _value):
            self.write_count += 1
            raise RuntimeError("write blocked")

    keyring = WriteFailingKeyring()
    monkeypatch.setattr(secure_token_manager, "keyring", keyring)
    manager = SecureTokenManager()

    manager.save_token("nai_token", "secret")
    write_count_after_failure = keyring.write_count
    manager.save_token("webui_token", "another")

    assert manager.persistent is False
    assert "write blocked" in manager.last_error
    assert manager.get_token("nai_token") == "secret"
    assert manager.get_token("webui_token") == "another"
    assert keyring.write_count == write_count_after_failure
