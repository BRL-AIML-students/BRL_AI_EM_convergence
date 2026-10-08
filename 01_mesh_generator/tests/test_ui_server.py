from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from mesh_ui.server import AppServer, absolute_cad_paths


@contextmanager
def running_server(tmp_path: Path):
    server = AppServer(0, tmp_path / "session")
    server.work_dir.mkdir()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def request(server: AppServer, path: str, *, method="GET", body=None, token=True, origin=True):
    headers = {}
    if token:
        headers["X-Session-Token"] = server.token
    if origin:
        headers["Origin"] = server.origin
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body).encode("utf-8")
    req = Request(server.origin + path, data=body, method=method, headers=headers)
    try:
        with urlopen(req, timeout=10) as response:
            data = response.read()
            return response.status, data
    except HTTPError as exc:
        return exc.code, exc.read()


def config(output: Path) -> dict:
    return {
        "version": 1, "name": "ui_integration", "output_dir": str(output),
        "length_unit": "mm", "output_unit": "mm",
        "geometry": {"kind": "plate", "parameters": {"length": 10, "width": 10}},
        "mesh": {"mode": "auto", "scale_fraction": 0.3,
                 "wave": {"enabled": True, "frequency_hz": 1e9,
                          "elements_per_wavelength": 10,
                          "relative_permittivity": 1, "relative_permeability": 1},
                 "local": {"enabled": False}},
    }


def wait_for_job(server: AppServer, job_id: str) -> dict:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        code, data = request(server, "/api/jobs/" + job_id)
        assert code == 200
        job = json.loads(data)
        if job["state"] != "running":
            return job
        time.sleep(0.1)
    pytest.fail("mesh generation did not complete within 60 seconds")


def test_server_generates_and_serves_nas(tmp_path: Path):
    with running_server(tmp_path) as server:
        code, html = request(server, "/", token=False, origin=False)
        assert code == 200 and server.token.encode() in html
        assert b"/viewer.html" in html
        code, viewer = request(server, "/viewer.html", token=False, origin=False)
        assert code == 200 and b"parseNAS" in viewer
        code, data = request(server, "/api/jobs", method="POST", body=config(tmp_path / "한글 mesh results"))
        assert code == 202, data
        job = wait_for_job(server, json.loads(data)["id"])
        assert job["state"] == "complete", job
        assert job["report"]["configuration"]["mesh"]["wave"]["frequency_hz"] == 1e9
        code, nas = request(server, "/api/results/" + job["id"])
        assert code == 200 and b"GRID" in nas and b"CTRIA3" in nas and b"ENDDATA" in nas
        assert Path(job["output_directory"], "ui_integration.nas").read_bytes() == nas


def test_server_uses_report_automatic_name(tmp_path: Path):
    cfg = config(tmp_path / "automatic")
    cfg["naming"] = {"automatic": True}
    with running_server(tmp_path) as server:
        code, data = request(server, "/api/jobs", method="POST", body=cfg)
        assert code == 202
        job = wait_for_job(server, json.loads(data)["id"])
        assert job["state"] == "complete", job
        assert job["report"]["artifacts"]["nas"].startswith("plate_L10_W10_mm_hMin")
        code, nas = request(server, "/api/results/" + job["id"])
        assert code == 200
        assert (Path(job["output_directory"]) / job["report"]["artifacts"]["nas"]).read_bytes() == nas


def test_server_rejects_invalid_requests_and_reports_worker_error(tmp_path: Path, monkeypatch):
    with running_server(tmp_path) as server:
        code, _ = request(server, "/api/jobs", method="POST", body=config(tmp_path / "results"), token=False)
        assert code == 403
        bad = config(tmp_path / "results")
        bad["mesh"]["wave"]["frequency_hz"] = -1
        code, data = request(server, "/api/jobs", method="POST", body=bad)
        assert code == 400 and b"frequency_hz" in data
        code, _ = request(server, "/api/upload-cad?name=bad.exe", method="POST", body={"x": 1})
        assert code == 400
        code, _ = request(server, "/private-file")
        assert code == 404
        upload = Request(server.origin + "/api/upload-cad?name=%ED%95%9C%EA%B8%80%20part.step",
                         data=b"ISO-10303-21;", method="POST",
                         headers={"X-Session-Token": server.token, "Origin": server.origin})
        with urlopen(upload, timeout=10) as response:
            uploaded = json.loads(response.read())
        assert uploaded["name"] == "한글 part.step"
        assert Path(uploaded["path"]).read_bytes() == b"ISO-10303-21;"
        class FailedWorker:
            returncode = 1

            def communicate(self, timeout):
                return "", "Gmsh failed to import CAD"

        monkeypatch.setattr("mesh_ui.server.subprocess.Popen", lambda *args, **kwargs: FailedWorker())
        code, data = request(server, "/api/jobs", method="POST", body=config(tmp_path / "results"))
        assert code == 202
        job = wait_for_job(server, json.loads(data)["id"])
        assert job["state"] == "error"
        assert "Gmsh failed to import CAD" in job["error"]


def test_invalid_quality_result_keeps_report_path(tmp_path: Path, monkeypatch):
    output = tmp_path / "invalid result"
    output.mkdir()
    (output / "report.json").write_text(json.dumps({"assessment": {"fatal_gates": ["inverted element"]}}))

    class InvalidWorker:
        returncode = 2

        def communicate(self, timeout):
            return json.dumps({"status": "invalid", "output_directory": str(output)}), ""

    monkeypatch.setattr("mesh_ui.server.subprocess.Popen", lambda *args, **kwargs: InvalidWorker())
    with running_server(tmp_path) as server:
        code, data = request(server, "/api/jobs", method="POST", body=config(tmp_path / "results"))
        assert code == 202
        job = wait_for_job(server, json.loads(data)["id"])
        assert job["state"] == "error" and job["status"] == "invalid"
        assert job["output_directory"] == str(output)
        assert "inverted element" in job["error"] and "report.json" in job["error"]
        assert job["report"]["assessment"]["fatal_gates"] == ["inverted element"]


def test_relative_cad_path_is_resolved_before_worker_config(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mesh_ui.server.ROOT", tmp_path)
    geometry = {"kind": "cut", "objects": [{"kind": "cad", "path": "한글 part.step"},
                                              {"kind": "sphere", "parameters": {"radius": 1}}]}
    absolute_cad_paths(geometry)
    assert geometry["objects"][0]["path"] == str((tmp_path / "한글 part.step").resolve())


def test_close_before_worker_start_prevents_launch_and_waits_for_thread(tmp_path: Path, monkeypatch):
    server = AppServer(0)
    entered = threading.Event()
    release = threading.Event()
    launched = threading.Event()
    original_run = server._run_job

    def delayed_run(job, configuration):
        entered.set()
        assert release.wait(5)
        original_run(job, configuration)

    def forbidden_launch(*args, **kwargs):
        launched.set()
        raise AssertionError("worker launched after server close")

    monkeypatch.setattr(server, "_run_job", delayed_run)
    monkeypatch.setattr("mesh_ui.server.subprocess.Popen", forbidden_launch)
    job = server.start_job(config(tmp_path / "results"))
    closer = threading.Thread(target=server.server_close)
    try:
        assert entered.wait(5)
        closer.start()
        assert server.closing_event.wait(5)
        assert server.work_dir.exists()  # Cleanup waits for the queued worker thread.
        release.set()
        closer.join(timeout=5)
        assert not closer.is_alive()
        assert not launched.is_set()
        assert not server.work_dir.exists()
        assert job.state == "error" and "shut down before generation" in job.error
        with pytest.raises(RuntimeError, match="shutting down"):
            server.start_job(config(tmp_path / "results"))
    finally:
        release.set()
        if closer.is_alive():
            closer.join(timeout=5)
        if not server.closing:
            server.server_close()
