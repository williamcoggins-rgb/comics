from http.server import BaseHTTPRequestHandler
import json
import os
import sys

# Add engine directory to path (works both locally and on Vercel)
_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(os.path.dirname(_dir))
sys.path.insert(0, os.path.join(_root, "engine"))
sys.path.insert(0, os.path.join(os.getcwd(), "engine"))

from unified_comics_rules_engine_studio import (
    build_unified_comics_engine,
    generate_specs,
    _priority_from_str,
    FIX_REGISTRY,
)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length))

            seed = body.get("seed", {})
            n = body.get("n", 3)
            apply_fixes = body.get("applyFixes", "suggest")

            engine = build_unified_comics_engine()
            min_pri = _priority_from_str("P1")

            generated = generate_specs(
                engine=engine,
                seed=seed,
                n=max(1, n),
                gate_min_priority=min_pri,
                max_attempts=6,
                apply_fixes_mode=apply_fixes,
                include_results=True,
            )

            result = {
                "mode": "studio",
                "seed": seed,
                "gate": {"min_priority": min_pri.name},
                "generated_specs": generated,
                "fix_registry": {
                    name: cap.value for name, (cap, _) in FIX_REGISTRY.items()
                },
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
