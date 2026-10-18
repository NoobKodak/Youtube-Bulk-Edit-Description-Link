"""Allowlisted desktop build: never copies user data or credentials."""
import json, os, pathlib, shutil, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
stage=ROOT/'desktop-stage'; stage.mkdir(exist_ok=True)
tools=stage/'tools'; tools.mkdir(exist_ok=True)
ffmpeg=pathlib.Path(shutil.which('ffmpeg') or '')
node=pathlib.Path(shutil.which('node') or '')
if not ffmpeg.is_file() or not node.is_file(): raise SystemExit('FFmpeg and Node build tools are required.')
for src in [ROOT/'yt-dlp.exe',ffmpeg,ffmpeg.with_name('ffprobe.exe'),node]:
    if not src.is_file(): raise SystemExit(f'Missing runtime: {src.name}')
    shutil.copy2(src,tools/src.name)
licenses=stage/'licenses';licenses.mkdir(exist_ok=True)
shutil.copy2(ffmpeg.parent.parent/'LICENSE',licenses/'FFmpeg-GPLv3.txt')
shutil.copy2(node.parent/'LICENSE',licenses/'Node-LICENSE.txt')
version=subprocess.check_output([str(ROOT/'yt-dlp.exe'),'--version'],text=True).strip()
import urllib.request
for name,url in {'yt-dlp-LICENSE.txt':f'https://raw.githubusercontent.com/yt-dlp/yt-dlp/{version}/LICENSE','yt-dlp-THIRD_PARTY_LICENSES.txt':f'https://raw.githubusercontent.com/yt-dlp/yt-dlp/{version}/THIRD_PARTY_LICENSES.txt'}.items():
    urllib.request.urlretrieve(url,licenses/name)
(licenses/'NOTICE.txt').write_text('FFmpeg is a separate GPLv3 executable, not linked into the app. Build: Gyan 2026-07-02 git 95a888b9ca essentials. Corresponding source: https://github.com/FFmpeg/FFmpeg/tree/95a888b9ca and https://www.gyan.dev/ffmpeg/builds/ . This installer is for local personal use; prepare corresponding source for distribution. yt-dlp source: https://github.com/yt-dlp/yt-dlp/tree/'+version+' . Node source: https://nodejs.org/en/download . Electron includes LICENSE and LICENSES.chromium.html.',encoding='utf-8')
from playwright.sync_api import sync_playwright
from PIL import Image
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':256,'height':256},device_scale_factor=1)
    page.set_content('<style>body{margin:0;background:transparent}svg{width:256px;height:256px}</style>'+ (ROOT/'assets/channel-mark.svg').read_text())
    page.screenshot(path=str(ROOT/'desktop/icon.png'),omit_background=True)
    browser.close()
Image.open(ROOT/'desktop/icon.png').save(ROOT/'desktop/icon.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--name','toolkit-backend','--distpath',str(stage),'--workpath',str(ROOT/'.desktop-build'),'--specpath',str(ROOT/'.desktop-build'),'--icon',str(ROOT/'desktop/icon.ico'),'--collect-all','googleapiclient','--collect-all','tzdata']
for asset in ['ui.html','app.js','assets']:
    cmd+=['--add-data',f'{ROOT/asset}{os.pathsep}{"assets" if asset=="assets" else "."}']
cmd+=['web.py'];subprocess.run(cmd,check=True)
backend=stage/'toolkit-backend'
# electron-builder consumes the onedir tree under a stable backend folder.
(stage/'manifest.json').write_text(json.dumps({'yt_dlp':version,'included':['backend','tools','licenses'],'user_data_included':False}))
print('Backend packaged:',backend)

