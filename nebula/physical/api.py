#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
import io
import json
import os
import re
import signal
import subprocess
import zipfile
from typing import Dict, List, Optional, Set

from flask import (
    Flask,
    abort,
    jsonify,
    request,
    send_file,
)

# ──────────────────────────────  GLOBAL CONFIG  ──────────────────────────────

app = Flask(__name__)

CERTS_FOLDER   = "./app/certs/"
CONFIG_FOLDER  = "./app/config/"
LOGS_FOLDER    = "./app/logs/"
METRICS_FOLDER = "./app/logs/metrics/"

CONFIG_FILE_COUNT  = 1          # Exactly one *.json* per run
DATASET_FILE_COUNT = 2          # Exactly two *.h5* per run

# Current training subprocess (None ⇢ not running)
TRAINING_PROC: Optional[subprocess.Popen] = None

# ──────────────────────────────  HELPER ROUTINES  ────────────────────────────
def _find_x_files(folder: str, extension: str = ".json") -> List[str]:
    """
    Return *all* files inside *folder* ending with *extension*.

    The check is non-recursive on purpose – the project stores every run in a
    dedicated directory with a flat layout.
    """
    return [
        os.path.join(folder, fn)
        for fn in os.listdir(folder)
        if fn.endswith(extension)
    ]


def _LFI_sentry(path: str) -> bool:
    """
    Very strict Local-File-Inclusion guard.

    Returns **True** when *path* is unsafe (attempted path traversal or the
    referenced folder does not exist), **False** otherwise.
    """
    forbidden_tokens = (
        "", "..", "/", "\\", "~", "*", "?", ":", "<", ">", "|", '"', "'", "`",
        "$", "%", "&", "!", "{", "}", "[", "]", "@", "#", "+", "=", ";", ",",
        " ", "\t", "\n", "\r", "\f", "\v",
    )
    return (
        not os.path.exists(os.path.join(CONFIG_FOLDER, path))
        or any(tok in path for tok in forbidden_tokens)
    )


def _json_abort(code: int, msg: str) -> None:
    """Abort the current request emitting a JSON payload: `{"detail": msg}`."""
    response = jsonify({"detail": msg})
    response.status_code = code
    abort(response)

# ────────────────────────────────  END-POINTS  ───────────────────────────────
# ———————————————————————————————  CONFIG  ————————————————————————————————

@app.route("/config/", methods=["GET"])
def get_config():
    """Return the single *.json* config file for the requested run."""
    path = request.args.get("path", "")
    if _LFI_sentry(path):
        _json_abort(404, "Item not found")

    json_files = _find_x_files(os.path.join(CONFIG_FOLDER, path))
    if len(json_files) != CONFIG_FILE_COUNT:
        _json_abort(404, "Item not found")

    return send_file(json_files.pop(), mimetype="application/json",
                     as_attachment=True)


@app.route("/config/", methods=["PUT"])
def set_config():
    """Upload a config *.json* for the provided run directory."""
    if "config" not in request.files:
        _json_abort(400, "Missing file field 'config'")

    path = request.args.get("path", "")
    if _LFI_sentry(path):
        _json_abort(404, "Item not found")

    os.makedirs(os.path.join(CONFIG_FOLDER, path), exist_ok=True)

    uploaded = request.files["config"]
    dst = os.path.join(CONFIG_FOLDER, path, uploaded.filename)
    uploaded.save(dst)

    return jsonify(filename=uploaded.filename), 201


@app.route("/config/", methods=["DELETE"])
def delete_config():
    """Remove the config *.json* from the given run directory."""
    path = request.args.get("path", "")
    if _LFI_sentry(path):
        _json_abort(404, "Item not found")

    json_files = _find_x_files(os.path.join(CONFIG_FOLDER, path))
    if len(json_files) != CONFIG_FILE_COUNT:
        _json_abort(404, "Item not found")

    fn = json_files.pop()
    os.remove(fn)
    return jsonify(filename=fn)

# ———————————————————————————————  DATASET  ————————————————————————————————

@app.route("/dataset/", methods=["GET"])
def get_dataset():
    """
    Deliver both *.h5* datasets as a single ZIP archive.

    Returning a single payload simplifies transfer, cache-control and client
    code compared to sending two independent responses.
    """
    path = request.args.get("path", "")
    if _LFI_sentry(path):
        _json_abort(404, "Item not found")

    h5_files = _find_x_files(os.path.join(CONFIG_FOLDER, path), ".h5")
    if len(h5_files) != DATASET_FILE_COUNT:
        _json_abort(404, "Item not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in h5_files:
            zf.write(f, arcname=os.path.basename(f))
    buf.seek(0)

    return send_file(buf, mimetype="application/zip",
                     download_name="dataset.zip", as_attachment=True)


@app.route("/dataset/", methods=["PUT"])
def set_dataset():
    """Upload the pair of train/test *.h5* files for a run."""
    missing = [fld for fld in ("dataset", "dataset_p") if fld not in request.files]
    if missing:
        _json_abort(400, f"Missing file field(s): {', '.join(missing)}")

    path = request.args.get("path", "")
    if _LFI_sentry(path):
        _json_abort(404, "Item not found")

    os.makedirs(os.path.join(CONFIG_FOLDER, path), exist_ok=True)
    stored: List[str] = []

    for fld in ("dataset", "dataset_p"):
        up = request.files[fld]
        dst = os.path.join(CONFIG_FOLDER, path, up.filename)
        up.save(dst)
        stored.append(up.filename)

    return jsonify(stored), 201


@app.route("/dataset/", methods=["DELETE"])
def delete_dataset():
    """Delete both dataset *.h5* files from the specified run directory."""
    path = request.args.get("path", "")
    if _LFI_sentry(path):
        _json_abort(404, "Item not found")

    data_files = _find_x_files(os.path.join(CONFIG_FOLDER, path), ".h5")
    if len(data_files) != DATASET_FILE_COUNT:
        _json_abort(404, "Item not found")

    removed: Dict[str, str] = {}
    for fn in data_files:
        os.remove(fn)
        removed[fn] = "deleted"
    return jsonify(removed)

# ————————————————————————————————  CERTS  ————————————————————————————————

@app.route("/certs/", methods=["GET"])
def get_certs():
    """Download every *.cert* file in a ZIP archive."""
    certs_files = _find_x_files(CERTS_FOLDER, ".cert")
    if not certs_files:
        _json_abort(404, "No cert files found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in certs_files:
            zf.write(f, arcname=os.path.basename(f))
    buf.seek(0)

    return send_file(buf, mimetype="application/zip",
                     download_name="certs.zip", as_attachment=True)


@app.route("/certs/", methods=["PUT"])
def set_cert():
    """Upload one *.cert* file to the global certificates folder."""
    if "cert" not in request.files:
        _json_abort(400, "Missing file field 'cert'")

    uploaded = request.files["cert"]
    dst = os.path.join(CERTS_FOLDER, uploaded.filename)
    uploaded.save(dst)

    return jsonify(filename=uploaded.filename), 201


@app.route("/certs/", methods=["DELETE"])
def delete_certs():
    """Remove **all** certificate files from the system."""
    certs_files = _find_x_files(CERTS_FOLDER, ".cert")
    removed: Dict[str, str] = {}
    for fn in certs_files:
        os.remove(fn)
        removed[fn] = "deleted"
    return jsonify(removed)

# ————————————————————————————————  LOGS  ————————————————————————————————

def _send_single_log(path: str, pattern: str):
    """Return the shortest matching log file inside *path*."""
    log_files = _find_x_files(path, pattern)
    if not log_files:
        _json_abort(404, "Log file not found")

    target = min(log_files, key=lambda x: len(os.path.basename(x)))
    return send_file(target, mimetype="text/plain", as_attachment=True)

@app.route("/get_logs/", methods=["GET"])
def get_logs():
    """Download the main *.log* produced during training."""
    path = request.args.get("path", "")
    if _LFI_sentry(path):
        _json_abort(404, "Item not found")
    return _send_single_log(os.path.join(LOGS_FOLDER, path), ".log")


@app.route("/get_logs/", methods=["DELETE"])
def delete_logs():
    """Delete the main *.log* for the requested run."""
    path = request.args.get("path", "")
    if _LFI_sentry(path):
        _json_abort(404, "Item not found")

    log_files = _find_x_files(os.path.join(LOGS_FOLDER, path), ".log")
    if not log_files:
        _json_abort(404, "Log file not found")

    target = min(log_files, key=lambda x: len(os.path.basename(x)))
    os.remove(target)
    return jsonify(filename=target)


# Create *dedicated* GET+DELETE routes for debug/error/training logs
def _log_route(route_name: str, filename: str) -> None:
    """
    Register two URL rules:

      • **GET  /get_logs/<route_name>/**  → download the file
      • **DELETE /get_logs/<route_name>/** → delete the file
    """
    def _getter():
        path = request.args.get("path", "")
        if _LFI_sentry(path):
            _json_abort(404, "Item not found")
        return _send_single_log(os.path.join(LOGS_FOLDER, path), filename)

    def _deleter():
        path = request.args.get("path", "")
        if _LFI_sentry(path):
            _json_abort(404, "Item not found")

        files = _find_x_files(os.path.join(LOGS_FOLDER, path), filename)
        if not files:
            _json_abort(404, "Log file not found")

        target = files.pop()
        os.remove(target)
        return jsonify(filename=target)

    # `endpoint` must be unique – build one from the route name + HTTP verb
    app.add_url_rule(
        f"/get_logs/{route_name}/",
        endpoint=f"get_logs_{route_name}_get",
        view_func=_getter,
        methods=["GET"],
    )
    app.add_url_rule(
        f"/get_logs/{route_name}/",
        endpoint=f"get_logs_{route_name}_del",
        view_func=_deleter,
        methods=["DELETE"],
    )

for _name in ("debug", "error", "training"):
    _log_route(_name, f"{_name}.log")

# ————————————————————————————————  METRICS  ————————————————————————————————

@app.route("/metrics/", methods=["GET"])
def get_metrics():
    """Bundle every file under *METRICS_FOLDER* into a ZIP archive."""
    log_files = _find_x_files(METRICS_FOLDER, "")
    if not log_files:
        _json_abort(404, "Log file not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in log_files:
            zf.write(f, arcname=os.path.basename(f))
    buf.seek(0)

    return send_file(buf, mimetype="application/zip",
                     download_name="metrics.zip", as_attachment=True)

# ————————————————————————————————  ACTIONS  ————————————————————————————————

@app.route("/run/", methods=["GET"])
def run():
    """
    Spawn the federated training process (once).

    Returns
    -------
    JSON {pid, state}
    """
    json_files = _find_x_files(CONFIG_FOLDER)
    if len(json_files) != CONFIG_FILE_COUNT:
        _json_abort(404, "Config file not found")

    global TRAINING_PROC
    if TRAINING_PROC and TRAINING_PROC.poll() is None:
        _json_abort(409, "Training already running")

    cmd = ["python", "/home/dietpi/prueba/nebula/nebula/node.py", json_files[0]]
    TRAINING_PROC = subprocess.Popen(cmd)

    return jsonify(pid=TRAINING_PROC.pid, state="running")


@app.route("/stop/", methods=["GET"])
def stop():
    """Terminate the running training process (SIGTERM) and wait for it."""
    global TRAINING_PROC
    if not TRAINING_PROC or TRAINING_PROC.poll() is not None:
        _json_abort(404, "No training running")

    TRAINING_PROC.send_signal(signal.SIGTERM)
    TRAINING_PROC.wait()
    pid = TRAINING_PROC.pid
    TRAINING_PROC = None

    return jsonify(pid=pid, state="stopped")

# ———————————————————————  SETUP – UPLOAD 3 FILES  ————————————————————————

@app.route("/setup/", methods=["PUT"])
def setup_new_run():
    """
    Prepare a **new** federated-learning round.

    Expected multipart-form fields
    -------------------------------
    * **config**     – JSON with scenario, network and security arguments  
    * **global_test** – shared evaluation dataset (`*.h5`)  
    * **train_set**   – participant-specific training dataset (`*.h5`)

    The function rewrites paths inside *config*, validates neighbour IPs
    through Tailscale, deletes previous artefacts and finally stores the new
    trio of files.
    """
    # 1 · Refuse while a training task is still running
    global TRAINING_PROC
    if TRAINING_PROC and TRAINING_PROC.poll() is None:
        _json_abort(409, "Training already running; pause or stop it first.")

    # 2 · Check field presence
    missing = [x for x in ("config", "global_test", "train_set")
               if x not in request.files]
    if missing:
        _json_abort(400, f"Missing file field(s): {', '.join(missing)}")

    config_up   = request.files["config"]
    global_test = request.files["global_test"]
    train_set   = request.files["train_set"]

    # 3 · Extension sanity
    if not config_up.filename.endswith(".json"):
        _json_abort(400, f"`{config_up.filename}` must have a .json extension.")
    for ds in (global_test, train_set):
        if not ds.filename.endswith(".h5"):
            _json_abort(400, f"`{ds.filename}` must have a .h5 extension.")

    # 4 · Parse + patch JSON
    try:
        original_cfg = json.load(config_up)
    except Exception as exc:  # broad – any parsing failure should abort
        _json_abort(400, f"Invalid JSON file: {exc}")

    # Update tracking / security paths to local folders
    tracking = original_cfg.get("tracking_args", {})
    tracking["log_dir"]    = LOGS_FOLDER.rstrip("/")
    tracking["config_dir"] = CONFIG_FOLDER.rstrip("/")
    original_cfg["tracking_args"] = tracking

    sec = original_cfg.get("security_args", {})
    for key in ("certfile", "keyfile", "cafile"):
        if key in sec and sec[key]:
            sec[key] = os.path.join(CERTS_FOLDER.rstrip("/"),
                                    os.path.basename(sec[key]))
    original_cfg["security_args"] = sec

    # 5 · (May be removed) Check neighbour reachability via Tailscale
    neigh_str = original_cfg.get("network_args", {}).get("neighbors", "").strip()
    requested_ips: Set[str] = {re.split(r":", n)[0] for n in neigh_str.split() if n}

    if requested_ips:
        try:
            ts_out = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, check=True,
            )
            ts_status = json.loads(ts_out.stdout)
            reachable: Set[str] = set(ts_status.get("Self", {}).get("TailscaleIPs", []))
            for peer in ts_status.get("Peer", {}).values():
                reachable.update(peer.get("TailscaleIPs", []))
        except Exception as exc:
            _json_abort(400, f"Could not verify neighbours via Tailscale: {exc}")

        missing = sorted(ip for ip in requested_ips if ip not in reachable)
        if missing:
            _json_abort(400, f"Neighbour IP(s) not reachable: {', '.join(missing)}")

    # 6 · Clean previous JSON/H5 artefacts
    for fn in os.listdir(CONFIG_FOLDER):
        if fn.endswith((".json", ".h5")):
            try:
                os.remove(os.path.join(CONFIG_FOLDER, fn))
            except OSError:
                pass
    if any(fn.endswith((".json", ".h5")) for fn in os.listdir(CONFIG_FOLDER)):
        _json_abort(400, "Could not delete old JSON/H5 files.")

    # 7 · Persist patched JSON
    json_dest = os.path.join(CONFIG_FOLDER, config_up.filename)
    with open(json_dest, "wb") as dst:
        dst.write(json.dumps(original_cfg, indent=2).encode())

    # 8 · Persist datasets
    saved = [config_up.filename]
    for up in (global_test, train_set):
        dst = os.path.join(CONFIG_FOLDER, up.filename)
        up.save(dst)
        saved.append(up.filename)

    # 9 · Purge previous log files
    for root, _, files in os.walk(LOGS_FOLDER):
        for fn in files:
            if fn.endswith(".log"):
                try:
                    os.remove(os.path.join(root, fn))
                except OSError:
                    pass
    if any(fn.endswith(".log") for _, _, fns in os.walk(LOGS_FOLDER) for fn in fns):
        _json_abort(400, "Could not delete old log files.")

    return jsonify(saved), 201

# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY-POINT
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Local testing:  python main.py
    app.run(host="0.0.0.0", port=8000, debug=False)