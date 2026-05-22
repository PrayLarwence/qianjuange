"""api_key 透明加解密 + 配置往返测试."""
from __future__ import annotations

import json
import sys

import pytest


# ─── secret 模块本体 ───

def test_encrypt_empty_returns_empty():
    from app.providers.secret import encrypt, decrypt
    assert encrypt("") == ""
    assert decrypt("") == ""


def test_roundtrip_short_and_long():
    from app.providers.secret import encrypt, decrypt
    for plain in ["sk-abc", "x" * 4096, "中文带 emoji 🦊", "包含 $ 和 = 的混淆 abc=def$ghi"]:
        token = encrypt(plain)
        assert token != plain  # 至少加了 scheme 前缀
        assert decrypt(token) == plain


def test_idempotent_encrypt():
    from app.providers.secret import encrypt
    once = encrypt("sk-abc")
    twice = encrypt(once)
    assert once == twice


def test_decrypt_passthrough_for_legacy_plain():
    """老配置里直接是明文 'sk-...', decrypt 应原样返回, 不能洗白."""
    from app.providers.secret import decrypt
    assert decrypt("sk-legacy-plain-key") == "sk-legacy-plain-key"


def test_is_encrypted_detection():
    from app.providers.secret import encrypt, is_encrypted
    assert is_encrypted("sk-plain") is False
    assert is_encrypted("") is False
    assert is_encrypted(encrypt("sk-x")) is True


def test_garbage_token_does_not_crash():
    from app.providers.secret import decrypt
    # 假冒 scheme 但 base64 烂掉
    assert decrypt("dpapi$@@@not-base64@@@") in ("", "dpapi$@@@not-base64@@@")


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI 仅 Windows")
def test_uses_dpapi_scheme_on_windows():
    from app.providers.secret import encrypt
    token = encrypt("sk-windows")
    assert token.startswith("dpapi$")


@pytest.mark.skipif(sys.platform == "win32", reason="非 Windows 才走 plain 占位")
def test_uses_plain_scheme_off_windows():
    from app.providers.secret import encrypt
    token = encrypt("sk-other")
    assert token.startswith("plain$")


# ─── config.py 集成 ───

def test_save_then_load_keeps_plaintext_in_memory(tmp_path, monkeypatch):
    """save_config 写完, load_config 读出来内存里仍是明文 (provider 直接用得到)."""
    from app.providers import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llm.json")

    cfg_mod.save_config({
        "active": "claude",
        "providers": {"claude": {"api_key": "sk-secret-123", "model": "claude-opus-4-1"}},
    })
    loaded = cfg_mod.load_config()
    assert loaded["providers"]["claude"]["api_key"] == "sk-secret-123"


def test_disk_payload_does_not_contain_plaintext(tmp_path, monkeypatch):
    """落盘文件里不能出现原始 api_key 字符串."""
    from app.providers import config as cfg_mod
    path = tmp_path / "llm.json"
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", path)

    cfg_mod.save_config({
        "active": "openai",
        "providers": {"openai": {"api_key": "sk-VERY-SECRET-XYZ"}},
    })
    raw = path.read_text(encoding="utf-8")
    assert "sk-VERY-SECRET-XYZ" not in raw
    on_disk = json.loads(raw)
    stored = on_disk["providers"]["openai"]["api_key"]
    assert stored.startswith(("dpapi$", "plain$"))


def test_legacy_plaintext_file_still_loads(tmp_path, monkeypatch):
    """老用户的 llm_config.json 里直接是明文 api_key, 升级后 load 不能洗白."""
    from app.providers import config as cfg_mod
    path = tmp_path / "llm.json"
    path.write_text(json.dumps({
        "active": "deepseek",
        "providers": {"deepseek": {"api_key": "sk-legacy-x", "model": "deepseek-chat", "base_url": ""}},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", path)

    loaded = cfg_mod.load_config()
    assert loaded["providers"]["deepseek"]["api_key"] == "sk-legacy-x"


def test_legacy_plaintext_migrates_to_ciphertext_on_next_save(tmp_path, monkeypatch):
    """老明文 → 任意 save_config 调用后, 文件应当变成密文 (即使本次没改 key)."""
    from app.providers import config as cfg_mod
    path = tmp_path / "llm.json"
    path.write_text(json.dumps({
        "active": "deepseek",
        "providers": {"deepseek": {"api_key": "sk-needs-migrate", "model": "deepseek-chat", "base_url": ""}},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", path)

    # 不改 api_key, 只改 active
    cfg_mod.save_config({"active": "deepseek"})
    raw = path.read_text(encoding="utf-8")
    assert "sk-needs-migrate" not in raw
    assert json.loads(raw)["providers"]["deepseek"]["api_key"].startswith(("dpapi$", "plain$"))


def test_save_config_ignores_masked_api_key(tmp_path, monkeypatch):
    """前端把 mask 后的 '***' 回传时不能覆盖真实 key."""
    from app.providers import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llm.json")
    cfg_mod.save_config({"providers": {"claude": {"api_key": "sk-real-key"}}})
    cfg_mod.save_config({"providers": {"claude": {"api_key": "***"}}})
    assert cfg_mod.load_config()["providers"]["claude"]["api_key"] == "sk-real-key"


def test_mask_strips_api_key_for_response(tmp_path, monkeypatch):
    """mask 输出永远不带 api_key (只暴露 preview + has_key)."""
    from app.providers import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llm.json")
    cfg_mod.save_config({"providers": {"openai": {"api_key": "sk-abcdefghij1234567890"}}})

    masked = cfg_mod.mask(cfg_mod.load_config())
    p = masked["providers"]["openai"]
    assert "api_key" not in p
    assert p["has_key"] is True
    assert p["api_key_preview"]
    assert "sk-abcdefghij1234567890" not in json.dumps(masked)
