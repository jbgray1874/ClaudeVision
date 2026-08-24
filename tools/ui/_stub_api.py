import http.server, socketserver, json, os, urllib.parse
ROOT="/srv/Estimating/Live Enquiry"
FILES=[{"name":f"10575-02-{i:02d}.pdf","path":f"{ROOT}\\10575-02\\10575-02-{i:02d}.pdf",
        "is_dir":False,"ext":".pdf","size_bytes":120000,"modified":0} for i in range(1,6)]
LOGO=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><circle cx="20" cy="20" r="18" fill="#F5D947"/></svg>'
class H(http.server.SimpleHTTPRequestHandler):
    def _j(self,obj):
        b=json.dumps(obj).encode(); self.send_response(200)
        self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p=urllib.parse.urlparse(self.path)
        if p.path=="/api/brand/logo":
            self.send_response(200); self.send_header("Content-Type","image/svg+xml")
            self.send_header("Content-Length",str(len(LOGO))); self.end_headers(); self.wfile.write(LOGO); return
        if p.path=="/api/roots": return self._j({"roots":[{"name":"Live Enquiry","path":ROOT}]})
        if p.path=="/api/files": return self._j({"path":ROOT,"items":FILES})
        if p.path=="/api/estimate/runners": return self._j({"runners":[]})
        if p.path=="/api/estimate/dm/status": return self._j({"configured":False,"reason":"not set"})
        if p.path.startswith("/api/"): return self._j({})
        return super().do_GET()
    def log_message(self,*a): pass
socketserver.TCPServer.allow_reuse_address=True
with socketserver.TCPServer(("127.0.0.1",8098),H) as h: h.serve_forever()
