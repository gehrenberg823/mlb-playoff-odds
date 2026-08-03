#!/usr/bin/env python3
"""Local server for the MLB playoff-odds board with a Refresh button.

Serves docs/index.html and re-runs the pipeline (python3 -m src.run) on
POST /refresh. The refresh button in the page only shows itself when served
from localhost, so the GitHub Pages copy is unaffected.

Run: python3 app.py   → http://127.0.0.1:5066
"""
import os
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
PORT = 5066

app = Flask(__name__)
_lock = threading.Lock()


@app.get("/")
def index():
    return send_from_directory(DOCS, "index.html")


@app.post("/refresh")
def refresh():
    if not _lock.acquire(blocking=False):
        return jsonify(ok=False, output="A refresh is already running."), 409
    try:
        t0 = time.time()
        # FanGraphs scrape (5 sources, curl_cffi + retries) dominates runtime.
        proc = subprocess.run(
            [sys.executable, "-m", "src.run"],
            capture_output=True, text=True, timeout=600, cwd=HERE,
        )
        out = proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")
        return jsonify(ok=proc.returncode == 0, output=out.strip(),
                       seconds=round(time.time() - t0, 1)), (200 if proc.returncode == 0 else 500)
    except subprocess.TimeoutExpired:
        return jsonify(ok=False, output="src.run timed out after 600s."), 500
    finally:
        _lock.release()


if __name__ == "__main__":
    print(f"MLB playoff odds board → http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False)
