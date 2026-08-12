"""Focused tests for the Cloudflare deployment harness."""

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "deploy_cf.py"
_SPEC = importlib.util.spec_from_file_location("deploy_cf", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
deploy_cf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(deploy_cf)


def test_wrangler_env_maps_dev_token_without_leaking_source_alias() -> None:
    source = {
        "PATH": "test-path",
        "CF_DEV_TOKEN": "dev-token-value",
    }

    result = deploy_cf._wrangler_env(source)

    assert result["CLOUDFLARE_API_TOKEN"] == "dev-token-value"
    assert "CF_DEV_TOKEN" not in result
    assert source == {
        "PATH": "test-path",
        "CF_DEV_TOKEN": "dev-token-value",
    }


def test_wrangler_env_preserves_explicit_api_token() -> None:
    result = deploy_cf._wrangler_env(
        {
            "CLOUDFLARE_API_TOKEN": "explicit-token",
            "CF_DEV_TOKEN": "fallback-token",
        }
    )

    assert result["CLOUDFLARE_API_TOKEN"] == "explicit-token"
    assert "CF_DEV_TOKEN" not in result


def test_run_wrangler_passes_mapped_env_without_printing_token(capsys) -> None:
    with (
        patch.dict(
            deploy_cf.os.environ,
            {"CF_DEV_TOKEN": "secret-token"},
            clear=True,
        ),
        patch.object(deploy_cf.subprocess, "run") as run,
    ):
        deploy_cf._run_wrangler(["deploy"], dry=False)

    assert run.call_args.kwargs["env"]["CLOUDFLARE_API_TOKEN"] == "secret-token"
    output = capsys.readouterr().out
    assert "secret-token" not in output


def test_wait_ready_passes_mapped_env_to_containers_list(monkeypatch) -> None:
    monkeypatch.setenv("CF_DEV_TOKEN", "secret-token")
    run = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["bunx", "wrangler", "containers", "list"],
            returncode=0,
            stdout=json.dumps([{"name": "mnemo", "state": "ready", "instances": 1}]),
        )
    )
    monkeypatch.setattr(deploy_cf.subprocess, "run", run)

    deploy_cf._wait_ready("mnemo", dry=False, timeout_s=1)

    assert run.call_args.kwargs["env"]["CLOUDFLARE_API_TOKEN"] == "secret-token"
    assert "CF_DEV_TOKEN" not in run.call_args.kwargs["env"]
    assert run.call_args.args[0][-1] == "--json"


def test_wait_ready_does_not_accept_degraded_container(monkeypatch, capsys) -> None:
    monkeypatch.setenv("CF_DEV_TOKEN", "secret-token")
    run = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["bunx", "wrangler", "containers", "list", "--json"],
            returncode=0,
            stdout=json.dumps([{"name": "mnemo", "state": "degraded", "instances": 1}]),
        )
    )
    monkeypatch.setattr(deploy_cf.subprocess, "run", run)
    monkeypatch.setattr(deploy_cf.time, "monotonic", MagicMock(side_effect=[0, 0, 2]))
    monkeypatch.setattr(deploy_cf.time, "sleep", MagicMock())

    assert deploy_cf._wait_ready("mnemo", dry=False, timeout_s=1) is False

    output = capsys.readouterr().out
    assert "degraded" in output
    assert "WARNING" in output


def test_deploy_template_keeps_basic_instance_type() -> None:
    template = (
        _SCRIPT_PATH.parent.parent / "wrangler.deploy.template.jsonc"
    ).read_text(encoding="utf-8")

    assert '"instance_type": "basic"' in template
    assert '"instance_type": "standard-1"' not in template


def test_main_routes_push_and_deploy_through_wrangler_runner(monkeypatch) -> None:
    cfg = {
        "name": "mnemo",
        "containers": [
            {"image": "registry.cloudflare.com/0123456789abcdef/mnemo:previous"}
        ],
        "vars": {"PUBLIC_URL": "https://mnemo.example"},
    }
    run = MagicMock()
    wrangler = MagicMock()
    wait_ready = MagicMock()

    monkeypatch.setenv("CF_DEV_TOKEN", "secret-token")
    monkeypatch.setattr(deploy_cf, "_load_deploy_config", lambda repo: cfg)
    monkeypatch.setattr(deploy_cf, "_run", run)
    monkeypatch.setattr(deploy_cf, "_run_wrangler", wrangler)
    monkeypatch.setattr(deploy_cf, "_wait_ready", wait_ready)
    monkeypatch.setattr(deploy_cf, "_set_image_tag", MagicMock())

    assert deploy_cf.main(["--skip-build", "--no-canary", "--tag", "b-test"]) == 0

    assert wrangler.call_args_list == [
        call(
            [
                "containers",
                "push",
                "registry.cloudflare.com/0123456789abcdef/mnemo:b-test",
            ],
            dry=False,
            cwd=deploy_cf.Path(__file__).resolve().parent.parent,
        ),
        call(
            ["deploy", "--config", deploy_cf.DEPLOY_CONFIG],
            dry=False,
            cwd=deploy_cf.Path(__file__).resolve().parent.parent,
        ),
    ]
    wait_ready.assert_called_once_with(
        "mnemo", dry=False, timeout_s=deploy_cf.DEFAULT_ROLLOUT_TIMEOUT_S
    )
    run.assert_called_once_with(
        [
            "docker",
            "tag",
            "mnemo:b-test",
            "registry.cloudflare.com/0123456789abcdef/mnemo:b-test",
        ],
        dry=False,
    )


def test_main_loads_built_image_before_tagging(monkeypatch) -> None:
    cfg = {
        "name": "mnemo",
        "containers": [
            {"image": "registry.cloudflare.com/0123456789abcdef/mnemo:previous"}
        ],
        "vars": {"PUBLIC_URL": "https://mnemo.example"},
    }
    run = MagicMock()
    wrangler = MagicMock()
    wait_ready = MagicMock()

    monkeypatch.setenv("CF_DEV_TOKEN", "secret-token")
    monkeypatch.setattr(deploy_cf, "_load_deploy_config", lambda repo: cfg)
    monkeypatch.setattr(deploy_cf, "_run", run)
    monkeypatch.setattr(deploy_cf, "_run_wrangler", wrangler)
    monkeypatch.setattr(deploy_cf, "_wait_ready", wait_ready)
    monkeypatch.setattr(deploy_cf, "_set_image_tag", MagicMock())

    assert deploy_cf.main(["--no-canary", "--tag", "b-test"]) == 0

    assert run.call_args_list[:2] == [
        call(
            [
                "docker",
                "build",
                "--load",
                "--target",
                "http",
                "--build-arg",
                "SLIM=1",
                "-t",
                "mnemo:b-test",
                ".",
            ],
            dry=False,
            cwd=deploy_cf.Path(__file__).resolve().parent.parent,
        ),
        call(
            [
                "docker",
                "tag",
                "mnemo:b-test",
                "registry.cloudflare.com/0123456789abcdef/mnemo:b-test",
            ],
            dry=False,
        ),
    ]


def test_rollback_routes_deploy_through_wrangler_runner(monkeypatch) -> None:
    set_image = MagicMock()
    wrangler = MagicMock()
    wait_ready = MagicMock()

    monkeypatch.setattr(deploy_cf, "_set_image_tag", set_image)
    monkeypatch.setattr(deploy_cf, "_run_wrangler", wrangler)
    monkeypatch.setattr(deploy_cf, "_wait_ready", wait_ready)

    deploy_cf._rollback(
        deploy_cf.Path("C:/repo"),
        "mnemo",
        "registry.cloudflare.com/0123456789abcdef/mnemo:previous",
        dry=False,
    )

    set_image.assert_called_once_with(
        deploy_cf.Path("C:/repo"),
        "registry.cloudflare.com/0123456789abcdef/mnemo:previous",
    )
    wrangler.assert_called_once_with(
        ["deploy", "--config", deploy_cf.DEPLOY_CONFIG],
        dry=False,
        cwd=deploy_cf.Path("C:/repo"),
    )
    wait_ready.assert_called_once_with("mnemo", dry=False)
