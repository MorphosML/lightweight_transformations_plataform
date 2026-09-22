#!/usr/bin/env python3
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure src/ is on python path
src_path = str(Path(__file__).parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)


def open_browser() -> None:
    time.sleep(1.0)
    webbrowser.open("http://127.0.0.1:8000")


def main() -> None:
    if "--tkinter" in sys.argv:
        from openflow_ui.app import main as tkinter_main
        tkinter_main()
        return

    import uvicorn
    from openflow_api.app import app

    print("================================================================")
    print(" OPENFLOW FABRIC STUDIO — MODERN WEB DESKTOP")
    print(" Official Monaco Editor (VS Code Engine) & Chart.js Analytics")
    print(" Opening: http://127.0.0.1:8000")
    print(" (Use '--tkinter' flag for legacy desktop window)")
    print("================================================================")
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
