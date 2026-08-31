"""Unit tests for the local live-protocol child environment builder."""

import os
from pathlib import Path

from test_live_protocol import (
    _KNOWN_PROVIDER_ENV_KEYS,
    _PROCESS_ENV_KEYS,
    _build_local_replay_env,
)


def test_replay_env_retains_only_process_launch_essentials(monkeypatch, tmp_path):
    expected = {name: f"essential-{name.lower()}" for name in _PROCESS_ENV_KEYS}
    for name, value in expected.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("UNEXPECTED_PARENT_SECRET", "must-not-propagate")

    env = _build_local_replay_env(
        tmp_path,
        cache_dir=tmp_path / "model-cache",
    )

    assert {name: env[name] for name in _PROCESS_ENV_KEYS} == expected
    assert "UNEXPECTED_PARENT_SECRET" not in env
    assert set(env) <= set(_PROCESS_ENV_KEYS) | set(_KNOWN_PROVIDER_ENV_KEYS) | {
        "DB_PATH",
        "MNEMO_DB_PATH",
        "LOG_LEVEL",
        "SYNC_ENABLED",
        "MCP_TRANSPORT",
        "MEMORY_DB_BACKEND",
        "MNEMO_DATA_DIR",
        "HOME",
        "USERPROFILE",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "LOCALAPPDATA",
        "APPDATA",
        "TMP",
        "TEMP",
        "TMPDIR",
        "FASTRETRIEVAL_CACHE_PATH",
        "QWEN3_EMBED_CACHE_PATH",
        "EMBEDDING_DIMS",
        "RERANK_ENABLED",
        "DISABLE_LOCAL_EMBED",
        "DISABLE_LOCAL_RERANK",
    }
    assert env["DB_PATH"] == env["MNEMO_DB_PATH"]


def test_replay_env_empties_known_provider_values(monkeypatch, tmp_path):
    for name in _KNOWN_PROVIDER_ENV_KEYS:
        monkeypatch.setenv(name, f"parent-{name.lower()}")

    env = _build_local_replay_env(tmp_path, cache_dir=tmp_path / "cache")

    assert all(env[name] == "" for name in _KNOWN_PROVIDER_ENV_KEYS)


def test_replay_env_forces_temporary_local_offline_boundary(tmp_path):
    root = tmp_path.resolve()
    env = _build_local_replay_env(tmp_path, cache_dir=tmp_path / "cache")

    assert env["DB_PATH"] == str(root / "local-test.db")
    for name in (
        "HOME",
        "USERPROFILE",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "LOCALAPPDATA",
        "APPDATA",
        "TMP",
        "TEMP",
        "TMPDIR",
    ):
        assert Path(env[name]).is_relative_to(root)
    assert env["SYNC_ENABLED"] == "false"
    assert env["MEMORY_DB_BACKEND"] == "sqlite"
    assert env["EMBEDDING_MODELS"] == ""
    assert env["RERANK_MODELS"] == ""
    assert env["LLM_MODELS"] == ""
    assert env["EMBEDDING_BACKEND"] == ""
    assert env["RERANK_BACKEND"] == ""
    assert env["DISABLE_LOCAL_EMBED"] == "false"
    assert env["DISABLE_LOCAL_RERANK"] == "false"


def test_replay_env_does_not_mutate_caller_environment(tmp_path):
    before = dict(os.environ)

    _build_local_replay_env(tmp_path, cache_dir=tmp_path / "cache")

    assert dict(os.environ) == before
