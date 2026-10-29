"""Assemble the free GitHub Pages bundle in _pages/: the marketing site at / and the demo-mode dashboard at /demo/."""
import os, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_pages")
shutil.rmtree(OUT, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, "site"), OUT, ignore=shutil.ignore_patterns(".taste-skill", ".DS_Store"))
os.makedirs(os.path.join(OUT, "demo"))
html = open(os.path.join(ROOT, "dashboard.html"), encoding="utf-8").read()
i = html.index("<script>")                      # the dashboard's own script: install the shim before it
html = html[:i] + '<script src="shim.js"></script>\n' + html[i:]
open(os.path.join(OUT, "demo", "index.html"), "w", encoding="utf-8").write(html)
for f in ("shim.js", "demo-data.json"):
    shutil.copy(os.path.join(ROOT, "demo", f), os.path.join(OUT, "demo", f))
open(os.path.join(OUT, ".nojekyll"), "w").close()
print("built", OUT)
