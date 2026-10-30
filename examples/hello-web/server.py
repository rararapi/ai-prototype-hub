"""Trusted stateless demonstration; no credentials, database or external network."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = b"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Hello ProtoHub</title>
<style>body{font:18px system-ui;max-width:650px;margin:10vh auto;padding:24px;background:#eef4fc;
color:#15253d}main{background:white;border-radius:24px;padding:40px}button{font:inherit;padding:12px;
background:#285ed0;color:white;border:0;border-radius:8px}small{color:#52627a}</style>
<main><small>PROTOHUB / TRUSTED SAMPLE</small><h1>Hello ProtoHub</h1>
<p>This app is running in a real sample Pod.</p><button id="counter">Clicked 0 times</button>
<p>Your clicks stay in this browser tab.</p></main><script>
let count=0;document.querySelector('#counter').onclick=(event)=>{
count+=1;event.target.textContent='Clicked '+count+' times'};</script></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            body, content_type = b'{"app":"hello-web"}', "application/json"
        elif self.path == "/":
            body, content_type = PAGE, "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_HEAD = do_GET

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
