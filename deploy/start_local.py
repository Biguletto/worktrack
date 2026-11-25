"""Start the local Django server and open its verified sign-in page."""
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser


PROJECT = Path(__file__).resolve().parents[1]
ADDRESS = "127.0.0.1:8765"
LOGIN = f"http://{ADDRESS}/accounts/login/"
LOCAL_HTTP = build_opener(ProxyHandler({}))


def login_ready():
    try:
        with LOCAL_HTTP.open(LOGIN, timeout=1) as response:
            return (response.geturl() == LOGIN and response.status == 200
                    and b"<title>Sign in | WorkTrack</title>" in response.read(8192))
    except (URLError, OSError):
        return False


def open_login():
    print(f"WorkTrack is ready. Open {LOGIN}", flush=True)
    webbrowser.open(LOGIN)


def main():
    if login_ready():
        open_login()
        return 0

    manage = [sys.executable, str(PROJECT / "manage.py")]
    migrate = subprocess.run([*manage, "migrate"], cwd=PROJECT)
    if migrate.returncode:
        return migrate.returncode

    print("Starting WorkTrack. Keep this window open while using the app.", flush=True)
    server = subprocess.Popen([*manage, "runserver", ADDRESS, "--noreload"], cwd=PROJECT)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if server.poll() is not None:
                return server.returncode or 1
            if login_ready():
                open_login()
                return server.wait()
            time.sleep(0.25)
        print(f"The sign-in page did not respond at {LOGIN} within 30 seconds.", flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if server.poll() is None:
            server.terminate()
        server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
