"""Loopback-only UI server. Mesh generation runs through the unchanged JSON CLI."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import uuid
import webbrowser
from urllib.parse import parse_qs, urlsplit

from geometry_mesh.config import CAD_SUFFIXES, validate


ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).with_name("index.html")
VIEWER = ROOT / "viewer.html"
MAX_CAD_BYTES = 50 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
MAX_NAS_BYTES = 100 * 1024 * 1024


def absolute_cad_paths(node: dict) -> None:
    if node.get("kind") == "cad" and isinstance(node.get("path"), str):
        path = Path(node["path"]).expanduser()
        node["path"] = str((path if path.is_absolute() else ROOT / path).resolve())
    for child in node.get("objects", []):
        if isinstance(child, dict):
            absolute_cad_paths(child)


@dataclass
class Job:
    id: str
    comparison: bool = False
    state: str = "running"
    status: str = ""
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    output_directory: str = ""
    nas_path: Path | None = None
    case_paths: dict[str, Path] = field(default_factory=dict)
    report: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {"id": self.id, "comparison": self.comparison, "state": self.state, "status": self.status,
                "error": self.error, "stdout": self.stdout[-4000:],
                "stderr": self.stderr[-4000:], "output_directory": self.output_directory,
                "report": self.report}


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, work_dir: Path | None = None):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.work_dir = work_dir or Path(tempfile.mkdtemp(prefix="brl_mesh_ui_"))
        self.owns_work_dir = work_dir is None
        self.jobs: dict[str, Job] = {}
        self.cad_names: dict[str, str] = {}
        self.lock = threading.Lock()
        self.active: str | None = None
        self.worker: subprocess.Popen | None = None
        self.job_thread: threading.Thread | None = None
        self.closing = False
        self.closing_event = threading.Event()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    def server_close(self) -> None:
        with self.lock:
            self.closing = True
            self.closing_event.set()
            worker = self.worker
            job_thread = self.job_thread
        if worker and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()
        if job_thread and job_thread is not threading.current_thread():
            job_thread.join()
        super().server_close()
        if self.owns_work_dir:
            import shutil
            shutil.rmtree(self.work_dir, ignore_errors=True)

    def start_job(self, config: dict, comparison: bool = False) -> Job:
        with self.lock:
            if self.closing:
                raise RuntimeError("The UI server is shutting down.")
            if self.active is not None:
                raise RuntimeError("A mesh generation is already running.")
            job = Job(uuid.uuid4().hex, comparison=comparison)
            self.jobs[job.id] = job
            self.active = job.id
            thread = threading.Thread(target=self._run_job, args=(job, config), daemon=True)
            self.job_thread = thread
            thread.start()
        return job

    def _run_job(self, job: Job, config: dict) -> None:
        config_path = self.work_dir / f"config_{job.id}.json"
        try:
            with self.lock:
                if self.closing:
                    raise RuntimeError("The UI server shut down before generation started.")
                config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
                proc = subprocess.Popen(
                    [sys.executable, "-m", "geometry_mesh.cli", str(config_path), "--quiet"] + (["--compare"] if job.comparison else []),
                    cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self.worker = proc
            try:
                job.stdout, job.stderr = proc.communicate(timeout=3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise RuntimeError("Mesh generation exceeded the one-hour limit.")
            if proc.returncode not in (0, 2):
                raise RuntimeError(job.stderr.strip() or f"Generator exited with code {proc.returncode}.")
            record = json.loads(job.stdout)
            output = Path(record["output_directory"]).resolve()
            if job.comparison:
                job.report = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
                job.output_directory, job.status = str(output), str(record["status"])
                for case in job.report["cases"]:
                    if case["status"] == "complete" and case["nas"]:
                        candidate = Path(case["output_directory"]) / case["nas"]
                        if candidate.is_file() and candidate.stat().st_size <= MAX_NAS_BYTES:
                            job.case_paths[case["case"]] = candidate
                job.nas_path = job.case_paths.get("combined") or next(iter(job.case_paths.values()), None)
                job.state = "complete"
                return
            report_path = output / "report.json"
            if not report_path.is_file():
                raise RuntimeError("Generation finished without report.json.")
            job.report = json.loads(report_path.read_text(encoding="utf-8"))
            job.output_directory = str(output)
            job.status = str(record["status"])
            if proc.returncode == 2 or job.status != "complete":
                gates = job.report.get("assessment", {}).get("fatal_gates", [])
                detail = "; ".join(map(str, gates)) if gates else "quality checks did not pass"
                job.error = f"Mesh result is invalid ({detail}). See {report_path}. NAS preview is withheld."
                job.state = "error"
                return
            nas_path = output / job.report["artifacts"]["nas"]
            if not nas_path.is_file():
                raise RuntimeError("Generation finished without the expected NAS file.")
            if nas_path.stat().st_size > MAX_NAS_BYTES:
                raise RuntimeError("Generated NAS exceeds the viewer limit (100 MiB).")
            job.nas_path = nas_path
            job.state = "complete"
        except (Exception, subprocess.TimeoutExpired) as exc:
            job.error = str(exc)
            job.state = "error"
        finally:
            config_path.unlink(missing_ok=True)
            with self.lock:
                self.worker = None
                if self.active == job.id:
                    self.active = None


class Handler(BaseHTTPRequestHandler):
    server: AppServer

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}", file=sys.stderr)

    def _valid_host(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def _valid_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin == self.server.origin

    def _authorized(self) -> bool:
        return (self._valid_host() and self._valid_origin()
                and secrets.compare_digest(self.headers.get("X-Session-Token", ""), self.server.token))

    def _send(self, code: int, data: bytes, mime: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, value: dict) -> None:
        self._send(code, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self, limit: int) -> bytes:
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length is required.") from exc
        if length < 1 or length > limit:
            raise ValueError(f"Upload must be between 1 and {limit} bytes.")
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError("Upload ended early.")
        return data

    def do_GET(self) -> None:
        if not self._valid_host():
            self._json(403, {"error": "Invalid host."})
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/":
            html = PAGE.read_text(encoding="utf-8").replace("__SESSION_TOKEN__", self.server.token)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/viewer.html":
            self._send(200, VIEWER.read_bytes(), "text/html; charset=utf-8")
        elif path.startswith("/api/jobs/") and self._authorized():
            job = self.server.jobs.get(path.removeprefix("/api/jobs/"))
            self._json(200, job.public()) if job else self._json(404, {"error": "Job not found."})
        elif path.startswith("/api/results/") and self._authorized():
            job = self.server.jobs.get(path.removeprefix("/api/results/"))
            case = parse_qs(parsed.query).get("case", [None])[0]
            nas_path = (job.case_paths.get(case) if case is not None else job.nas_path) if job else None
            if job and job.state == "complete" and nas_path and nas_path.is_file():
                self._send(200, nas_path.read_bytes(), "text/plain; charset=utf-8")
            else:
                self._json(404, {"error": "NAS result is unavailable."})
        else:
            self._json(403 if path.startswith("/api/") else 404, {"error": "Forbidden or not found."})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(403, {"error": "Invalid session, origin, or host."})
            return
        path = urlsplit(self.path)
        try:
            if path.path == "/api/upload-cad":
                filename = parse_qs(path.query).get("name", [""])[0]
                suffix = Path(filename).suffix.lower()
                if suffix not in CAD_SUFFIXES:
                    raise ValueError("Select a STEP, IGES, or BREP CAD file.")
                data = self._body(MAX_CAD_BYTES)
                upload = self.server.work_dir / f"cad_{uuid.uuid4().hex}{suffix}"
                upload.write_bytes(data)
                self.server.cad_names[str(upload)] = Path(filename.replace("\\", "/")).name
                self._json(200, {"path": str(upload), "name": Path(filename).name})
            elif path.path in {"/api/jobs", "/api/comparisons"}:
                config = json.loads(self._body(MAX_JSON_BYTES))
                if not isinstance(config, dict):
                    raise ValueError("Configuration must be an object.")
                if isinstance(config.get("geometry"), dict):
                    absolute_cad_paths(config["geometry"])
                config = validate(config)
                comparison = path.path == "/api/comparisons"
                if comparison:
                    from geometry_mesh.comparison import configurations
                    configurations(config)
                geometry = config["geometry"]
                if geometry["kind"] == "cad" and config["naming"]["source_name"] is None:
                    config["naming"]["source_name"] = self.server.cad_names.get(geometry["path"])
                output = Path(config["output_dir"]).expanduser()
                if not output.is_absolute():
                    output = ROOT / output
                output = output.resolve()
                output.mkdir(parents=True, exist_ok=True)
                config["output_dir"] = str(output)
                job = self.server.start_job(config, comparison=comparison)
                self._json(202, job.public())
            elif path.path == "/api/shutdown":
                if self.server.active:
                    raise RuntimeError("Wait for generation to finish before stopping the server.")
                self._json(200, {"status": "stopping"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._json(404, {"error": "Not found."})
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the integrated local mesh generator UI")
    parser.add_argument("--no-browser", action="store_true", help="print the URL without opening a browser")
    parser.add_argument("--port", type=int, default=0, help="loopback port (default: choose a free port)")
    args = parser.parse_args(argv)
    with AppServer(args.port) as server:
        print(f"Mesh generator: {server.origin}/", flush=True)
        print("Use the Stop server button or press Ctrl+C in this terminal to shut down.", flush=True)
        if not args.no_browser:
            webbrowser.open(f"{server.origin}/")
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
