"""Compose offline profile: vLLM services, pins, and env interpolation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

COMPOSE_PATH = Path("/repo/docker-compose.yml")
OFFLINE_ENV_PATH = Path("/env/.env.offline.example")
PINNED_IMAGE = "vllm/vllm-openai:v0.31.0"
VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _load_compose() -> dict:
    assert COMPOSE_PATH.is_file(), f"missing {COMPOSE_PATH}"
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0])
    return keys


def _command_text(service: dict) -> str:
    command = service["command"]
    assert isinstance(command, str), "vLLM command must be string-form, not a list"
    return command


def test_offline_vllm_services_profile_image_and_served_names() -> None:
    compose = _load_compose()
    services = compose["services"]
    for name in ("vllm-llm", "vllm-embed"):
        assert name in services, f"missing service {name}"
        service = services[name]
        assert service.get("profiles") == ["offline"]
        assert service["image"] == PINNED_IMAGE
        assert "latest" not in service["image"]
        assert "<" not in service["image"]

    llm_cmd = _command_text(services["vllm-llm"])
    embed_cmd = _command_text(services["vllm-embed"])
    assert "--served-model-name ${SELECTION_MODEL}" in llm_cmd
    assert "--served-model-name ${EMBEDDING_MODEL}" in embed_cmd
    assert "--max-model-len ${LLM_MAX_MODEL_LEN}" in llm_cmd


def test_offline_vllm_healthcheck_gpu_and_cache_volume() -> None:
    compose = _load_compose()
    services = compose["services"]
    volumes = compose.get("volumes") or {}
    assert "hf-cache" in volumes

    for name in ("vllm-llm", "vllm-embed"):
        service = services[name]
        health = service["healthcheck"]
        test = health["test"]
        test_text = " ".join(test) if isinstance(test, list) else str(test)
        assert "python" in test_text.lower()
        assert "urllib" in test_text or "urlopen" in test_text
        assert "/health" in test_text
        start = str(health.get("start_period", ""))
        assert start.endswith("s")
        assert int(start[:-1]) >= 600

        devices = service["deploy"]["resources"]["reservations"]["devices"]
        assert any(
            d.get("driver") == "nvidia" and "gpu" in (d.get("capabilities") or [])
            for d in devices
        )
        mounts = service.get("volumes") or []
        assert any("hf-cache" in str(m) for m in mounts)


def test_backend_and_migrate_keep_env_file_and_no_vllm_dependency() -> None:
    compose = _load_compose()
    services = compose["services"]
    for name in ("backend", "migrate"):
        env_file = services[name]["env_file"]
        if isinstance(env_file, list):
            assert "${ENV_FILE:-.env}" in env_file
        else:
            assert env_file == "${ENV_FILE:-.env}"

    depends = services["backend"].get("depends_on") or {}
    if isinstance(depends, dict):
        assert "vllm-llm" not in depends
        assert "vllm-embed" not in depends
    else:
        assert "vllm-llm" not in depends
        assert "vllm-embed" not in depends


def test_command_vars_are_in_offline_env_or_have_defaults() -> None:
    compose = _load_compose()
    assert OFFLINE_ENV_PATH.is_file(), f"missing {OFFLINE_ENV_PATH}"
    env_keys = _env_keys(OFFLINE_ENV_PATH)
    for name in ("vllm-llm", "vllm-embed"):
        command = _command_text(compose["services"][name])
        for match in VAR_PATTERN.finditer(command):
            var_name, default = match.group(1), match.group(2)
            if default is not None:
                continue
            assert var_name in env_keys, (
                f"{name} command references ${{{var_name}}} "
                f"missing from .env.offline.example and without :- default"
            )
