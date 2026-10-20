"""Build website/offline help from the same small Markdown document (stdlib only)."""
import argparse
import html
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def inline(text):
    text=html.escape(text)
    text=re.sub(r'\[([^\]]+)\]\((https://[^\s)]+)\)',r'<a href="\2">\1</a>',text)
    text=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',text)
    return re.sub(r'`([^`]+)`',r'<code>\1</code>',text)


def render_help(markdown):
    title='Help'; sections=[]; paragraph=[]; heading=None; body=[]
    def flush():
        if paragraph:body.append('<p>'+inline(' '.join(paragraph))+'</p>');paragraph.clear()
    for line in markdown.splitlines():
        if line.startswith('# '):title=line[2:].strip()
        elif line.startswith('## '):
            flush()
            if heading is not None:sections.append((heading,body));body=[]
            heading=line[3:].strip()
        elif not line.strip():flush()
        else:paragraph.append(line.strip())
    flush()
    if heading is not None:sections.append((heading,body))
    content='\n'.join('<details'+(' open' if i==0 else '')+'><summary>'+inline(q)+'</summary><div class="answer">'+''.join(p)+'</div></details>'
                      for i,(q,p) in enumerate(sections))
    return '''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#18211e"><title>'''+html.escape(title)+'''</title>
<link rel="stylesheet" href="styles.css?v=20261020-3"><link rel="stylesheet" href="help.css?v=1">
<link rel="icon" href="assets/brand.svg?v=2" type="image/svg+xml"></head>
<body class="help-page"><a class="skip" href="#main">К содержимому</a>
<div class="backdrop" aria-hidden="true"></div><div class="shade" aria-hidden="true"></div>
<header class="header"><a class="brand" href="./" aria-label="BC2.uplay2.ru — главная"><img class="brand-mark" src="assets/brand.svg?v=2" alt="" width="43" height="48"><span>BC2<span>.uplay2.ru</span></span></a><a class="header-link" href="./">На главную</a></header>
<main id="main" class="help-main"><h1>'''+html.escape(title)+'''</h1><div class="questions">'''+content+'''</div></main>
<footer class="footer"><span>BC2.uplay2.ru</span></footer></body></html>
'''


def build_help(source,website,asset,*,check=False):
    source=Path(source);website=Path(website);asset=Path(asset)
    raw=source.read_bytes();web=render_help(raw.decode('utf-8')).encode('utf-8')
    if check:
        # Git may normalize text-file line endings on Windows.
        norm=lambda data:data.replace(b'\r\n',b'\n')
        if not website.is_file() or not asset.is_file() or norm(website.read_bytes())!=norm(web) or norm(asset.read_bytes())!=norm(raw):
            raise SystemExit('Help outputs are stale; run tools/build_help.py.')
    else:
        website.parent.mkdir(parents=True,exist_ok=True);asset.parent.mkdir(parents=True,exist_ok=True)
        website.write_bytes(web);asset.write_bytes(raw)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');a=parser.parse_args()
    build_help(ROOT/'docs'/'FAQ_RU.md',ROOT/'website'/'help.html',ROOT/'launcher'/'assets'/'FAQ_RU.md',check=a.check)
    print('Shared help: OK')
