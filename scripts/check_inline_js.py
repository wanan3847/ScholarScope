#!/usr/bin/env python3
"""Extract production template scripts and check each with Node.js."""
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import json

repo = Path(__file__).resolve().parents[1]
dest = repo / "src/tests/ad_hoc/inline_js"
dest.mkdir(parents=True, exist_ok=True)
checked = []


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__(); self.current = None; self.found = []
    def handle_starttag(self, tag, attrs):
        if tag != "script": return
        attrs = dict(attrs)
        if "src" not in attrs and attrs.get("type", "") in ("", "module", "text/javascript", "application/javascript"):
            self.current = {"type": attrs.get("type", ""), "text": ""}
    def handle_data(self, data):
        if self.current is not None: self.current["text"] += data
    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.found.append(self.current); self.current = None


for template in sorted((repo / "src/web/templates").glob("*.html")):
    parser = Scripts(); parser.feed(template.read_text())
    for i, script in enumerate(parser.found, 1):
        output = dest / ("validated-" + template.stem + "-" + str(i) + (".mjs" if script["type"] == "module" else ".js"))
        output.write_text(script["text"])
        subprocess.run(["node", "--check", str(output)], check=True)
        checked.append(str(output.relative_to(repo)))
print(json.dumps({"status": "PASS", "checked": checked}, indent=2))
