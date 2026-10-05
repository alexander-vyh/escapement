"""Deployment must prove installed OMP behavior, including both guard controls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "scripts/omp-plugin-update.sh"
VERIFIER = ROOT / "scripts/verify_omp_plugin.py"


def package_copy(destination: Path) -> Path:
    destination.mkdir(parents=True)
    shutil.copy2(ROOT / "package.json", destination / "package.json")
    for relative in ("plugins/escapement-pi", ".agents/skills"):
        shutil.copytree(ROOT / relative, destination / relative)
    return destination


@pytest.fixture
def installation(tmp_path):
    plugins = tmp_path / "home/.omp/plugins"
    plugins.mkdir(parents=True)
    spec = {"name": "omp-plugins", "private": True, "dependencies": {
        "escapement": "github:alexander-vyh/escapement", "another-plugin": "^2.0.0",
    }}
    settings = {"plugins": {"escapement": {
        "version": "0.1.0", "enabled": False, "enabledFeatures": None,
    }, "another-plugin": {"enabled": True}}, "settings": {"custom": "keep"}}
    (plugins / "package.json").write_text(json.dumps(spec))
    (plugins / "omp-plugins.lock.json").write_text(json.dumps(settings))
    (plugins / "bun.lock").write_text("old-revision\n")
    unrelated = plugins / "node_modules/another-plugin/private-data.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("User plugin data must survive.\n")
    package = package_copy(plugins / "node_modules/escapement")
    (package / "plugins/escapement-pi/extensions/payloads.ts").write_text("// stale adapter\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    omp = bin_dir / "omp"
    omp.write_text("""#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
assert sys.argv[1:] == ['plugin', 'upgrade', 'escapement'], sys.argv
root = pathlib.Path(os.environ['OMP_PLUGIN_DIR'])
mode = os.environ.get('UPGRADE_MODE', 'replace')
if mode == 'fail':
    raise SystemExit(23)
if mode != 'no-op':
    destination = root / 'node_modules/escapement'
    shutil.rmtree(destination)
    shutil.copytree(os.environ['EXPECTED_PACKAGE'], destination)
    (root / 'bun.lock').write_text('new-revision\\n')
if mode == 'mutate-config':
    (root / 'omp-plugins.lock.json').write_text('{}')
if mode == 'new-version':
    runtime = json.loads((root / 'omp-plugins.lock.json').read_text())
    runtime['plugins']['escapement']['version'] = '0.2.0'
    (root / 'omp-plugins.lock.json').write_text(json.dumps(runtime))
if mode == 'delete-unrelated':
    shutil.rmtree(root / 'node_modules/another-plugin')
""")
    omp.chmod(0o755)
    expected = package_copy(tmp_path / "expected")
    env = dict(os.environ, HOME=str(tmp_path / "home"), OMP_BIN=str(omp),
               OMP_PLUGIN_DIR=str(plugins), EXPECTED_PACKAGE=str(expected))
    return plugins, package, env, spec, settings


def update(env, source=ROOT):
    return subprocess.run(["bash", str(UPDATER), "--source", str(source)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=90)


def verify(plugins, source=ROOT):
    return subprocess.run(["python3", str(VERIFIER), "--source", str(source),
                           "--plugins-dir", str(plugins)], cwd=ROOT,
                          capture_output=True, text=True, timeout=90)


def test_refresh_repairs_installed_bytes_and_preserves_rolling_source_and_settings(installation):
    plugins, package, env, spec, settings = installation
    result = update(env)
    assert result.returncode == 0, result.stdout + result.stderr
    relative = "plugins/escapement-pi/extensions/payloads.ts"
    assert (package / relative).read_bytes() == (ROOT / relative).read_bytes()
    assert json.loads((plugins / "package.json").read_text()) == spec
    assert json.loads((plugins / "omp-plugins.lock.json").read_text()) == settings
    assert (plugins / "bun.lock").read_text() == "new-revision\n"
    assert (plugins / "node_modules/another-plugin/private-data.txt").read_text() == "User plugin data must survive.\n"
    proof = verify(plugins)
    assert proof.returncode == 0, proof.stdout + proof.stderr
    assert "xd://github" in proof.stdout and "root" in proof.stdout
    assert "xd://mcp__serena_initial_instructions" in proof.stdout
    assert "xd://report_issue" in proof.stdout and "linked" in proof.stdout


def test_second_deployment_advances_installed_plugin_without_pinning_source(installation, tmp_path):
    plugins, package, env, spec, settings = installation
    assert update(env).returncode == 0
    next_source = package_copy(tmp_path / "next-release")
    relative = "plugins/escapement-pi/PI.md"
    (next_source / relative).write_text((next_source / relative).read_text() + "\nNew released instructions.\n")
    result = update(dict(env, EXPECTED_PACKAGE=str(next_source)), next_source)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (package / relative).read_bytes() == (next_source / relative).read_bytes()
    assert json.loads((plugins / "package.json").read_text()) == spec
    assert json.loads((plugins / "omp-plugins.lock.json").read_text()) == settings


def test_legitimate_runtime_version_update_preserves_settings(installation):
    plugins, _, env, _, settings = installation
    result = update(dict(env, UPGRADE_MODE="new-version"))
    assert result.returncode == 0, result.stdout + result.stderr
    settings["plugins"]["escapement"]["version"] = "0.2.0"
    assert json.loads((plugins / "omp-plugins.lock.json").read_text()) == settings


@pytest.mark.parametrize("mode", ["no-op", "fail", "mutate-config", "delete-unrelated"])
def test_failed_stale_or_config_changing_upgrade_cannot_report_success(installation, mode):
    _, _, env, _, _ = installation
    result = update(dict(env, UPGRADE_MODE=mode))
    assert result.returncode != 0, result.stdout + result.stderr
    assert "OK:" not in result.stdout
    assert "FATAL:" in result.stderr


@pytest.mark.parametrize("damage", ["missing-package", "missing-cli", "unregistered", "invalid-manifest"])
def test_present_broken_omp_installation_fails_closed(installation, damage):
    plugins, package, env, _, _ = installation
    if damage == "missing-package":
        shutil.rmtree(package)
    elif damage == "missing-cli":
        env["OMP_BIN"] = str(plugins / "no-such-omp")
    elif damage == "unregistered":
        (plugins / "package.json").write_text('{}')
    else:
        (plugins / "package.json").write_text('{')
    result = update(env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "SKIP" not in result.stdout
    assert "FATAL:" in result.stderr


def test_truly_absent_omp_is_explicitly_skipped(installation):
    plugins, _, env, _, _ = installation
    shutil.rmtree(plugins.parent)
    result = update(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SKIP" in result.stdout and "OMP" in result.stdout


def test_verifier_rejects_stale_bytes_even_with_same_package_version(installation):
    plugins, _, _, _, _ = installation
    result = verify(plugins)
    assert result.returncode != 0
    assert "payloads.ts" in result.stdout + result.stderr


@pytest.mark.parametrize("mutant", ["all-files-virtual", "virtual-files-ordinary"])
def test_installed_runtime_probe_rejects_bad_mapping_even_when_bytes_match(installation, mutant, tmp_path):
    plugins, package, _, _, _ = installation
    shutil.rmtree(package)
    package_copy(package)
    source = package_copy(tmp_path / "mutant-source")
    for root in (source, package):
        payloads = root / "plugins/escapement-pi/extensions/payloads.ts"
        text = payloads.read_text()
        assert "URI_SCHEME.test(path)" in text
        payloads.write_text(text.replace("URI_SCHEME.test(path)",
                                        "true" if mutant == "all-files-virtual" else "false"))
    result = verify(plugins, source)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "runtime" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize("missing", ["extensions/index.ts", "claude/hooks/root_checkout_guard.py", "gates.json"])
def test_verifier_rejects_incomplete_installed_plugin(installation, missing):
    plugins, package, env, _, _ = installation
    assert update(env).returncode == 0
    (package / "plugins/escapement-pi" / missing).unlink()
    assert verify(plugins).returncode != 0


def test_declared_deploy_runs_all_three_hosts(tmp_path):
    surface = json.loads((ROOT / ".escapement/repo.json").read_text())["deploy"]["surface"]
    assert surface == "scripts/deploy-plugins.sh"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    wrapper = ROOT / surface
    shutil.copy2(wrapper, scripts / wrapper.name)
    record = tmp_path / "hosts"
    for name in ("plugin-update.sh", "codex-plugin-update.sh", "omp-plugin-update.sh"):
        (scripts / name).write_text(f'#!/bin/bash\necho "{name}" >> "$HOST_RECORD"\n')
    result = subprocess.run(["bash", str(scripts / wrapper.name)],
                            env=dict(os.environ, HOST_RECORD=str(record)), capture_output=True)
    assert result.returncode == 0, result.stderr
    assert record.read_text().splitlines() == [
        "plugin-update.sh", "codex-plugin-update.sh", "omp-plugin-update.sh",
    ]


@pytest.mark.parametrize("failed_host", ["plugin-update.sh", "codex-plugin-update.sh", "omp-plugin-update.sh"])
def test_declared_deploy_propagates_host_failure(tmp_path, failed_host):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(ROOT / "scripts/deploy-plugins.sh", scripts / "deploy-plugins.sh")
    for name in ("plugin-update.sh", "codex-plugin-update.sh", "omp-plugin-update.sh"):
        code = 17 if name == failed_host else 0
        (scripts / name).write_text(f'#!/bin/bash\nexit {code}\n')
    result = subprocess.run(["bash", str(scripts / "deploy-plugins.sh")], capture_output=True)
    assert result.returncode == 17, result.stderr
