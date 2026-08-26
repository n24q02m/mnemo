"""Contract tests for the public OCI publication sunset.

Mnemo still builds and pushes its Cloudflare image through the internal
registry, but releases must no longer publish or recommend a public image.
These tests read the checked-in workflow and metadata as users and GitHub
Actions consume them; they do not contact any registry or provider.
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC_IMAGE_REFS = (
    "docker.io/n24q02m/mnemo-mcp",
    "ghcr.io/n24q02m/mnemo-mcp",
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _job_block(workflow: str, job: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job)}:\n.*?(?=^  [A-Za-z0-9_-]+:|\Z)",
        workflow,
    )
    assert match, f"workflow job {job!r} is missing"
    return match.group(0)


def test_release_graph_has_no_public_oci_jobs_and_keeps_cf_deploy_independent():
    workflow = _read(".github/workflows/cd.yml")

    for marker in (
        "DOCKERHUB_IMAGE",
        "GHCR_IMAGE",
        "build-docker:",
        "merge-docker:",
        "docker/login-action",
        "docker/build-push-action",
        "peter-evans/dockerhub-description",
        'registryType == "oci"',
    ):
        assert marker not in workflow

    assert "packages: write" not in workflow
    assert "id-token: write" in workflow

    assert re.search(r"(?m)^  publish-pypi:\n(?:.*\n)*?    needs: release\n", workflow)
    assert re.search(
        r"(?m)^  publish-mcp-registry:\n(?:.*\n)*?    needs: \[release, publish-pypi\]\n",
        workflow,
    )
    assert re.search(
        r"(?m)^  sync-marketplace:\n(?:.*\n)*?    needs: \[release, publish-mcp-registry\]\n",
        workflow,
    )

    deploy_cf = _job_block(workflow, "deploy-cf")
    assert re.search(r"(?m)^    needs: \[release\]\n", deploy_cf)
    assert "registry.cloudflare.com" not in deploy_cf
    assert "scripts/deploy_cf.py" in deploy_cf
    assert "docker/setup-buildx-action" in deploy_cf
    assert "docker/login-action" not in deploy_cf


def test_registry_metadata_publishes_only_the_pypi_package():
    server = json.loads(_read("server.json"))
    packages = server["packages"]

    assert [package["registryType"] for package in packages] == ["pypi"]
    assert packages[0]["identifier"] == "mnemo-mcp"
    assert all(package.get("runtimeHint") == "uvx" for package in packages)


def test_public_docs_drop_image_aliases_but_keep_source_and_cf_paths():
    readme = _read("README.md")
    passport = _read("docs/passport.md")
    wrangler = _read("wrangler.jsonc")
    worker = _read("src/worker.ts")
    agents = _read("AGENTS.md")
    claude = _read("CLAUDE.md")
    contributing = _read("CONTRIBUTING.md")

    for text in (readme, passport, wrangler, worker, agents, claude, contributing):
        assert all(reference not in text for reference in PUBLIC_IMAGE_REFS)

    assert "[![Docker]" not in readme
    assert "Public OCI image publication is discontinued" in readme
    assert "Existing historical registry tags" in readme
    assert "docker build --target http -t mnemo-mcp:local ." in readme
    assert "wrangler containers push mnemo-mcp:local" in readme
    assert "docker build --target http -t mnemo-mcp:local ." in passport
    assert "mnemo-mcp:local --http" in passport

    assert "registry.cloudflare.com/<YOUR_ACCOUNT_ID>/mnemo-mcp:local" in wrangler
    assert re.search(r"registry\.cloudflare\.com", worker)
    expected_release_claim = (
        "PyPI + GitHub Release; eligible stable releases -> MCP Registry + marketplace"
    )
    assert expected_release_claim in agents
    assert expected_release_claim in claude
    assert "Builds and pushes the Cloudflare internal image" in contributing
