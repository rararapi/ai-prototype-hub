"""Real host-loopback HTTP for the sample only; this is not kind evidence."""

import importlib.util
from pathlib import Path
from threading import Thread

import httpx


def test_sample_real_http_has_health_page_and_head():
    source = Path(__file__).resolve().parents[4] / "examples/hello-web/server.py"
    spec = importlib.util.spec_from_file_location("protohub_sample", source)
    sample = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sample)
    server = sample.ThreadingHTTPServer(("127.0.0.1", 0), sample.Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{server.server_port}", timeout=3, trust_env=False
        ) as browser:
            assert browser.get("/healthz").json() == {"app": "hello-web"}
            page = browser.get("/")
            assert page.status_code == 200
            assert "Hello ProtoHub" in page.text and 'id="counter"' in page.text
            assert browser.head("/").content == b""
            assert browser.get("/missing").status_code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
