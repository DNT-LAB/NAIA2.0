from cryptography.fernet import Fernet

import core.secure_token_manager as secure_token_manager
from core.secure_token_manager import SecureTokenManager


def test_secure_token_manager_uses_memory_store_when_keyring_init_fails(monkeypatch, capsys):
    class FailingKeyring:
        def get_password(self, _service, _key):
            raise RuntimeError("vault down")

        def set_password(self, _service, _key, _value):
            raise AssertionError("set_password should not be called")

        def delete_password(self, _service, _key):
            raise AssertionError("delete_password should not be called")

    monkeypatch.setattr(secure_token_manager, "keyring", FailingKeyring())

    manager = SecureTokenManager()
    manager.save_token("nai_token", "secret")

    assert manager.persistent is False
    assert "vault down" in manager.last_error
    assert manager.get_token("nai_token") == "secret"
    assert "in-memory" in capsys.readouterr().err

    assert manager.delete_token("nai_token") is True

    assert manager.get_token("nai_token") == ""


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

        def delete_password(self, _service, _key):
            raise AssertionError("delete_password should not be called after fallback")

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


def test_secure_token_manager_deletes_persistent_token(monkeypatch):
    class Keyring:
        def __init__(self):
            self.key = Fernet.generate_key().decode()
            self.values = {"encryption_key": self.key}
            self.deleted = []

        def get_password(self, _service, key):
            return self.values.get(key)

        def set_password(self, _service, key, value):
            self.values[key] = value

        def delete_password(self, _service, key):
            self.deleted.append(key)
            self.values.pop(key, None)

    keyring = Keyring()
    monkeypatch.setattr(secure_token_manager, "keyring", keyring)
    manager = SecureTokenManager()

    manager.save_token("nai_token", "secret")
    assert manager.get_token("nai_token") == "secret"

    assert manager.delete_token("nai_token") is True

    assert manager.get_token("nai_token") == ""
    assert keyring.deleted == ["nai_token"]


def test_secure_token_manager_preserves_persistent_token_on_delete_failure(monkeypatch):
    class DeleteFailingKeyring:
        def __init__(self):
            self.key = Fernet.generate_key().decode()
            self.values = {"encryption_key": self.key}

        def get_password(self, _service, key):
            return self.values.get(key)

        def set_password(self, _service, key, value):
            self.values[key] = value

        def delete_password(self, _service, _key):
            raise RuntimeError("delete blocked")

    keyring = DeleteFailingKeyring()
    monkeypatch.setattr(secure_token_manager, "keyring", keyring)
    manager = SecureTokenManager()

    manager.save_token("nai_token", "secret")

    assert manager.delete_token("nai_token") is False
    assert manager.persistent is True
    assert "delete blocked" in manager.last_error
    assert manager.get_token("nai_token") == "secret"
