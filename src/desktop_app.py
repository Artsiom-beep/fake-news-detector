from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

import uvicorn

APP_TITLE = "Verity Lens"
APP_PACKAGE_NAME = "FakeNewsDetector"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_AI_IMAGE_MODEL = "metadata_only"
APP_IMPORT = "src.ui:app"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)).resolve()
    return Path(__file__).resolve().parents[1]


def user_data_dir() -> Path:
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_PACKAGE_NAME


def configure_runtime_environment() -> Path:
    root = resource_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)

    if is_frozen():
        data_dir = user_data_dir()
        cache_dir = data_dir / "cache"
        model_cache_dir = data_dir / "model-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        model_cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("FACTCHECK_CACHE_PATH", str(cache_dir / "factcheck_cache.sqlite3"))
        os.environ.setdefault("HF_HOME", str(model_cache_dir))
    return root


def enable_default_ai_image_model() -> None:
    """Keep the packaged desktop app on the lightweight image-risk path by default."""
    if "FACTCHECK_AI_IMAGE_MODEL" not in os.environ:
        os.environ["FACTCHECK_AI_IMAGE_MODEL"] = DEFAULT_AI_IMAGE_MODEL


def find_free_port(host: str = DEFAULT_HOST, preferred_port: int = DEFAULT_PORT) -> int:
    """Return preferred_port if available, otherwise ask the OS for a free port."""
    if preferred_port <= 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as fallback:
            fallback.bind((host, 0))
            return int(fallback.getsockname()[1])

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as preferred:
        preferred.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            preferred.bind((host, preferred_port))
            return preferred_port
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as fallback:
        fallback.bind((host, 0))
        return int(fallback.getsockname()[1])


def build_local_url(host: str, port: int, path: str = "/") -> str:
    clean_path = path if path.startswith("/") else f"/{path}"
    return f"http://{host}:{port}{clean_path}"


def _wait_for_http(url: str, timeout_s: float = 15.0) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if 200 <= response.status < 500:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    return False


def _create_server(host: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(
        APP_IMPORT,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        lifespan="on",
    )
    return uvicorn.Server(config)


def _start_server_thread(server: uvicorn.Server) -> threading.Thread:
    thread = threading.Thread(target=server.run, name="fake-news-detector-ui", daemon=True)
    thread.start()
    return thread


def _stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=5)


def _error_html(message: str) -> str:
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <style>
          body {{
            margin: 0;
            display: grid;
            min-height: 100vh;
            place-items: center;
            background: #f8efe2;
            color: #1f2937;
            font-family: Segoe UI, sans-serif;
          }}
          main {{
            max-width: 640px;
            padding: 28px;
            border-radius: 24px;
            background: #fffaf2;
            border: 1px solid #decdb5;
            box-shadow: 0 20px 70px rgba(35, 25, 10, .16);
          }}
          h1 {{ margin: 0 0 10px; font-size: 26px; }}
          p {{ color: #596579; line-height: 1.55; }}
          code {{ background: #f0e2cd; padding: 2px 6px; border-radius: 8px; }}
        </style>
      </head>
      <body>
        <main>
          <h1>Could not start {escape(APP_TITLE)}</h1>
          <p>{escape(message)}</p>
          <p>Try running <code>python -m src.desktop_app --smoke</code> to check the local server.</p>
        </main>
      </body>
    </html>
    """


def _show_startup_error(message: str) -> None:
    try:
        import webview

        webview.create_window(
            f"{APP_TITLE} - Startup Error",
            html=_error_html(message),
            width=720,
            height=360,
            resizable=True,
        )
        webview.start()
    except Exception:
        print(f"{APP_TITLE} startup error: {message}", file=sys.stderr)


def _webview_unavailable_message(exc: BaseException) -> str:
    return (
        "PyWebView could not be loaded. In a packaged build this usually means "
        "the Windows WebView2 runtime or bundled Python GUI bridge is unavailable. "
        f"Details: {type(exc).__name__}: {exc}"
    )


def run_smoke(host: str = DEFAULT_HOST, preferred_port: int = DEFAULT_PORT) -> int:
    configure_runtime_environment()
    enable_default_ai_image_model()
    port = find_free_port(host, preferred_port)
    url = build_local_url(host, port)
    try:
        server = _create_server(host, port)
        thread = _start_server_thread(server)
    except Exception as exc:
        print(f"Smoke failed before server start: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    try:
        if not _wait_for_http(url, timeout_s=15):
            print(
                f"Smoke failed: UI did not respond at {url}. "
                f"Resource root: {resource_root()}",
                file=sys.stderr,
            )
            return 1
        print(f"Smoke OK: {url}")
        return 0
    finally:
        _stop_server(server, thread)


def run_desktop_app(
    host: str = DEFAULT_HOST,
    preferred_port: int = DEFAULT_PORT,
    width: int = 1180,
    height: int = 820,
) -> int:
    configure_runtime_environment()
    enable_default_ai_image_model()

    try:
        import webview
    except Exception as exc:
        message = _webview_unavailable_message(exc)
        print(message, file=sys.stderr)
        return 1

    port = find_free_port(host, preferred_port)
    url = build_local_url(host, port)
    server = _create_server(host, port)
    thread = _start_server_thread(server)

    if not _wait_for_http(url, timeout_s=15):
        _stop_server(server, thread)
        _show_startup_error(f"The local UI server did not respond at {url}.")
        return 1

    try:
        webview.create_window(
            APP_TITLE,
            url,
            width=width,
            height=height,
            min_size=(820, 620),
            resizable=True,
            background_color="#fffaf4",
        )
        webview.start()
        return 0
    finally:
        _stop_server(server, thread)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch Verity Lens as a local desktop app.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--width", type=int, default=1180)
    parser.add_argument("--height", type=int, default=820)
    parser.add_argument("--smoke", action="store_true", help="Start the local UI server, verify it responds, then exit.")
    args = parser.parse_args()

    if args.smoke:
        return run_smoke(host=args.host, preferred_port=args.port)
    return run_desktop_app(host=args.host, preferred_port=args.port, width=args.width, height=args.height)


if __name__ == "__main__":
    raise SystemExit(main())
