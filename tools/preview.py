#!/usr/bin/env python3
"""Render the real interface with fictional data; never loads saved accounts."""
import json
import os
from pathlib import Path
import runpy
import sys
import time
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Graphene', '1.0')
from gi.repository import Adw, Gtk, GLib, Graphene

ROOT = Path(__file__).resolve().parents[1]
source = Path(os.environ.get('ACCOUNT_CENTER_PREVIEW_SOURCE', ROOT / 'src/codex-acc'))
mod = runpy.run_path(str(source), run_name='account_center_preview')
g = mod['run_gui'].__globals__
plans = ['PRO', 'PLUS', 'FREE']
accounts = [dict(id_key=str(i), email=f'{plan.lower()}@example.com', name=f'{plan.title()} account',
                 plan=plan, is_active=i == 0, sub_until='', file_path='/nonexistent/demo')
            for i, plan in enumerate(plans)]
limits = {str(i): dict(ok=True, plan_type=plan, rem_5h=[84,62,18][i], rem_weekly=[76,48,10][i],
                      allowed=True, limit_reached=False, reset_5h='2h 15m', reset_weekly='3d 4h')
          for i, plan in enumerate(plans)}

def forbidden(*args, **kwargs):
    raise RuntimeError('Real account actions are disabled in preview mode')

g.update(list_accounts=lambda: (accounts, accounts[0]),
         sync_current_auth=lambda: None, ensure_dirs=lambda: None,
         load_meta=lambda: {'web_emails': [a['email'] for a in accounts] + ['unknown@example.com']},
         get_auto_config=lambda: dict(mod['DEFAULT_AUTO_CONFIG']),
         get_auto_service_status=lambda: {'active': False, 'enabled': False},
         get_recent_auto_service_logs=lambda *a: 'Preview mode · No real accounts or service access',
         get_active_or_interrupted_codex_thread=lambda **kw: None,
         fetch_all_limits_parallel=lambda a: limits, is_chatgpt_app_running=lambda: False)
for name in ('switch_to_account', 'save_meta', 'save_auto_config', 'resume_codex_thread',
             'resume_codex_threads', 'set_auto_service_enabled', 'restart_auto_service_if_active',
             'open_url_in_browser', 'open_chatgpt_web_for_account', 'consume_codex_reset_credit'):
    g[name] = forbidden
if 'fetch_web_account_plans' in mod:
    g['fetch_web_account_plans'] = lambda emails, accs: {
        a['email']: dict(ok=True, plan=a['plan'], checked_at=time.time()) for a in accounts}
# Distinct application ID avoids activating the user's real application.
original_init = Adw.Application.__init__
def init(self, *a, **kw):
    kw['application_id'] = 'io.local.CodexAccountCenterPreview'
    original_init(self, *a, **kw)
Adw.Application.__init__ = init
original_run = Adw.Application.run
report = {}

def capture(app):
    try:
        report['pages'] = list(app.nav_buttons)
        report['account_cards'] = len(app.account_rows)
        texts = []
        def visit(widget):
            if isinstance(widget, Gtk.Label): texts.append(widget.get_label())
            child = widget.get_first_child()
            while child:
                visit(child)
                child = child.get_next_sibling()
        visit(app.win)
        report['plans_visible'] = all(p in texts for p in plans)
        assert report['plans_visible'], texts
        assert len(app.account_rows) == 3
        if 'web' in report['pages']:
            options = app.web_plan_filter.get_model()
            names = [options.get_string(i) for i in range(options.get_n_items())]
            report['plan_filters'] = names
            assert set(names) == {'All plans','PRO','PLUS','FREE','Unknown'}
            for name in ('PRO','FREE','Unknown'):
                app.web_plan_filter.set_selected(names.index(name))
                assert sum(row.get_visible() for row in app.web_rows) == 1
            app.web_plan_filter.set_selected(0)
        else:
            assert report['pages'] == ['codex','automation']
        GLib.timeout_add(300, save_image, app)
    except Exception:
        import traceback
        traceback.print_exc()
        report['failed'] = True
        app.quit()
    return False


def save_image(app):
    try:
        paintable = Gtk.WidgetPaintable.new(app.win)
        snapshot = Gtk.Snapshot.new()
        width, height = app.win.get_width(), app.win.get_height()
        paintable.snapshot(snapshot, width, height)
        texture = app.win.get_renderer().render_texture(snapshot.to_node(), Graphene.Rect().init(0,0,width,height))
        output = Path(os.environ.get('ACCOUNT_CENTER_PREVIEW_OUTPUT', ROOT / 'docs/account-center.png'))
        texture.save_to_png(str(output))
        report['screenshot'] = str(output)
        print(json.dumps(report), flush=True)
    except Exception:
        import traceback
        traceback.print_exc()
        report['failed'] = True
    finally:
        app.quit()
    return False

def run(app, *args):
    GLib.timeout_add(1600, capture, app)
    return original_run(app, *args)
Adw.Application.run = run
mod['run_gui']()
if report.get('failed'):
    sys.exit(1)
