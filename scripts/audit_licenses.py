#!/usr/bin/env python3
"""Inventory exact installed dependencies and retain their license texts."""
from __future__ import annotations
import importlib.metadata as metadata
import json
import re
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

repo = Path(__file__).resolve().parents[1]
out = repo / "docs/implementation/dependency-licenses.json"
notices_path = repo / "frontend/public/brand/THIRD_PARTY_NOTICES.txt"
python, seen, missing = [], set(), []
notices = []


def inspect_python(name, extras=()):
    key = canonicalize_name(name)
    if key in seen: return
    seen.add(key)
    try: dist = metadata.distribution(name)
    except metadata.PackageNotFoundError: missing.append(name); return
    meta = dist.metadata
    license_text = meta.get("License-Expression") or meta.get("License", "")
    classifiers = [v.split(" :: ")[-1] for v in meta.get_all("Classifier", []) if v.startswith("License ::")]
    license_name = license_text if len(license_text) < 150 else "; ".join(classifiers)
    texts = []
    for f in dist.files or []:
        if re.search(r"(?:^|/)(?:LICEN[SC]E|COPYING|NOTICE)(?:[._-].*)?$", str(f), re.I):
            path = dist.locate_file(f)
            try: text = path.read_text(errors="replace")
            except (OSError, UnicodeError): continue
            if len(text) < 500000:
                texts.append(str(f)); notices.append(f"\n\n===== Python: {meta['Name']} {dist.version} / {f} =====\n" + text)
    python.append({"name": meta["Name"], "version": dist.version, "license": license_name or "; ".join(classifiers) or "See packaged license text", "license_files": texts,
        "project_urls": meta.get_all("Project-URL", [])})
    for value in dist.requires or []:
        req = Requirement(value)
        if req.marker and not any(req.marker.evaluate({"extra": extra}) for extra in ("", *extras)): continue
        inspect_python(req.name, req.extras)


for line in (repo / "src/requirements.txt").read_text().splitlines():
    line = line.split("#", 1)[0].strip()
    if line and not line.startswith("-"):
        req = Requirement(line)
        if not req.marker or req.marker.evaluate(): inspect_python(req.name, req.extras)

npm = []
lock = json.loads((repo / "frontend/package-lock.json").read_text())
for package_path, info in lock["packages"].items():
    if not package_path: continue
    name = package_path.rsplit("node_modules/", 1)[-1]
    package = repo / "frontend" / package_path
    npm.append({"name": name, "version": info["version"], "license": info.get("license", "See packaged license text"), "dev": bool(info.get("dev")), "optional": bool(info.get("optional"))})
    if package.exists():
        for f in package.iterdir():
            if f.is_file() and re.fullmatch(r"(?:LICEN[SC]E|COPYING|NOTICE)(?:[._-].*)?", f.name, re.I):
                notices.append(f"\n\n===== JavaScript: {name} {info['version']} / {f.name} =====\n" + f.read_text(errors="replace"))
out.write_text(json.dumps({"audit_date": "2026-10-14", "python": sorted(python, key=lambda d: d["name"].lower()), "npm": sorted(npm, key=lambda d: d["name"]), "missing_installed_requirements": missing}, ensure_ascii=False, indent=2))
notices_path.parent.mkdir(parents=True, exist_ok=True)
notices_path.write_text("ScholarScope third-party dependency notices\nExact installed versions are recorded in docs/implementation/dependency-licenses.json.\n" + "".join(notices))
print(json.dumps({"python_packages": len(python), "npm_packages": len(npm), "missing_installed_requirements": missing}, ensure_ascii=False))
