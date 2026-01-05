import subprocess
import webbrowser
import time
import os
import socket
import sys
from pathlib import Path

PORT = 8501

def get_base_dir() -> Path:
    # Quando vira .exe (PyInstaller), use o caminho do executável
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Quando roda como .py, use o caminho do arquivo
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()

VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
APP_PATH = BASE_DIR / "app" / "dashboard.py"
print(VENV_PYTHON)
print(APP_PATH)
def porta_em_uso(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0

if __name__ == "__main__":

    # DEBUG (depois pode remover)
    # print("BASE_DIR:", BASE_DIR)
    # print("VENV_PYTHON:", VENV_PYTHON)
    # print("APP_PATH:", APP_PATH)

    if not VENV_PYTHON.exists():
        raise RuntimeError(
            f"Python do ambiente virtual (.venv) não encontrado em: {VENV_PYTHON}\n"
            f"BASE_DIR resolvido para: {BASE_DIR}\n"
            "Garanta que a pasta .venv esteja AO LADO do .exe (mesma pasta do executável)."
        )

    if not APP_PATH.exists():
        raise RuntimeError(f"App Streamlit não encontrado em: {APP_PATH}")

    if not porta_em_uso(PORT):
        subprocess.Popen(
            [
                str(VENV_PYTHON),
                "-m", "streamlit", "run",
                str(APP_PATH),
                "--server.port", str(PORT),
                "--server.headless=true",
                "--server.runOnSave=false",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=str(BASE_DIR),  # importante: streamlit roda “a partir” do base dir
        )
        time.sleep(2)

    webbrowser.open(f"http://localhost:{PORT}")
