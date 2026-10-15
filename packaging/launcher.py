"""GTMTracker.exe entry point: workspace extraction, access keys, menu and interpreter shim.

The release tree is bundled as data (a zip of every file listed in
RELEASE_MANIFEST.json) and extracted into a persistent workspace, so the
project runs from real files and every ROOT-relative path keeps working.
Project modules are imported from that workspace at run time, never from the
frozen archive. Every helper below is importable and testable unfrozen.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import runpy
import shutil
import sys
import threading
import traceback
import zipfile

APP_NAME = "GTMTracker"
WORKSPACE_DIRNAME = APP_NAME + "_workspace"
RELEASE_ZIP = "gtm_tracker_release.zip"
KEYS_FILE = "embedded_keys.b64"
MANIFEST = "RELEASE_MANIFEST.json"
KEYS_FORMAT = "gtm-embedded-keys/1"
REQUIRED_KEYS = ("NOTION_API_KEY", "AIRTABLE_TOKEN", "OPENAI_API_KEY", "JEV_API_KEY")
OPTIONAL_KEYS = ("NOTION_ROOT_PAGE_ID", "NOTION_DATABASE_ID", "NOTION_DATA_SOURCE_ID", "AIRTABLE_BASE_ID",
                 "NOTION_EXPORT_ZIP", "CRM_EXPORT_JSON",
                 "OPENAI_SEMANTIC_MODEL", "OPENAI_SEMANTIC_REASONING", "OPENAI_SEMANTIC_MAX_CONCURRENCY",
                 "OPENAI_EXTRACTION_MODEL", "JEV_REPEATS", "JEV_MAX_CONCURRENCY")
# Workspace content that belongs to the user and is never written by extraction.
PROTECTED_TOP = {".env", "outputs", "data", ".local"}
DEMO_PORT, LIVE_PORT = 8877, 8878

# Python interpreter options accepted by the shim (subset of CPython's command line).
_FLAGS_NO_ARG = {"-B", "-I", "-u", "-E", "-s", "-S", "-O", "-OO", "-q", "-b", "-bb", "-d", "-v", "-P"}
_FLAGS_WITH_ARG = {"-X", "-W"}


# ---------------------------------------------------------------- interpreter shim
def parse_interpreter_args(args):
    """Return a shim spec when args look like a Python command line, else None.

    Supported forms: [flags] -m module [args], [flags] -c code [args],
    [flags] path/to/script.py [args]. Launcher subcommands never match.
    """
    args = list(args)
    flags, i = [], 0
    while i < len(args):
        arg = args[i]
        if arg in _FLAGS_NO_ARG:
            flags.append(arg)
            i += 1
        elif arg in _FLAGS_WITH_ARG and i + 1 < len(args):
            flags += args[i:i + 2]
            i += 2
        else:
            break
    rest = args[i:]
    if rest[:1] == ["-m"] and len(rest) >= 2:
        return {"mode": "module", "target": rest[1], "args": rest[2:], "flags": flags}
    if rest[:1] == ["-c"] and len(rest) >= 2:
        return {"mode": "code", "target": rest[1], "args": rest[2:], "flags": flags}
    if rest and not rest[0].startswith("-") and rest[0].lower().endswith(".py"):
        return {"mode": "path", "target": rest[0], "args": rest[1:], "flags": flags}
    return None


def exit_code(exc: SystemExit) -> int:
    """Mirror CPython's handling of SystemExit codes."""
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr, flush=True)
    return 1


def run_shim(spec) -> int:
    """Run a module/script/code like `python <flags> ...` would, in this process."""
    if "-B" in spec["flags"]:
        sys.dont_write_bytecode = True
    try:
        if spec["mode"] == "module":
            sys.argv = [spec["target"]] + spec["args"]
            sys.path.insert(0, os.getcwd())
            runpy.run_module(spec["target"], run_name="__main__", alter_sys=True)
        elif spec["mode"] == "path":
            script = os.path.abspath(spec["target"])
            sys.argv = [spec["target"]] + spec["args"]
            sys.path.insert(0, os.path.dirname(script))
            runpy.run_path(script, run_name="__main__")
        else:
            sys.argv = ["-c"] + spec["args"]
            sys.path.insert(0, "")
            exec(compile(spec["target"], "<string>", "exec"), {"__name__": "__main__"})
    except SystemExit as exc:
        return exit_code(exc)
    except KeyboardInterrupt:
        return 130
    except BaseException:  # noqa: BLE001 - interpreter semantics: report and fail
        traceback.print_exc()
        return 1
    return 0


# ---------------------------------------------------------------- workspace
def is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / (".write_probe_%d" % os.getpid())
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def choose_workspace(exe_dir: Path, local_appdata: str | None = None) -> Path:
    """`<exe folder>/GTMTracker_workspace` if writable, else %LOCALAPPDATA%/GTMTracker/workspace."""
    preferred = Path(exe_dir) / WORKSPACE_DIRNAME
    if is_writable_dir(preferred):
        return preferred
    base = local_appdata or os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    fallback = Path(base) / APP_NAME / "workspace"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def is_protected(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return bool(parts) and (parts[0] in PROTECTED_TOP or parts[-1] == ".env")


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not name.endswith("/") and not path.is_absolute() and ".." not in path.parts \
        and ":" not in name and not is_protected(name)


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp%d" % os.getpid())
    temp.write_bytes(data)
    os.replace(temp, target)


def _manifest_files(raw: bytes | None) -> set[str]:
    if not raw:
        return set()
    try:
        return set(json.loads(raw.decode("utf-8")).get("sha256", {}))
    except (ValueError, AttributeError):
        return set()


def extract_release(bundle_zip: Path, workspace: Path, force: bool = False) -> str:
    """Install the bundled release tree into the workspace.

    Returns "extracted" (manifest changed or forced: all release files rewritten,
    files dropped from the release removed), "repaired" (same manifest, missing
    release files restored) or "up-to-date". Never touches .env, outputs/, data/.
    """
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_zip) as archive:
        bundled_manifest = archive.read(MANIFEST)
        current = workspace / MANIFEST
        current_manifest = current.read_bytes() if current.is_file() else None
        members = [n for n in archive.namelist() if n != MANIFEST and _safe_member(n)]
        if not force and current_manifest == bundled_manifest:
            missing = [n for n in members if not (workspace / n).is_file()]
            for name in missing:
                _write_atomic(workspace / name, archive.read(name))
            return "repaired" if missing else "up-to-date"
        stale = _manifest_files(current_manifest) - _manifest_files(bundled_manifest) - set(members)
        for name in sorted(stale):
            if _safe_member(name):
                path = workspace / name
                if path.is_file():
                    path.unlink()
        for name in members:
            _write_atomic(workspace / name, archive.read(name))
        _write_atomic(current, bundled_manifest)  # written last: marks a complete extraction
    return "extracted"


# ---------------------------------------------------------------- access keys
def encode_embedded(values: dict) -> bytes:
    """Base64-encode the embedded-keys JSON. Obfuscation against casual viewing only: NOT encryption."""
    payload = {"format": KEYS_FORMAT, "note": "base64 only - not encryption",
               "keys": {k: v for k, v in values.items() if v}}
    return base64.b64encode(json.dumps(payload, sort_keys=True).encode("utf-8"))


def decode_embedded(blob: bytes | None) -> dict:
    if not blob:
        return {}
    try:
        payload = json.loads(base64.b64decode(blob).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    if payload.get("format") != KEYS_FORMAT:
        return {}
    return {str(k): str(v) for k, v in payload.get("keys", {}).items() if v}


_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r'\\(["\\])', r"\1", value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return re.split(r"\s+#", value, maxsplit=1)[0]


def read_dotenv(path: Path) -> dict:
    values = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return values
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if match:
            values[match.group(1)] = _unquote(match.group(2))
    return values


def _quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_\-.:/+=@,]*", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def update_dotenv(path: Path, updates: dict, header: str | None = None) -> None:
    """Set (value) or remove (None) keys in a .env file, keeping other lines intact."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else \
        ([("# " + line) if line else "#" for line in header.splitlines()] if header else [])
    pending = dict(updates)
    output = []
    for line in lines:
        match = None if line.lstrip().startswith("#") else _LINE.match(line)
        if match and match.group(1) in pending:
            value = pending.pop(match.group(1))
            if value is not None:
                output.append(f"{match.group(1)}={_quote(value)}")
            continue
        output.append(line)
    output += [f"{k}={_quote(v)}" for k, v in pending.items() if v is not None]
    _write_atomic(path, ("\n".join(output) + "\n").encode("utf-8"))


ENV_HEADER = ("Created by GTMTracker.exe from the access keys embedded at build time.\n"
              "Private: never share this file. Edit values here or use the 'Configure access keys' menu.\n"
              "Precedence: process environment variables > this file > keys embedded in the exe.")


def ensure_workspace_dotenv(workspace: Path, embedded: dict) -> list[str]:
    """First run: create workspace .env from the embedded keys. Returns the names written."""
    path = Path(workspace) / ".env"
    names = [k for k, v in embedded.items() if v]
    if path.exists() or not names:
        return []
    update_dotenv(path, {k: embedded[k] for k in names}, header=ENV_HEADER)
    return names


def resolve_keys(environ, dotenv: dict, embedded: dict, names) -> tuple[dict, dict]:
    """Precedence: workspace .env > embedded > process environment.

    The owner's configured keys win over unrelated machine-wide variables. A name
    written in .env with an empty value (NAME=) disables the embedded fallback for
    that name; an empty environment variable counts as unset.
    """
    values, sources = {}, {}
    for name in names:
        sources[name] = None
        if name in dotenv:
            if dotenv[name]:
                values[name], sources[name] = dotenv[name], ".env"
        elif embedded.get(name):
            values[name], sources[name] = embedded[name], "embedded"
        if name not in values and environ.get(name):
            values[name], sources[name] = environ[name], "environment"
    return values, sources


def apply_keys(environ, dotenv: dict, embedded: dict, names) -> dict:
    """Set environ according to precedence (configured keys override the environment); returns name -> source."""
    values, sources = resolve_keys(environ, dotenv, embedded, names)
    for name, value in values.items():
        environ[name] = value
    return sources


def key_status_lines(sources: dict, names=REQUIRED_KEYS) -> list[str]:
    """Human-readable status that never contains a value."""
    return [f"  {name}: " + (f"set ({sources[name]})" if sources.get(name) else "not set") for name in names]


# ---------------------------------------------------------------- command line
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME + ".exe", description="GTM Tracker. Run without "
                                     "arguments for the interactive menu.")
    sub = parser.add_subparsers(dest="command")
    demo = sub.add_parser("demo", help="Serve the frozen offline demo (default)")
    demo.add_argument("--port", type=int, default=DEMO_PORT)
    demo.add_argument("--no-browser", action="store_true")
    sub.add_parser("check", help="Live preflight: configuration and imports only, no external calls")
    live = sub.add_parser("live", help="Full live run (external API calls, may incur charges)")
    live.add_argument("--no-serve", action="store_true")
    live.add_argument("--port", type=int, default=LIVE_PORT)
    live.add_argument("--no-browser", action="store_true")
    serve = sub.add_parser("serve-live", help="Reopen the last validated live result")
    serve.add_argument("--port", type=int, default=LIVE_PORT)
    serve.add_argument("--no-browser", action="store_true")
    sub.add_parser("keys", help="Configure access keys (saved to the workspace .env)")
    test = sub.add_parser("test", help="Run the offline self-test suite (--live: also call the real providers)")
    test.add_argument("--live", action="store_true")
    sub.add_parser("where", help="Show exe, workspace and key status (names only)")
    sub.add_parser("repair", help="Re-extract all release files into the workspace")
    return parser


def parse_cli(args):
    return build_parser().parse_args(list(args))


# ---------------------------------------------------------------- runtime state
class Context:
    def __init__(self, workspace: Path, bundle: Path | None, embedded: dict, sources: dict,
                 external: set, extraction: str):
        self.workspace, self.bundle, self.embedded = workspace, bundle, embedded
        self.sources, self.external, self.extraction = sources, external, extraction


def bundle_dir() -> Path | None:
    return Path(sys._MEIPASS) if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else None


def prepare(force: bool = False) -> Context:
    bundle = bundle_dir()
    if bundle is not None:
        workspace = choose_workspace(Path(sys.executable).resolve().parent)
        state = extract_release(bundle / RELEASE_ZIP, workspace, force=force)
        blob = (bundle / KEYS_FILE).read_bytes() if (bundle / KEYS_FILE).is_file() else b""
        embedded = decode_embedded(blob)
    else:  # unfrozen development run: the project itself is the workspace
        workspace, state, embedded = Path(__file__).resolve().parents[1], "source tree", {}
    os.chdir(workspace)
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    created = ensure_workspace_dotenv(workspace, embedded)
    if created:
        print(f"Saved {len(created)} embedded access setting(s) to {workspace / '.env'} (names: "
              + ", ".join(created) + ").", flush=True)
    names = REQUIRED_KEYS + OPTIONAL_KEYS + tuple(k for k in embedded if k not in REQUIRED_KEYS + OPTIONAL_KEYS)
    external = {n for n in names if os.environ.get(n)}
    sources = apply_keys(os.environ, read_dotenv(workspace / ".env"), embedded, names)
    if bundle is not None and not shutil.which("node"):
        os.environ["GTM_NODE_OPTIONAL"] = "1"
    return Context(workspace, bundle, embedded, sources, external, state)


def _serve(httpd, url: str, open_browser: bool, stopped: str) -> int:
    import signal
    import webbrowser

    def stop(signum, frame):
        raise KeyboardInterrupt
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop)
    if open_browser:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(stopped, flush=True)
    finally:
        httpd.server_close()
    return 0


def cmd_demo(ctx: Context, port: int = DEMO_PORT, open_browser: bool = True) -> int:
    server = importlib.import_module("runtime.server")
    try:
        server.verify_release()
    except (OSError, ValueError, KeyError) as exc:
        print("Unable to start demo: " + str(exc), flush=True)
        print(f"Run '{APP_NAME}.exe repair' to restore the original release files.", flush=True)
        return 1
    try:
        httpd = server.Server(("127.0.0.1", port), server.Handler)
    except OSError as exc:
        if exc.errno not in {48, 98, 10048}:
            print("Unable to start demo: " + str(exc), flush=True)
            return 1
        print("Requested port is busy; selecting another local port.", flush=True)
        httpd = server.Server(("127.0.0.1", 0), server.Handler)
    url = f"http://127.0.0.1:{httpd.server_port}/app/"
    print("\nGTM TRACKER\n", flush=True)
    print("Open: " + url, flush=True)
    print("Frozen offline demo. Keep this window open. Press Ctrl+C to stop.\n", flush=True)
    return _serve(httpd, url, open_browser, "Demo stopped.")


def cmd_serve_live(ctx: Context, port: int = LIVE_PORT, open_browser: bool = True) -> int:
    live = importlib.import_module("runtime.live_server")
    contract = importlib.import_module("scripts.validate_presentation_contract")
    runtime_dir = ctx.workspace / "outputs/D/runtime"
    if not (runtime_dir / "manifest.json").is_file():
        print("No live result found in " + str(runtime_dir) + ". Run the full live run first.", flush=True)
        return 1
    try:
        contract.validate(runtime_dir, ctx.workspace / "data/runtime/gtm_state.sqlite")
        httpd = live.Server(("127.0.0.1", port), live.LiveHandler)
    except Exception as exc:  # noqa: BLE001 - show the validation/bind failure, never fall back to demo
        print("Unable to open the live result: " + str(exc), flush=True)
        return 1
    url = f"http://127.0.0.1:{httpd.server_port}/app/"
    print("Live product: " + url, flush=True)
    print("Current live results; frozen demo is unchanged. Press Ctrl+C to stop.", flush=True)
    return _serve(httpd, url, open_browser, "Live product stopped.")


def _run_live_script(args) -> int:
    saved = list(sys.argv)
    try:
        return run_shim({"mode": "path", "target": "scripts/run_live.py", "args": list(args), "flags": ["-B"]})
    finally:
        sys.argv = saved


def _node_note() -> None:
    if os.environ.get("GTM_NODE_OPTIONAL") == "1":
        print("Note: Node.js was not found; the frontend check will skip only its JavaScript syntax step.",
              flush=True)


def cmd_check(ctx: Context) -> int:
    _node_note()
    return _run_live_script(["--check-only"])


def cmd_live(ctx: Context, port: int = LIVE_PORT, serve: bool = True, open_browser: bool = True) -> int:
    print("Full live run: reads Notion and Airtable and calls OpenAI/Jev (may incur API charges).", flush=True)
    _node_note()
    try:
        code = _run_live_script(["--no-serve", "--port", str(port)])
    except KeyboardInterrupt:
        print("Live run interrupted.", flush=True)
        return 130
    if code != 0 or not serve:
        return code
    return cmd_serve_live(ctx, port, open_browser)


def cmd_keys(ctx: Context) -> int:
    import getpass
    env_path = ctx.workspace / ".env"
    print("Access keys are saved to " + str(env_path) + " (private; values are never displayed).")
    print("\n".join(key_status_lines(ctx.sources)))
    print("Type a new value (input hidden), Enter keeps the current one, '-' clears it (also disables "
          "the embedded fallback).")
    updates = {}
    for name in REQUIRED_KEYS:
        try:
            value = getpass.getpass(f"{name}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nNo changes saved.")
            return 1
        if value == "-":
            updates[name] = ""
        elif value:
            updates[name] = value
    if not updates:
        print("No changes.")
        return 0
    update_dotenv(env_path, updates, header=ENV_HEADER)
    for name, value in updates.items():
        if name in ctx.external:
            print(f"{name}: saved; it now takes precedence over the environment variable with this name.")
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)
    ctx.sources = apply_keys(os.environ, read_dotenv(env_path), ctx.embedded, tuple(ctx.sources))
    print("Saved. Optional settings (scope hints, model overrides) can be edited in the same file.")
    print("\n".join(key_status_lines(ctx.sources)))
    return 0


def cmd_test(ctx: Context, live: bool = False) -> int:
    pytest = importlib.import_module("pytest")
    if live:
        # Keys were already resolved into the process environment (env > workspace .env > embedded).
        os.environ["GTM_LIVE_TESTS"] = "1"
    return int(pytest.main(["-q", "-rA" if live else "-q", str(ctx.workspace / "tests")]))


def cmd_where(ctx: Context) -> int:
    manifest = {}
    try:
        manifest = json.loads((ctx.workspace / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    print("Executable : " + (sys.executable if ctx.bundle else "(not frozen) " + sys.executable))
    print("Workspace  : " + str(ctx.workspace))
    print("Release    : " + str(manifest.get("release_version", "?")) + " (" +
          str(manifest.get("release_timestamp", "?")) + "), workspace " + ctx.extraction)
    env_path = ctx.workspace / ".env"
    print("Keys file  : " + str(env_path) + ("" if env_path.is_file() else " (not created)"))
    print("Embedded   : " + (", ".join(sorted(ctx.embedded)) if ctx.embedded else "none"))
    print("Node.js    : " + ("found" if shutil.which("node") else "not found (JavaScript syntax step skipped)"))
    print("Live access keys (names only):")
    print("\n".join(key_status_lines(ctx.sources)))
    return 0


def cmd_open_folder(ctx: Context) -> int:
    print("Workspace: " + str(ctx.workspace))
    if hasattr(os, "startfile"):
        os.startfile(str(ctx.workspace))  # noqa: S606 - opens Explorer on the local workspace
    return 0


MENU = """
=================== GTM TRACKER ===================
 [1] Open demo (offline, default)
 [2] Live preflight (no external calls)
 [3] Full live run (external API calls)
 [4] Reopen last live result
 [5] Configure access keys
 [6] Run self-tests (offline)
 [7] Open workspace folder
 [0] Exit
"""


def menu(ctx: Context) -> int:
    while True:
        print(MENU)
        print("Workspace: " + str(ctx.workspace))
        ready = sum(1 for k in REQUIRED_KEYS if ctx.sources.get(k))
        print(f"Live access keys: {ready}/{len(REQUIRED_KEYS)} set")
        try:
            choice = input("Choose [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        actions = {"1": lambda: cmd_demo(ctx), "2": lambda: cmd_check(ctx), "3": lambda: _confirm_live(ctx),
                   "4": lambda: cmd_serve_live(ctx), "5": lambda: cmd_keys(ctx), "6": lambda: cmd_test(ctx),
                   "7": lambda: cmd_open_folder(ctx)}
        if choice == "0":
            return 0
        if choice not in actions:
            print("Unknown choice.")
            continue
        try:
            code = actions[choice]()
        except KeyboardInterrupt:
            code = 130
            print("\nStopped.")
        print(f"\n(finished with exit code {code})")


def _confirm_live(ctx: Context) -> int:
    try:
        answer = input("The full live run calls external services and may incur charges. Continue? [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        return 1
    return cmd_live(ctx) if answer.strip().lower() in {"y", "yes"} else 1


def fix_frozen_console() -> None:
    """Make the frozen exe's C runtime behave like python.exe for standard handles.

    The PyInstaller bootloader leaves the UCRT app type unset, so os.dup2() onto
    fd 0-2 (e.g. pytest's fd capture) does not update the Windows std handles and
    later subprocess calls fail with WinError 6. python.exe sets "console app".
    """
    if getattr(sys, "frozen", False) and os.name == "nt":
        try:
            import ctypes
            ctypes.cdll.ucrtbase._set_app_type(1)  # _crt_console_app
        except (OSError, AttributeError):
            pass


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    fix_frozen_console()
    shim = parse_interpreter_args(argv)
    if shim is not None:
        return run_shim(shim)
    args = parse_cli(argv)
    try:
        ctx = prepare(force=args.command == "repair")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        print("Unable to prepare the workspace: " + str(exc), flush=True)
        return 1
    if args.command is None:
        return menu(ctx)
    try:
        if args.command == "demo":
            return cmd_demo(ctx, args.port, not args.no_browser)
        if args.command == "check":
            return cmd_check(ctx)
        if args.command == "live":
            return cmd_live(ctx, args.port, not args.no_serve, not args.no_browser)
        if args.command == "serve-live":
            return cmd_serve_live(ctx, args.port, not args.no_browser)
        if args.command == "keys":
            return cmd_keys(ctx)
        if args.command == "test":
            return cmd_test(ctx, args.live)
        if args.command == "repair":
            print("Release files re-extracted to " + str(ctx.workspace) + " (.env, outputs/ and data/ untouched).")
            return 0
        return cmd_where(ctx)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 130


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
