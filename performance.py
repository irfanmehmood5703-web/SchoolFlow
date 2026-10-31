"""Cache only content-versioned public assets; private school responses stay no-store."""
import hashlib
from pathlib import Path
from time import perf_counter
from flask import g, request, url_for


def configure_performance(app):
    versions = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                for p in Path(app.static_folder).iterdir() if p.is_file() and p.suffix in {'.css', '.js'}}

    @app.context_processor
    def assets():
        return {'asset_url': lambda filename: url_for('static', filename=filename, v=versions.get(filename))}

    @app.before_request
    def begin_request():
        g.request_started = perf_counter()

    @app.after_request
    def public_asset_cache(response):
        if request.endpoint == 'static' and response.status_code in (200, 304):
            filename = (request.view_args or {}).get('filename')
            if filename in versions and request.args.get('v') == versions[filename]:
                response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        if hasattr(g, 'request_started'):
            response.headers['Server-Timing'] = f'app;dur={(perf_counter()-g.request_started)*1000:.1f}'
        return response
