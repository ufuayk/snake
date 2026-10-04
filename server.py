import json, os, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import laya_mlx as laya

ROOT = Path(__file__).parent
MODEL = os.environ.get("LAYA_MODEL", "aac6fef/laya-mlx")
NUM = (int, float)
LOCK = threading.Lock()

try:
    AGENT = laya.load(MODEL, compile=True, pad_to_multiple=16, cache_prompts=True)
except TypeError:
    AGENT = laya.load(MODEL)

def question(instr, crit):
    return {"move": {"type": "choice", "instructions": instr, "criteria": crit}}

for n in (2, 3, 2, 3):
    AGENT.predict("Snake 20x20. Head (10,10) heading right. Length 5. Apple 3 right, 2 down. Hungry 4 steps.",
                  question("Which move reaches the apple soon and stays alive?",
                           [f"Move {d}: apple {i + 2} steps away" for i, d in enumerate(["up", "down", "left"][:n])]))

def find_probs(o, keys):
    """predict() şeması belgelenmediği için olasılıkları toleranslı ara."""
    if isinstance(o, dict):
        if all(isinstance(o.get(k), NUM) for k in keys):
            return {k: float(o[k]) for k in keys}
        for v in o.values():
            r = find_probs(v, keys)
            if r: return r
    elif isinstance(o, list):
        if len(o) == len(keys) and all(isinstance(x, NUM) for x in o):
            return dict(zip(keys, map(float, o)))
        m = {}
        for x in o:
            if isinstance(x, dict):
                lab = next((x[f] for f in ("label", "criterion", "name", "option") if x.get(f) in keys), None)
                p = next((x[f] for f in ("probability", "prob", "score") if isinstance(x.get(f), NUM)), None)
                if lab is not None and p is not None: m[lab] = float(p)
        if len(m) == len(keys): return m
        for v in o:
            r = find_probs(v, keys)
            if r: return r
    elif isinstance(o, str) and o in keys:
        return {k: 1.0 if k == o else 0.0 for k in keys}
    return None

def norm(p):
    s = sum(max(v, 0) for v in p.values()) or 1
    return {k: max(v, 0) / s for k, v in p.items()}

def decide(b):
    keys, t = b["criteria"], time.perf_counter()
    with LOCK:
        res = AGENT.predict(b["state"], question(b["instructions"], keys))
    raw = res.get("answers", res) if isinstance(res, dict) else res
    p = find_probs(raw, keys)
    parsed = p is not None
    probs = norm(p) if p else {k: 1 / len(keys) for k in keys}
    return {"probs": probs, "parsed": parsed, "ms": round((time.perf_counter() - t) * 1000, 1)}

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a): pass

    def _send(self, data, ctype="application/json", code=200):
        if not isinstance(data, bytes): data = json.dumps(data).encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/info": return self._send({"mock": False})
        self._send((ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self._send(decide(body))
        except Exception as e:
            self._send({"error": str(e)}, code=500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    print(f"Ready · {MODEL} · http://127.0.0.1:{port}")
    threading.Timer(.4, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()