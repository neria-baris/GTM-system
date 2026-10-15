"""Build dist/GTMTracker.exe: a onefile PyInstaller executable of the GTM Tracker release.

Run with the project's virtual environment (it must contain requirements.txt and
PyInstaller):  .venv\\Scripts\\python.exe -B packaging\\build_exe.py

Steps: refresh RELEASE_MANIFEST.json, stage exactly the manifest files into a
zip (hash-verified), embed the access keys found at build time (project .env if
present, else this machine's environment variables), AST-scan every project
module for imports, run PyInstaller, remove temporary build directories.
The resulting exe CONTAINS THE EMBEDDED ACCESS KEYS: never share it.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
import launcher  # noqa: E402  (shared constants and the embedded-keys encoder)

NAME = launcher.APP_NAME
FORBIDDEN_PARTS = {".env", ".venv", "outputs", "data", ".local", "__pycache__", "dist", "build"}
# Packages whose submodules or data are loaded dynamically (not visible to static analysis).
COLLECT_SUBMODULES = ("openai", "httpx", "httpcore", "anyio", "h11", "certifi", "dotenv", "yaml",
                      "pydantic", "pydantic_core", "jiter", "distro", "sniffio", "idna",
                      "pytest", "_pytest", "pluggy", "iniconfig", "packaging")
COLLECT_DATA = ("certifi", "openai")
EXTRA_HIDDEN = ("tomli", "exceptiongroup", "colorama", "pygments", "typing_extensions",
                "annotated_types", "typing_inspection", "tqdm", "getpass", "webbrowser", "runpy",
                "multiprocessing", "zipfile", "base64")
EXCLUDES = ("tkinter", "_tkinter", "turtle", "turtledemo", "idlelib", "PyInstaller", "pip", "setuptools")


def log(message: str) -> None:
    print("[build] " + message, flush=True)


def refresh_manifest() -> dict:
    subprocess.run([sys.executable, "-B", "scripts/update_release_manifest.py"], cwd=ROOT, check=True)
    return json.loads((ROOT / launcher.MANIFEST).read_text(encoding="utf-8"))


def stage_release(manifest_files: dict, destination: Path) -> int:
    """Zip exactly the manifest files (hash-verified) plus RELEASE_MANIFEST.json."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative, expected in sorted(manifest_files.items()):
            parts = PurePosixPath(relative).parts
            if FORBIDDEN_PARTS.intersection(parts) or relative.endswith(".env") or launcher.is_protected(relative):
                raise ValueError("Refusing to stage a private or generated path: " + relative)
            data = (ROOT / relative).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError("Release file changed during the build: " + relative)
            archive.writestr(relative, data)
        archive.writestr(launcher.MANIFEST, (ROOT / launcher.MANIFEST).read_bytes())
    return len(manifest_files)


def key_names() -> list[str]:
    names = list(launcher.REQUIRED_KEYS)
    example = launcher.read_dotenv(ROOT / ".env.example")
    names += [n for n in example if n not in names]
    names += [n for n in launcher.OPTIONAL_KEYS if n not in names]
    return names


def collect_keys(no_keys: bool) -> tuple[dict, str]:
    if no_keys:
        return {}, "disabled (--no-keys)"
    names = key_names()
    env_file = ROOT / ".env"
    if env_file.is_file():
        values = launcher.read_dotenv(env_file)
        source = "project .env"
    else:
        values = dict(os.environ)
        source = "build machine environment variables"
    return {n: values[n] for n in names if values.get(n)}, source


def project_module_names(files) -> set[str]:
    names = set()
    for relative in files:
        path = PurePosixPath(relative)
        if path.suffix == ".py":
            names.add(path.stem)
            names.update(path.parts[:-1])
    names.update(p.name for p in ROOT.iterdir() if p.is_dir())
    return names


def scan_imports(py_files) -> set[str]:
    found = set()
    for path in py_files:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module)
                found.update(node.module + "." + alias.name for alias in node.names if alias.name != "*")
    return found


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def hidden_imports(manifest_files) -> tuple[list[str], list[str]]:
    project = project_module_names(manifest_files)
    py_files = [ROOT / r for r in manifest_files if r.endswith(".py")]
    hidden, missing = set(), set()
    for name in sorted(scan_imports(py_files)):
        top = name.split(".")[0]
        if top in project or top == "__future__":
            continue
        if _importable(name):
            hidden.add(name)
        elif "." in name and _importable(name.rsplit(".", 1)[0]):
            continue  # `from package import attribute`, not a submodule
        else:
            missing.add(name)
    hidden.update(n for n in EXTRA_HIDDEN if _importable(n))
    return sorted(hidden), sorted(missing)


def pyinstaller(work: Path, release_zip: Path, keys_file: Path, hidden: list[str]) -> Path:
    sep = os.pathsep
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
               "--name", NAME, "--distpath", str(work / "dist"), "--workpath", str(work / "work"),
               "--specpath", str(work / "spec"), "--log-level", "WARN",
               "--add-data", f"{release_zip}{sep}.", "--add-data", f"{keys_file}{sep}."]
    for name in hidden:
        command += ["--hidden-import", name]
    for name in COLLECT_SUBMODULES:
        if _importable(name):
            command += ["--collect-submodules", name]
    for name in COLLECT_DATA:
        if _importable(name):
            command += ["--collect-data", name]
    # Project packages run from the extracted workspace, never from the frozen archive.
    for name in EXCLUDES + ("src", "scripts", "runtime", "tests", "app", "demo", "config"):
        command += ["--exclude-module", name]
    command.append(str(ROOT / "packaging" / "launcher.py"))
    subprocess.run(command, cwd=work, check=True)
    return work / "dist" / (NAME + ".exe")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-keys", action="store_true", help="Build without embedding any access key")
    parser.add_argument("--keep-build", action="store_true", help="Keep the temporary build directory")
    args = parser.parse_args(argv)
    if not _importable("PyInstaller"):
        raise SystemExit("PyInstaller is not installed in this interpreter. Use the project .venv.")

    for attempt in (1, 2):
        manifest = refresh_manifest()
        work = Path(tempfile.mkdtemp(prefix="gtm_exe_build_"))
        try:
            release_zip = work / launcher.RELEASE_ZIP
            count = stage_release(manifest["sha256"], release_zip)
            break
        except RuntimeError as exc:
            shutil.rmtree(work, ignore_errors=True)
            if attempt == 2:
                raise SystemExit(str(exc) + " (twice). Stop concurrent edits and rebuild.")
            log(str(exc) + "; refreshing the manifest and retrying.")
    log(f"Staged {count} release files (release {manifest.get('release_version')}, "
        f"{manifest.get('release_timestamp')}).")

    keys, source = collect_keys(args.no_keys)
    keys_file = work / launcher.KEYS_FILE
    keys_file.write_bytes(launcher.encode_embedded(keys))
    log("Access keys source: " + source)
    log("Embedded access settings (names only): " + (", ".join(sorted(keys)) if keys else "none"))
    missing_required = [n for n in launcher.REQUIRED_KEYS if n not in keys]
    if missing_required:
        log("Required live keys NOT embedded: " + ", ".join(missing_required) +
            " (the demo works; live mode needs them via the menu, the workspace .env or the environment).")

    hidden, unresolved = hidden_imports(manifest["sha256"])
    log(f"Hidden imports from project AST scan: {len(hidden)}")
    if unresolved:
        log("Imports not installed in this interpreter (skipped): " + ", ".join(unresolved))

    log("Running PyInstaller (this takes a few minutes)...")
    built = pyinstaller(work, release_zip, keys_file, hidden)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    target = dist / built.name
    shutil.copy2(built, target)
    if args.keep_build:
        log("Build directory kept: " + str(work))
    else:
        shutil.rmtree(work, ignore_errors=True)
    size = target.stat().st_size / (1024 * 1024)
    log(f"Built {target} ({size:.1f} MB)")
    if keys:
        print("\n" + "!" * 78)
        print("WARNING: this executable CONTAINS EMBEDDED ACCESS KEYS (" + ", ".join(sorted(keys)) + ").")
        print("They are only base64-obfuscated, NOT encrypted. Anyone with the exe can extract them.")
        print("Do not share, upload or commit dist/" + built.name + ". Use --no-keys for a shareable build.")
        print("!" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
