"""Offline browser checks. All requests are mocked; no live account is used.

Run: python -B test_ui_redesign.py
Requires Playwright and an installed Chrome browser. Screenshots go to .ui-preview.
"""
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
import bulkedit
import web

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / '.ui-preview'


def run():
    OUTPUT.mkdir(exist_ok=True)
    rules = [{'name': 'Instagram username', 'enabled': True, 'type': 'text',
              'find': 'prod.crmdrm', 'replace': 'prod_crmdrm', 'protect': ['business@example.com']}]
    base = 'An original beat.\nInstagram: @prod.crmdrm\nhttps://www.instagram.com/prod.crmdrm/\nEmail: business@example.com\n'
    videos = [{'id': str(i), 'snippet': {'title': title, 'description': desc},
               'status': {'privacyStatus': 'public'}}
              for i, (title, desc) in enumerate([
                  ('Golden hour — indie guitar beat', base),
                  ('Somewhere new — alternative beat', base.replace('prod.crmdrm/', 'prod.crmdrm')),
                  ('A quiet morning — piano beat', 'Original music. Contact business@example.com.'),
              ])]
    progress = {'completed': {}, 'failed': {}, 'quota_by_pt_date': {}}
    status = {'phase': 'ready', 'message': 'Your channel is ready. Choose what to update.',
              'channel': {'title': 'Studio channel', 'id': 'demo'}, 'error': None, 'job': None,
              'counts': {'videos': 3, 'api_videos': 3, 'pending_edits': 2, 'links': 1},
              'quota': {'spent': 0, 'limit': 10000, 'affordable_updates': 197, 'update_cost': 50},
              'reset': {'reset_local': 'tomorrow'},
              'ytdlp': {'available': True, 'version': 'demo', 'cached': 3, 'updated_at': None}}
    captured = []
    actions = []
    allow_mock_actions = False
    fail_exports = False
    with patch.object(web, 'API_VIDEOS', videos), \
         patch.object(web.ytdlp, 'load_cache', return_value={'videos': {}}), \
         patch.object(web.main, 'load_progress', return_value=progress), \
         patch.object(web.bulkedit, 'load_rules', side_effect=lambda: rules), \
         sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1050}, color_scheme='light')
        errors = []
        page.on('pageerror', lambda error: errors.append(error.stack or str(error)))

        def route(request):
            nonlocal rules
            parsed = urlparse(request.request.url)
            if parsed.hostname != 'toolkit.test':
                return request.abort()
            path = parsed.path
            if path == '/':
                return request.fulfill(body=(ROOT/'ui.html').read_text(encoding='utf-8'), content_type='text/html')
            if path == '/app.js':
                return request.fulfill(body=(ROOT/'app.js').read_text(encoding='utf-8'), content_type='text/javascript')
            brand_assets = {'/assets/brand.css':'text/css', '/assets/channel-mark.svg':'image/svg+xml',
                            '/assets/ui/ui.css':'text/css', '/assets/ui/ui.js':'text/javascript',
                            '/assets/fonts/LinkSans-LinkSansVF.woff2':'font/woff2',
                            '/assets/fonts/link-sans.css':'text/css'}
            if path in brand_assets:
                return request.fulfill(body=(ROOT/path.lstrip('/')).read_bytes(), content_type=brand_assets[path])
            data = {}
            if path == '/api/status': data = status
            elif path == '/api/videos': data = {'videos': web.merged_videos()}
            elif path == '/api/rules':
                if request.request.method == 'POST':
                    rules = request.request.post_data_json['rules']
                    compiled, problems = bulkedit.validate_rules(rules)
                    data = {'errors': problems, 'enabled': len(compiled)}
                else: data = {'rules': rules}
            elif path == '/api/bulk/preview':
                ids = request.request.post_data_json.get('video_ids')
                data = web.compute_preview(ids)
                captured.append(data)
            elif path == '/api/log': data = {'lines': [], 'total': 0}
            elif path == '/api/links': data = {'links': []}
            elif path == '/api/download/env':
                data = {'presets': [{'key': key, **value} for key,value in web.download.PRESETS.items()],
                        'ytdlp_version': 'demo', 'ffmpeg': True, 'js_runtime': 'Node', 'default_outdir': 'downloads'}
            elif path == '/api/stats': data = {}
            elif allow_mock_actions and path in ['/api/scan','/api/stop','/api/ytdlp/sync',
                    '/api/export','/api/ytdlp/thumbnails','/api/download/preview',
                    '/api/download/formats','/api/download/start','/api/bulk/apply']:
                actions.append((path, request.request.post_data_json))
                if path == '/api/export' and fail_exports:
                    return request.fulfill(status=500, json={'error':'Export could not be saved. Check the project folder permissions and try again.'})
                data = {'message':'Mock operation complete.', 'text':'Mock format list',
                        'command':'yt-dlp --mock-only', 'args':['yt-dlp','--mock-only']}
            else:
                raise AssertionError('Unexpected request (live operations forbidden): ' + path)
            request.fulfill(json=data)

        page.route('**/*', route)
        page.goto('http://toolkit.test/#edit')
        assert not errors, errors
        page.locator('#find-0').wait_for()
        assert page.locator('html').get_attribute('data-theme') == 'dark'
        assert page.evaluate("localStorage.getItem('theme')") == 'dark'
        page.evaluate('document.fonts.ready')
        page.locator('.workspace-nav').first.wait_for()
        assert page.locator('.header-brand img').evaluate('(el)=>el.complete && el.naturalWidth>0')
        assert page.evaluate("document.fonts.check('14px \"Link Sans\"')")
        assert page.evaluate("getComputedStyle(document.body).fontFamily.includes('Link Sans')")
        assert not errors, errors
        page.screenshot(path=str(OUTPUT/'desktop-text.png'), full_page=True, animations='disabled')
        page.locator('#rInstagram').click()
        page.screenshot(path=str(OUTPUT/'desktop-instagram.png'), full_page=True, animations='disabled')
        page.locator('#rPreview').click()
        page.wait_for_function('PREVIEW !== null && !PREVIEW_BUSY')
        assert len(captured[-1]['changes']) == 2
        assert not captured[-1]['rejected'], captured[-1]['rejected']
        assert len(captured[-1]['unchanged']) == 1
        assert page.locator('#rApply').is_enabled()
        assert page.locator('#editResult mark').count() > 0
        assert 'prod.crmdrm' not in captured[-1]['pending'][0]['new_description']
        assert 'prod.crmdrm' not in page.locator('#editResult .diff.after').all_text_contents()[0]
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(OUTPUT/'desktop-review.png'), full_page=True, animations='disabled')
        page.locator('#rApply').click()
        assert page.locator('#dlgGo').is_disabled()
        assert page.locator('#dlgWord').evaluate('(el)=>el===document.activeElement')
        page.locator('#dlgWord').fill('update')
        assert page.locator('#dlgGo').is_disabled()
        page.locator('#dlgWord').fill('UPDATE')
        assert page.locator('#dlgGo').is_enabled()
        page.screenshot(path=str(OUTPUT/'confirmation.png'), animations='disabled')
        page.locator('#dlgCancel').click()
        page.locator('#igNewName').fill('another_name')
        assert page.locator('#rApply').is_disabled()
        page.locator('#igNewName').fill('prod_crmdrm')

        # Validate the actual generated rules against boundary cases.
        compiled, problems = bulkedit.validate_rules(page.evaluate('currentRules()'))
        assert not problems
        for old, new in [('@prod.crmdrm', '@prod_crmdrm'), ('prod.crmdrm', 'prod_crmdrm'),
                         ('https://www.instagram.com/prod.crmdrm', 'https://www.instagram.com/prod_crmdrm/'),
                         ('https://www.instagram.com/prod.crmdrm/', 'https://www.instagram.com/prod_crmdrm/')]:
            actual, _, rejected = bulkedit.apply_rules('Follow me: '+old, compiled)
            assert actual == 'Follow me: '+new, (old, actual, rejected)
        for unchanged in ['name@prod.crmdrm', 'prod.crmdrm@example.com', 'https://example.com/prod.crmdrm',
                          '@prod.crmdrm_extra', 'https://www.instagram.com/prod.crmdrm_extra/',
                          'https://www.instagram.com/prod.crmdrm/posts', 'https://example.com/@prod.crmdrm']:
            actual, _, _ = bulkedit.apply_rules(unchanged, compiled)
            assert actual == unchanged, (unchanged, actual)

        assert page.locator('.desktop-sidebar [data-page=videos]').count() == 0
        page.locator('#rPreview').click()
        page.wait_for_function('PREVIEW !== null && !PREVIEW_BUSY')
        assert [v['video_id'] for v in captured[-1]['pending']] == ['0', '1']

        # Exercise new shadcn interactions against strictly mocked write endpoints.
        allow_mock_actions = True
        page.locator('#edit-help-trigger button').click()
        assert page.get_by_role('dialog').is_visible()
        assert page.locator('#edit-help-fields').is_visible()
        page.keyboard.press('Escape')
        page.get_by_role('dialog').wait_for(state='hidden')
        assert page.locator('#edit-help-trigger button').evaluate('(e)=>e===document.activeElement')

        page.locator('#activity-toggle').click()
        assert page.locator('#activity-panel').get_attribute('data-open') == ''
        page.locator('#activityClose').click()
        assert page.locator('#activity-panel').get_attribute('data-open') is None

        page.evaluate("show('tools')")
        page.locator('#cookie-trigger button').click()
        page.locator('#tCookies').select_option('edge')
        page.get_by_role('button', name='Done', exact=True).click()
        page.evaluate("show('edit')")
        page.locator('#btnSyncFree').click()
        page.wait_for_function("!document.querySelector('#btnSyncFree').hasAttribute('aria-busy')")
        assert ('/api/ytdlp/sync', {'cookies_browser':'edge'}) in actions
        page.evaluate("show('tools')")
        page.locator('#export-trigger button').click()
        page.locator('#tCsv').click()
        page.wait_for_function("!document.querySelector('#tCsv').hasAttribute('aria-busy')")
        assert ('/api/export', {'format':'csv'}) in actions
        fail_exports = True
        page.locator('#tJson').click()
        page.get_by_text('Export could not be saved.', exact=False).wait_for()
        fail_exports = False
        page.locator('#tJson').click()
        page.wait_for_function("!document.querySelector('#tJson').hasAttribute('aria-busy')")
        assert ('/api/export', {'format':'json'}) in actions
        page.get_by_role('button', name='Done', exact=True).click()
        page.locator('#tThumbs').click()
        page.wait_for_function("!document.querySelector('#tThumbs').hasAttribute('aria-busy')")
        assert ('/api/ytdlp/thumbnails', {'cookies_browser':'edge'}) in actions

        page.evaluate("show('download')")
        page.locator('#dlPresets button').first.wait_for()
        for preset in page.locator('#dlPresets button').all():
            preset.click()
        page.locator('#dlPresets button').first.click()
        page.locator('#dlOutDir').fill('test-output')
        page.locator('#download-settings-trigger button').click()
        page.locator('#dlMode').select_option('audio')
        page.locator('#dlAudioFmt').select_option('flac')
        page.get_by_role('tab', name='Extras', exact=True).click()
        page.locator('#dlSubs').check()
        page.locator('#dlCookies').select_option('chrome')
        page.get_by_role('tab', name='Filters', exact=True).click()
        page.locator('#dlFilter').fill('duration < 600')
        page.get_by_role('tab', name='System', exact=True).click()
        assert page.locator('#dlEnv').is_visible()
        page.get_by_role('tab', name='Output', exact=True).click()
        assert page.locator('#dlOutDir').input_value() == 'test-output'
        assert page.locator('#dlMode').input_value() == 'audio'
        page.screenshot(path=str(OUTPUT/'download-settings.png'), animations='disabled')
        page.get_by_role('button', name='Done', exact=True).click()
        assert page.locator('#dlFilter').input_value() == 'duration < 600'
        page.locator('#dlUrls').fill('https://www.youtube.com/watch?v=mock-video')
        expected_options = page.evaluate('downloadOpts()')
        page.locator('#dlPreviewBtn').click()
        page.wait_for_function("!document.querySelector('#dlPreviewBtn').hasAttribute('aria-busy')")
        page.locator('#dlFormats').click()
        page.wait_for_function("!document.querySelector('#dlFormats').hasAttribute('aria-busy')")
        assert ('/api/download/formats', {'url':'https://www.youtube.com/watch?v=mock-video','cookies_browser':'chrome'}) in actions
        page.locator('#dlStart').click()
        page.wait_for_function("!document.querySelector('#dlStart').hasAttribute('aria-busy')")
        assert ('/api/download/start', expected_options) in actions
        page.evaluate('DLENV.stale=true')
        page.locator('#dlStart').click()
        page.get_by_role('alertdialog').wait_for()
        page.get_by_role('button', name='Cancel', exact=True).click()
        page.get_by_role('alertdialog').wait_for(state='hidden')
        assert len([a for a in actions if a[0]=='/api/download/start']) == 1
        page.locator('#dlMyChannel').click()
        assert 'demo' in page.locator('#dlUrls').input_value()
        page.evaluate("show('edit'); setEditMode('text')")
        initial_rules = page.locator('#rList .rule-card').count()
        page.locator('#rAdd').click()
        page.locator('#rList [data-act=del]').last.click()
        page.get_by_role('alertdialog').wait_for()
        page.get_by_role('button', name='Cancel', exact=True).click()
        page.get_by_role('alertdialog').wait_for(state='hidden')
        assert page.locator('#rList .rule-card').count() == initial_rules + 1
        page.locator('#rList [data-act=del]').last.click()
        page.get_by_role('button', name='Continue', exact=True).click()
        page.get_by_role('alertdialog').wait_for(state='hidden')
        assert page.locator('#rList .rule-card').count() == initial_rules
        page.locator('#rList .advanced summary').first.click()
        page.locator('#type-0').select_option('text')
        page.locator('#find-0').fill('prod.crmdrm')
        page.locator('#replace-0').fill('prod_crmdrm')
        page.locator('#protect-0').fill('business@example.com')
        page.locator('#rList [data-f=case_sensitive]').first.check()
        page.locator('#rList [data-f=word_boundary]').first.check()
        page.locator('#rSave').click()
        page.wait_for_function("!document.querySelector('#rSave').hasAttribute('aria-busy')")
        assert 'Saved' in page.locator('#rErrors').inner_text()
        page.locator('#rInstagram').click()
        assert page.evaluate('selectedScope()') is False
        page.locator('#rPreview').click()
        page.wait_for_function('PREVIEW !== null && !PREVIEW_BUSY')
        expected_token = captured[-1]['preview_id']
        page.locator('#rApply').click()
        page.locator('#dlgWord').fill('UPDATE')
        page.locator('#dlgGo').click()
        page.get_by_role('dialog').wait_for(state='hidden')
        assert ('/api/bulk/apply', {'confirm':'UPDATE','preview_id':expected_token}) in actions
        assert [v['video_id'] for v in captured[-1]['pending']] == ['0', '1']
        page.locator('#btnScanApi').click()
        page.wait_for_function("!document.querySelector('#btnScanApi').hasAttribute('aria-busy')")
        assert ('/api/scan', {}) in actions

        # Command navigation, appearance menu, keyboard focus, and mobile sheet.
        page.keyboard.press('Control+k')
        page.get_by_placeholder('Where would you like to go?').fill('Bulk Edit')
        page.get_by_role('option').click()
        assert page.locator('#view-edit').is_visible()
        page.locator('.bulk-submodules a[href="#links"]').click()
        assert page.locator('#view-links').is_visible()
        assert page.get_by_role('button', name='Choose appearance').count() == 0
        page.set_viewport_size({'width':375,'height':812})
        page.get_by_role('button', name='Open navigation').click()
        page.locator('.navigation-sheet').wait_for()
        page.screenshot(path=str(OUTPUT/'mobile-navigation.png'), animations='disabled')
        page.locator('.navigation-sheet [data-page=download]').click()
        assert page.locator('#view-download').is_visible()
        assert page.locator('.mobile-bottom-tabs [data-tab=download]').get_attribute('aria-current') == 'page'
        page.locator('#download-settings-trigger button').click()
        page.get_by_role('tab', name='Extras', exact=True).click()
        assert page.locator('#dlCookies').input_value() == 'chrome'
        assert page.locator('#dlSubs').is_checked()
        page.screenshot(path=str(OUTPUT/'mobile-settings.png'), animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.keyboard.press('Escape')
        page.get_by_role('dialog').wait_for(state='hidden')

        for width, height in [(1920,1080),(1440,1050),(1280,720),(1024,768),(768,1024),(375,812),(320,568),(812,375)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.wait_for_function("Math.abs(parseFloat(getComputedStyle(document.querySelector('#activity-panel')).top)-document.querySelector('.shell-header').getBoundingClientRect().height)<1")
            for view in ['edit','overview','links','help','tools','download']:
                page.evaluate('(view)=>show(view)', view)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width,view)
                if width == 1440:
                    page.screenshot(path=str(OUTPUT/f'page-{view}.png'), full_page=True, animations='disabled')
            page.evaluate("show('edit')")
            page.screenshot(path=str(OUTPUT/f'layout-{width}.png'),full_page=True, animations='disabled')
        page.set_viewport_size({'width':1440,'height':1050})
        page.evaluate("show('edit'); document.querySelector('#activity-toggle').click()")
        page.wait_for_function("getComputedStyle(document.querySelector('#view-edit .edit-main')).gridTemplateColumns.split(' ').length === 1")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#activityClose').click()
        page.evaluate("applyTheme('dark')")
        page.screenshot(path=str(OUTPUT/'desktop-dark.png'),full_page=True, animations='disabled')
        page.wait_for_function("getComputedStyle(document.querySelector('#chooseVideos')).color === 'rgb(242, 242, 243)'")
        status['counts']['api_videos'] = 0
        page.evaluate('poll()')
        assert page.locator('#rApply').is_disabled()
        assert 'Scan for editing first' in page.locator('#applyHelp').inner_text()
        status['phase'] = 'scanning'
        status['message'] = 'Signing in and reading your channel through the API...'
        page.evaluate('poll()')
        assert 'Google sign-in' in page.locator('#phaseMsg').inner_text()
        assert 'elapsed' in page.locator('#phaseMsg').inner_text()
        assert page.locator('#rPreview').is_disabled()
        page.locator('#btnStop').click()
        page.wait_for_function("!document.querySelector('#btnStop').hasAttribute('aria-busy')")
        assert ('/api/stop', {}) in actions
        status['phase'] = 'ready'
        status['counts']['api_videos'] = 3
        page.evaluate('poll()')
        page.emulate_media(reduced_motion='reduce')
        page.add_script_tag(path=str(ROOT/'node_modules/axe-core/axe.min.js'))
        for theme in ['light','dark']:
            page.evaluate('(theme)=>applyTheme(theme)', theme)
            for view in ['overview','edit','links','download','tools','help']:
                page.evaluate('(view)=>show(view)', view)
                page.evaluate('''async () => { await Promise.all(document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))) }''')
                violations = page.evaluate('''async () => (await axe.run(document, {
                  runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}
                })).violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,reason:n.failureSummary}))}))''')
                assert not violations, (theme,view,violations)
        page.evaluate("show('download')")
        page.locator('#download-settings-trigger button').click()
        for tab in ['Output','Extras','Filters','System']:
            page.get_by_role('tab', name=tab, exact=True).click()
            assert not page.evaluate('''async () => (await axe.run(document, {
                runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}
            })).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))''')
        for _ in range(12):
            page.keyboard.press('Tab')
            assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
        page.keyboard.press('Escape')
        page.get_by_role('dialog').wait_for(state='hidden')
        page.emulate_media(reduced_motion='reduce')
        assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
        assert not errors, errors
        status['download'] = {'id':'mock','status':'running','percent':'42.5%','title':'Mock video','folder':'downloads'}
        page.evaluate("show('download'); poll()")
        page.wait_for_function("document.querySelector('#downloadProgress progress')?.value === 42.5")
        assert page.locator('#downloadProgress progress').get_attribute('value') == '42.5'
        status['download'] = {'id':'mock','status':'complete','folder':'downloads'}
        page.evaluate('poll()')
        page.locator('#downloadComplete').wait_for(state='visible')
        assert page.locator('#downloadComplete').is_visible()
        assert page.locator('#downloadOpenFolder').inner_text() == 'Open folder'
        page.locator('#downloadDismiss').click()
        assert page.locator('#downloadComplete').is_hidden()
        status['download'] = None
        status['phase'] = 'downloading'
        status['job'] = {'done':9,'total':300,'current':'61.2% 2MiB/s - Mock video'}
        page.evaluate('poll()')
        page.wait_for_function("document.querySelector('#downloadProgress progress')?.value === 61.2")
        status['phase'] = 'ready'
        status['message'] = 'Download finished. Files are in downloads'
        page.evaluate('poll()')
        page.locator('#downloadComplete').wait_for(state='visible')
        page.locator('#downloadOpenFolder').click()
        assert 'Restart' in page.locator('#folderError').inner_text()
        browser.close()
    print('PASS: preview safety; mocked scan/apply/export/downloads; settings and dialogs; eight responsive viewport sizes, expanded Activity layout, dark default, accessibility and reduced motion. No live requests.')


if __name__ == '__main__':
    run()
