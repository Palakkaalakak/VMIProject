"""Launcher logic (no real install, no real server)."""
import http.server
import threading

from vmi import launch


def test_deps_installed_once_and_again_when_requirements_change(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    calls = []
    run = lambda cmd: calls.append(cmd) or 0
    assert launch.ensure_deps(tmp_path, run) and len(calls) == 1
    assert launch.ensure_deps(tmp_path, run) and len(calls) == 1            # unchanged: no second install
    (tmp_path / "requirements.txt").write_text("fastapi\nhttpx\n")
    assert launch.ensure_deps(tmp_path, run) and len(calls) == 2


def test_failed_install_is_not_remembered(tmp_path):
    (tmp_path / "requirements.txt").write_text("x\n")
    assert not launch.ensure_deps(tmp_path, lambda cmd: 1)
    calls = []
    assert launch.ensure_deps(tmp_path, lambda cmd: calls.append(cmd) or 0) and calls


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/api/health" else 404)
        self.end_headers()
        self.wfile.write(getattr(self, "body", b"{}"))

    def log_message(self, *a):
        pass


def test_already_running_app_is_detected_and_not_started_twice(monkeypatch):
    from vmi import version as ver
    monkeypatch.setattr(ver, "_CACHE", {"v": "abc1234 2026-11-16 x"})
    _Health.body = b'{"version": "abc1234 2026-11-16 x"}'
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    opened = []
    monkeypatch.setattr(launch.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("started a second server")))
    assert launch.is_up(port)
    assert launch.serve(port) == 0 and opened == [f"http://localhost:{port}"]
    srv.shutdown()


def test_nothing_listening_is_not_up_and_wait_gives_up_when_the_server_dies():
    class Dead:
        def poll(self):
            return 1
    assert not launch.is_up(1)
    assert not launch.wait_until_up(1, Dead(), secs=2, sleep=lambda s: None)


def test_old_copy_on_the_port_is_stopped_before_starting(monkeypatch):
    """The 'Update VMI.bat then still the old screen' bug: an old server kept the port and the launcher just opened it."""
    from vmi import version as ver
    monkeypatch.setattr(ver, "_CACHE", {"v": "new1234 2026-11-16 x"})
    _Health.body = b'{"ok": true}'                                        # old app: no version field
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    stopped = []
    monkeypatch.setattr(launch, "stop_listener", lambda p: stopped.append(p) or False)    # could not stop: reports and exits
    assert launch.serve(port, open_browser=False) == 1 and stopped == [port]
    srv.shutdown()
