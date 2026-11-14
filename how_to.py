"""Read-only help for the actual SchoolFlow menu; no school records are loaded."""
from flask import Blueprint, abort, g, render_template, request, session, url_for
from module_catalog import MENUS, SCHEMAS
from how_to_content import GUIDES, SETTINGS, UTILITY_GUIDES, TOOLS_GUIDES


def configure_how_to(app):
    bp = Blueprint('how_to', __name__, url_prefix='/workspace/how-to')

    def catalogue():
        # Reuse the navigation resolver instead of maintaining invented links.
        menu_url = app.extensions['workspace_menu_url']
        articles = []
        identity = getattr(g, 'school_identity', None) or {}
        private_owner = (not identity.get('demo') and identity.get('scope')
                         and session.get('owner_id') and not session.get('staff_id'))
        for category, groups in MENUS.items():
            for section, items in groups:
                for title, key in items:
                    if key.startswith('general-') and not private_owner:
                        continue
                    # Every menu item must have reviewed instructions. Missing
                    # content is excluded rather than replaced with filler.
                    if key not in GUIDES:
                        continue
                    summary, steps, note = GUIDES[key]
                    articles.append(dict(slug=key, category=category, title=title,
                                         location=' → '.join(filter(None, (category, section, title))),
                                         summary=summary, steps=steps, note=note,
                                         fields=[f[1] for f in SCHEMAS.get(key, [])],
                                         target=menu_url(key)))
        for slug, title, endpoint, args, summary, steps, note in SETTINGS:
            articles.append(dict(slug=slug, category='Configuration', title=title,
                                 location='Configuration → '+title, summary=summary,
                                 steps=steps, note=note, fields=[], target=url_for(endpoint, **args)))
        for slug, title, endpoint, args, summary, steps, note in UTILITY_GUIDES:
            articles.append(dict(slug=slug, category='Communication', title=title, location='Messages → '+title, summary=summary, steps=steps, note=note, fields=[], target=url_for(endpoint, **args)))
        for slug,title,endpoint,args,summary,steps,note in TOOLS_GUIDES:
            articles.append(dict(slug=slug,category='Workspace tools',title=title,location=title,summary=summary,steps=steps,note=note,fields=[],target=url_for(endpoint,**args)))
        articles.insert(0, dict(slug='dashboard', category='Dashboard', title='Dashboard & widgets',
            location='Dashboard', summary='Read school summaries and choose your dashboard widgets.',
            steps=['Open Dashboard to view the summaries available to your account.',
                   'Use General → Widgets to choose cards, change their order and review period filters.',
                   'Open a widget report to inspect the records behind its total.',
                   'Save a personal layout or set the widget dashboard as your default.'],
            note='Unavailable telemetry is labelled; a missing value is not a confirmed zero.',
            fields=[], target=url_for('ops.dashboard')))
        return articles

    @bp.get('')
    def index():
        articles = catalogue()
        categories = list(dict.fromkeys(a['category'] for a in articles))
        category = request.args.get('category', '')
        q = request.args.get('q', '').strip()[:160]
        if category and category not in categories:
            abort(404)
        filtered = [a for a in articles if (not category or a['category'] == category)
                    and (not q or q.casefold() in ' '.join(
                        [a['title'], a['summary'], a['location'], *a['steps'], *a['fields']]).casefold())]
        return render_template('how_to.html', title='How To', articles=filtered,
                               categories=categories, category=category, q=q,
                               counts={c:sum(a['category']==c for a in articles) for c in categories},
                               total=len(articles))

    @bp.get('/<slug>')
    def article(slug):
        articles = catalogue()
        found = next((a for a in articles if a['slug'] == slug), None)
        if found is None:
            abort(404)
        return render_template('how_to_article.html', title=found['title']+' · How To',
                               article=found, related=[a for a in articles
                               if a['category']==found['category'] and a['slug']!=slug][:5])

    app.register_blueprint(bp)
    app.extensions['how_to_catalogue'] = catalogue
