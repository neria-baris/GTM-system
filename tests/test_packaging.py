"""Offline checks for the GTMTracker.exe launcher (no PyInstaller run)."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = _load("gtm_exe_launcher", "packaging/launcher.py")


@pytest.mark.parametrize("args,expected", [
    (["-B", "-m", "src.connectors.sync_cli", "--require-live"], ("module", "src.connectors.sync_cli", ["--require-live"])),
    (["-B", "scripts/build_stage_d.py"], ("path", "scripts/build_stage_d.py", [])),
    (["-B", "-X", "utf8", "scripts/x.py", "a", "-m"], ("path", "scripts/x.py", ["a", "-m"])),
    (["-c", "print(1)", "z"], ("code", "print(1)", ["z"])),
    (["-m", "pytest", "-q"], ("module", "pytest", ["-q"])),
])
def test_interpreter_shim_detection(args, expected):
    spec = launcher.parse_interpreter_args(args)
    assert (spec["mode"], spec["target"], spec["args"]) == expected


@pytest.mark.parametrize("args", [[], ["demo"], ["demo", "--port", "1"], ["check"], ["--help"], ["-B"],
                                  ["live", "--no-serve"], ["where"]])
def test_launcher_commands_are_not_shimmed(args):
    assert launcher.parse_interpreter_args(args) is None


def test_cli_subcommands():
    args = launcher.parse_cli(["demo", "--port", "8897", "--no-browser"])
    assert (args.command, args.port, args.no_browser) == ("demo", 8897, True)
    assert launcher.parse_cli([]).command is None
    live = launcher.parse_cli(["live", "--no-serve", "--port", "9000"])
    assert (live.command, live.no_serve, live.port) == ("live", True, 9000)
    for name in ("check", "serve-live", "keys", "test", "where"):
        assert launcher.parse_cli([name]).command == name


def test_shim_runs_script_and_module_with_exit_status(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "shim_probe_mod.py").write_text(
        "import sys\nif __name__ == '__main__':\n    sys.exit(len(sys.argv))\n")
    (tmp_path / "probe.py").write_text("import sys\nraise SystemExit(int(sys.argv[1]))\n")
    assert launcher.run_shim(launcher.parse_interpreter_args(["-B", "probe.py", "7"])) == 7
    assert launcher.run_shim(launcher.parse_interpreter_args(["-B", "-m", "shim_probe_mod", "a", "b"])) == 3
    assert launcher.run_shim(launcher.parse_interpreter_args(["-c", "raise SystemExit('boom')"])) == 1
    assert launcher.run_shim(launcher.parse_interpreter_args(["-c", "x = 1"])) == 0


def test_key_precedence_dotenv_then_embedded_then_environment():
    names = ("A", "B", "C", "D", "E", "F")
    environ = {"A": "env-a", "B": "", "C": "env-c", "F": "env-f"}
    dotenv = {"A": "file-a", "B": "file-b", "D": ""}
    embedded = {"A": "emb-a", "B": "emb-b", "C": "emb-c", "D": "emb-d"}
    values, sources = launcher.resolve_keys(environ, dotenv, embedded, names)
    assert values == {"A": "file-a", "B": "file-b", "C": "emb-c", "F": "env-f"}
    assert sources == {"A": ".env", "B": ".env", "C": "embedded", "D": None, "E": None, "F": "environment"}
    applied = dict(environ)
    launcher.apply_keys(applied, dotenv, embedded, names)
    assert applied == {"A": "file-a", "B": "file-b", "C": "emb-c", "F": "env-f"}


def test_status_lines_never_reveal_values():
    secret = "sk-very-secret-value"
    _, sources = launcher.resolve_keys({}, {}, {"OPENAI_API_KEY": secret}, launcher.REQUIRED_KEYS)
    text = "\n".join(launcher.key_status_lines(sources))
    assert secret not in text
    assert "OPENAI_API_KEY: set (embedded)" in text and "NOTION_API_KEY: not set" in text


def test_embedded_keys_roundtrip_is_base64_not_plaintext():
    blob = launcher.encode_embedded({"OPENAI_API_KEY": "sk-abc", "JEV_API_KEY": ""})
    assert b"sk-abc" not in blob
    assert launcher.decode_embedded(blob) == {"OPENAI_API_KEY": "sk-abc"}
    assert launcher.decode_embedded(b"") == {} and launcher.decode_embedded(b"not base64!") == {}


def test_dotenv_write_read_roundtrip_and_first_run_creation(tmp_path):
    embedded = {"OPENAI_API_KEY": 'sk-a#b "c" d', "AIRTABLE_TOKEN": "pat.x-1"}
    assert sorted(launcher.ensure_workspace_dotenv(tmp_path, embedded)) == ["AIRTABLE_TOKEN", "OPENAI_API_KEY"]
    assert launcher.read_dotenv(tmp_path / ".env") == embedded
    names = [line.split("=")[0] for line in (tmp_path / ".env").read_text().splitlines()
             if line and not line.startswith("#")]
    assert sorted(names) == ["AIRTABLE_TOKEN", "OPENAI_API_KEY"]
    # An existing .env is never overwritten by embedded keys.
    assert launcher.ensure_workspace_dotenv(tmp_path, {"JEV_API_KEY": "x"}) == []
    launcher.update_dotenv(tmp_path / ".env", {"JEV_API_KEY": "j", "AIRTABLE_TOKEN": ""})
    assert launcher.read_dotenv(tmp_path / ".env") == {"OPENAI_API_KEY": embedded["OPENAI_API_KEY"],
                                                       "AIRTABLE_TOKEN": "", "JEV_API_KEY": "j"}
    assert launcher.ensure_workspace_dotenv(tmp_path / "empty", {}) == []
    assert not (tmp_path / "empty" / ".env").exists()


def _bundle(path, version, files):
    manifest = {"release_version": version, "sha256": {name: "x" for name in files}}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("RELEASE_MANIFEST.json", json.dumps(manifest))
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def test_workspace_extraction_protects_user_files_and_only_reextracts_on_manifest_change(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / ".env").write_text("OPENAI_API_KEY=user\n")
    (workspace / "outputs").mkdir()
    (workspace / "outputs" / "keep.txt").write_text("user output")
    files = {"app/index.html": "v1", "src/old.py": "old", ".env": "BUNDLED=1",
             "outputs/x.txt": "bundled", "data/raw/y.txt": "bundled", "../escape.txt": "no"}
    v1 = _bundle(tmp_path / "v1.zip", "1", files)
    assert launcher.extract_release(v1, workspace) == "extracted"
    assert (workspace / "app/index.html").read_text() == "v1"
    assert (workspace / ".env").read_text() == "OPENAI_API_KEY=user\n"
    assert not (workspace / "outputs" / "x.txt").exists() and not (workspace / "data").exists()
    assert (workspace / "outputs" / "keep.txt").read_text() == "user output"
    assert not (tmp_path / "escape.txt").exists()

    (workspace / "app/index.html").write_text("locally modified")
    assert launcher.extract_release(v1, workspace) == "up-to-date"
    assert (workspace / "app/index.html").read_text() == "locally modified"
    (workspace / "src/old.py").unlink()
    assert launcher.extract_release(v1, workspace) == "repaired"
    assert (workspace / "src/old.py").read_text() == "old"

    v2 = _bundle(tmp_path / "v2.zip", "2", {"app/index.html": "v2", "src/new.py": "new"})
    assert launcher.extract_release(v2, workspace) == "extracted"
    assert (workspace / "app/index.html").read_text() == "v2"
    assert (workspace / "src/new.py").exists() and not (workspace / "src/old.py").exists()
    assert (workspace / ".env").read_text() == "OPENAI_API_KEY=user\n"
    assert (workspace / "outputs" / "keep.txt").exists()
    assert json.loads((workspace / "RELEASE_MANIFEST.json").read_text())["release_version"] == "2"
    assert launcher.extract_release(v2, workspace, force=True) == "extracted"


def test_workspace_location_prefers_exe_folder_then_local_appdata(tmp_path, monkeypatch):
    exe_dir = tmp_path / "exe"
    exe_dir.mkdir()
    assert launcher.choose_workspace(exe_dir, str(tmp_path / "lad")) == exe_dir / "GTMTracker_workspace"
    monkeypatch.setattr(launcher, "is_writable_dir", lambda path: False)
    assert launcher.choose_workspace(exe_dir, str(tmp_path / "lad")) == tmp_path / "lad" / "GTMTracker" / "workspace"


def test_build_never_stages_private_or_generated_paths(tmp_path):
    build = _load("gtm_exe_build", "packaging/build_exe.py")
    for bad in (".env", "outputs/D/runtime/overview.json", "data/raw/x.json", ".venv/x.py"):
        with pytest.raises(ValueError):
            build.stage_release({bad: "0" * 64}, tmp_path / "r.zip")
    names = build.key_names()
    assert set(launcher.REQUIRED_KEYS) <= set(names) and "AIRTABLE_BASE_ID" in names


def test_run_live_node_is_optional_only_with_explicit_switch(monkeypatch):
    from scripts import run_live
    monkeypatch.setattr(run_live, "configure", lambda: None)
    monkeypatch.setattr(run_live.shutil, "which", lambda name: None)
    for key in run_live.REQUIRED:
        monkeypatch.setenv(key, "fixture-only")
    for key, value in run_live.DEFAULTS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GTM_NODE_OPTIONAL", raising=False)
    with pytest.raises(ValueError, match="Node.js"):
        run_live.main(["--check-only"])
    monkeypatch.setenv("GTM_NODE_OPTIONAL", "1")
    assert run_live.main(["--check-only"]) == 0
