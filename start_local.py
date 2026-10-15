"""Start the complete release locally; Node is only needed for editing source."""
import argparse
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent
MODULES = ['fastapi', 'uvicorn', 'multipart', 'trimesh', 'numpy', 'scipy', 'igl', 'open3d']


def python_runtime():
    local = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if local.exists():
        interpreter = str(local)
    elif all(importlib.util.find_spec(name) is not None for name in MODULES):
        return sys.executable
    else:
        print('Preparing a local Python environment (first run only)...', flush=True)
        venv.create(ROOT / '.venv', with_pip=True)
        interpreter = str(local)
    subprocess.run([interpreter, '-m', 'pip', 'install', '-r', str(ROOT / 'backend' / 'requirements.txt')], check=True)
    return interpreter


def available_port(first):
    for port in range(first, first + 20):
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', port))
            return port
        except OSError:
            continue
    raise RuntimeError('No free local port found; close an older demo server and retry.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError('Please install Python 3.11 or 3.12 first.')
    if not (ROOT / 'frontend' / 'dist' / 'index.html').exists():
        raise RuntimeError('Frontend build missing. Run pnpm install and pnpm build in frontend.')
    interpreter = python_runtime()
    port = available_port(args.port)
    url = f'http://127.0.0.1:{port}'
    print(f'Adaptive Voxelizer: {url}\nPress Ctrl+C in this window to stop.', flush=True)

    def open_when_ready():
        for _ in range(120):
            try:
                with urllib.request.urlopen(url + '/api/health', timeout=1):
                    webbrowser.open(url)
                return
            except OSError:
                time.sleep(.5)

    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    try:
        subprocess.run([interpreter, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT / 'backend', env=env, check=True)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
