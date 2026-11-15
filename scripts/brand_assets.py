"""Generate the Winq brand files: wordmark lockup, favicon, Apple touch icon and share image.

The mark is a rounded square on the brand gradient with two eyes: one open, one winking.
The wordmark is "winq" outlined from Unbounded Bold (SIL OFL), so it renders the same without the
font; its i-dot is a separate path (class "wm-spark") that pages colour pink.

    pip install fonttools brotli        # plus playwright, already in requirements.lock
    python scripts/brand_assets.py      # rewrites the files listed in OUTPUTS

Inline copies of the lockup in the HTML pages come from print_inline() (run with --inline).
"""
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / 'static/fonts/unbounded-latin-wght-normal.woff2'
INK, PINK, ORANGE = '#2a0f22', '#fd267a', '#ff6036'

# The mark, on a 64-unit square.
EYE = dict(cx=19.5, cy=31.5, rx=7.6, ry=9.4)
WINK = 'M32.5 34Q40.5 23 48.5 34'
WINK_WIDTH = 7.4


def squircle(size=64.0, n=5.0, steps=96):
    """A superellipse (continuous corners, like app icons) as an SVG path."""
    c = size / 2
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        x, y = math.cos(t), math.sin(t)
        pts.append((c + c * math.copysign(abs(x) ** (2 / n), x), c + c * math.copysign(abs(y) ** (2 / n), y)))
    return 'M' + 'L'.join(f'{x:.2f} {y:.2f}' for x, y in pts) + 'Z'


def gradient(gid):
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{PINK}"/>'
            f'<stop offset="1" stop-color="{ORANGE}"/></linearGradient>')


def eyes(colour='#fff'):
    e = EYE
    # Classes let a page recolour the mark (white tile, pink eyes) on a coloured background.
    return (f'<ellipse class="wm-eye" cx="{e["cx"]}" cy="{e["cy"]}" rx="{e["rx"]}" ry="{e["ry"]}" fill="{colour}"/>'
            f'<path class="wm-wink" d="{WINK}" fill="none" stroke="{colour}" stroke-width="{WINK_WIDTH}" stroke-linecap="round"/>')


def mark(gid, shape=None):
    return f'<path class="wm-tile" d="{shape or squircle()}" fill="url(#{gid})"/>{eyes()}'


def outline_word():
    """'winq' from Unbounded Bold, the i-dot split out. Returns (x0, y0, w, h, body_d, dot_d) in font units."""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    font = instantiateVariableFont(TTFont(FONT), {'wght': 700})
    glyphs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font['hmtx']
    x, body, dot = 0, [], ''
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for ch in 'winq':
        name = cmap[ord(ch)]
        rec = DecomposingRecordingPen(glyphs)
        glyphs[name].draw(rec)
        contours, cur = [], []
        for op, args in rec.value:
            cur.append((op, args))
            if op in ('closePath', 'endPath'):
                contours.append(cur)
                cur = []
        for contour in contours:
            sub = RecordingPen()
            sub.value = contour
            bounds = BoundsPen(glyphs)
            sub.replay(bounds)
            bx0, by0, bx1, by1 = bounds.bounds
            pen = SVGPathPen(glyphs)
            sub.replay(TransformPen(pen, (1, 0, 0, -1, x, 0)))
            d = pen.getCommands()
            if ch == 'i' and by0 > 550:
                dot = d
            else:
                body.append(d)
            x0, x1, y0, y1 = min(x0, bx0 + x), max(x1, bx1 + x), min(y0, -by1), max(y1, -by0)
        x += hmtx[name][0] - 30  # slightly tighter than the font's default spacing
    short = lambda d: re.sub(r'-?\d+\.\d+', lambda m: f'{float(m.group()):.1f}'.rstrip('0').rstrip('.'), d)
    return x0, y0, x1 - x0, y1 - y0, short(' '.join(body)), short(dot)


def lockup(gid, body_fill=INK, dot_attr=f'fill="{PINK}"'):
    """Mark + wordmark in one SVG viewBox. Returns (viewBox, inner markup)."""
    x0, y0, w, h, body, dot = outline_word()
    size, gap = h, 0.22 * h
    left = x0 - gap - size
    inner = (f'<defs>{gradient(gid)}</defs><g transform="translate({left:.0f} {y0:.0f}) scale({size / 64:.4f})">{mark(gid)}</g>'
             f'<path fill="{body_fill}" d="{body}"/><path {dot_attr} d="{dot}"/>')
    return f'{left:.0f} {y0:.0f} {x0 + w - left:.0f} {h:.0f}', inner


def print_inline():
    """The lockup for inline use in pages: letters follow currentColor, the i-dot takes class wm-spark."""
    vb, inner = lockup('wq-g', 'currentColor', 'class="wm-spark"')
    print(f'<svg class="wordmark" viewBox="{vb}" aria-hidden="true" focusable="false">{inner}</svg>')


def share_image_html():
    vb, inner = lockup('og-g')
    import base64
    embed = lambda f: base64.b64encode((ROOT / 'static/fonts' / f).read_bytes()).decode()  # set_content cannot read file://
    fonts = ''.join(
        f'@font-face{{font-family:"{fam}";font-weight:100 900;src:url(data:font/woff2;base64,{embed(f)}) format("woff2")}}'
        for fam, f in (('Onest', 'onest-latin-wght-normal.woff2'), ('Onest', 'onest-latin-ext-wght-normal.woff2'),
                       ('Unbounded', 'unbounded-latin-wght-normal.woff2'), ('Unbounded', 'unbounded-latin-ext-wght-normal.woff2')))
    card = 'background:#fff;border-radius:22px;box-shadow:0 18px 50px -24px rgba(42,15,34,.35);position:absolute'
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>{fonts}
*{{box-sizing:border-box}}body{{margin:0;width:1200px;height:630px;overflow:hidden;font-family:Onest,sans-serif;color:{INK};
background:radial-gradient(900px 600px at 95% 0%,#ffd6e3 0%,transparent 60%),radial-gradient(700px 500px at 0% 100%,#fff0e6 0%,transparent 60%),#fff6f8}}
.l{{position:absolute;left:72px;top:58px;width:600px}}h1{{font-family:Unbounded,sans-serif;font-weight:700;font-size:72px;line-height:1.02;
letter-spacing:-.045em;margin:46px 0 24px}}p{{font-size:25px;line-height:1.4;color:#57404f;margin:0;max-width:540px}}
.cta{{position:absolute;left:72px;bottom:48px;font-size:22px;font-weight:600;color:#6f5866}}.cta b{{color:{PINK}}}</style></head><body>
<div class="l"><svg viewBox="{vb}" height="58">{inner}</svg>
<h1>Zamień<br>dopasowania<br>w spotkania.</h1><p>Asystent randkowy AI, który pisze Twoim stylem i wie, kiedy zaprosić.</p></div>
<div class="cta"><b>Załóż konto</b> i zacznij dziś</div>
<div style="{card};left:700px;top:72px;width:288px;padding:18px 20px"><div style="display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px">
<span style="width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,{PINK},{ORANGE});color:#fff;display:grid;place-items:center;font-size:14px">O</span>Ola, 25</div>
<div style="margin-top:12px;background:#fff1f5;border-radius:14px;padding:12px 14px;font-size:19px">a ty co robisz w weekend?</div></div>
<div style="{card};left:880px;top:222px;width:270px;padding:18px 20px"><span style="display:inline-block;background:linear-gradient(120deg,{PINK},{ORANGE});
color:#fff;font-weight:700;font-size:15px;border-radius:999px;padding:6px 12px">Okno na zaproszenie</span>
<div style="height:8px;border-radius:9px;background:#f3e3ea;margin:14px 0 10px"><div style="width:82%;height:100%;border-radius:9px;background:linear-gradient(90deg,{PINK},{ORANGE})"></div></div>
<div style="font-size:15px;color:#6f5866">dopytuje · żartuje · szybko odpisuje</div></div>
<div style="position:absolute;left:696px;top:372px;width:320px;padding:20px 22px;border-radius:22px;color:#fff;
background:linear-gradient(120deg,{PINK},{ORANGE});box-shadow:0 18px 50px -20px rgba(253,38,122,.6)"><div style="font-size:19px;line-height:1.4">a może kawa w czwartek wieczorem?</div>
<div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;font-size:15px">Twoim stylem<span style="background:#fff;color:{PINK};font-weight:700;border-radius:999px;padding:6px 14px">Wyślij</span></div></div>
<div style="{card};left:872px;top:482px;width:278px;padding:16px 18px;display:flex;align-items:center;gap:14px">
<div style="background:#fff1f5;border-radius:12px;padding:8px 10px;text-align:center;font-family:Unbounded,sans-serif;font-weight:700;line-height:1.2">
<div style="font-size:12px;color:{PINK}">CZW</div><div style="font-size:16px">19:00</div></div><div><div style="font-weight:700;font-size:19px">Kawa na mieście</div>
<div style="font-size:15px;color:#6f5866">Ola: chętnie!</div></div></div>
</body></html>'''


def render_png(html, path, width, height):
    import os
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # BRAND_CHROMIUM: a Chromium binary, when the installed one does not match this Playwright version.
        browser = p.chromium.launch(executable_path=os.getenv('BRAND_CHROMIUM') or None, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.set_content(html)
        page.wait_for_timeout(300)
        page.screenshot(path=str(path))
        browser.close()


def main():
    if '--inline' in sys.argv:
        return print_inline()
    vb, inner = lockup('g')
    word = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{inner}</svg>\n'
    icon = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs>{gradient("g")}</defs>{mark("g")}</svg>\n'
    for target in ('control/static', 'static'):
        (ROOT / target / 'wordmark.svg').write_text(word, encoding='utf-8')
        (ROOT / target / 'icon.svg').write_text(icon, encoding='utf-8')
    # iOS rounds the corners itself, so the touch icon is a full square.
    touch = (f'<html><body style="margin:0"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="180" height="180">'
             f'<defs>{gradient("g")}</defs><rect width="64" height="64" fill="url(#g)"/>{eyes()}</svg></body></html>')
    render_png(touch, ROOT / 'control/static/apple-touch-icon.png', 180, 180)
    render_png(share_image_html(), ROOT / 'control/static/og.png', 1200, 630)


if __name__ == '__main__':
    main()
