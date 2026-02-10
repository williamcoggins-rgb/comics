from http.server import BaseHTTPRequestHandler
from dataclasses import asdict
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
    _priority_from_str,
    _summarize,
    gate_results,
    apply_safe_autofixes,
    collect_suggestions,
    FIX_REGISTRY,
)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length))

            spec = body.get("spec")
            if not spec:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "spec is required"}).encode())
                return

            apply_fixes = body.get("applyFixes", "suggest")
            full_report = body.get("fullReport", False)

            engine = build_unified_comics_engine()
            min_pri = _priority_from_str("P1")

            results = engine.evaluate(
                spec, stop_on_first_failing_priority=(not full_report)
            )

            if apply_fixes in {"safe", "suggest"}:
                apply_safe_autofixes(spec, results)
                if apply_fixes == "suggest":
                    collect_suggestions(spec, results)
                results = engine.evaluate(
                    spec, stop_on_first_failing_priority=(not full_report)
                )

            summary = _summarize(results)
            ok, gate_message = gate_results(results, min_pri)

            result = {
                "mode": "critic",
                "summary": summary,
                "results": [asdict(r) for r in results],
                "gate": {
                    "min_priority": min_pri.name,
                    "ok": ok,
                    "message": gate_message,
                },
                "suggestions": spec.get("suggestions", {})
                if apply_fixes == "suggest"
                else {},
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
