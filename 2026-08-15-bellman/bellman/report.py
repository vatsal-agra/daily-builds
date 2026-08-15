"""Assembles the self-contained interactive HTML report from a results bundle.

No CDN, no build step: `report_template.html` is a static skeleton with two
placeholders (`__DATA_JSON__` for the run's results, `__APP_JS__` for the
renderer script in `report_app.js`), both filled in and written out as one
plain HTML file.
"""
import json
from pathlib import Path

_HERE = Path(__file__).parent


def build_report(bundle, out_path):
    template = (_HERE / "report_template.html").read_text()
    app_js = (_HERE / "report_app.js").read_text()

    data_json = json.dumps(bundle)
    # A literal "</script>" inside the JSON payload would prematurely close
    # the embedding <script> tag in HTML -- escape it defensively.
    data_json = data_json.replace("</script>", "<\\/script>")

    html = template.replace("__DATA_JSON__", data_json).replace("__APP_JS__", app_js)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path
