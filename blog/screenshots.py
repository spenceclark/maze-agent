# ruff: noqa: E501  (long lines are embedded page JavaScript)
"""Element screenshots of the viewer for the blog draft, via headless Edge and the DevTools protocol.

Usage: start `uv run maze-lab --db pilot.db serve --port 8013`, then `uv run python blog/screenshots.py blog/images`.
The run ids below are games in the local pilot.db.
"""

import asyncio
import base64
import itertools
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
VIEWER = "http://127.0.0.1:8013/"
OUT = Path(sys.argv[1])

SEEK = """(t => {
  const el = document.querySelector('input[aria-label="Scrub to tick"]');
  const live = [...document.querySelectorAll('input[type=checkbox]')].find(c => c.parentElement.textContent.includes('Follow live'));
  if (live && live.checked) live.click();
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  set.call(el, String(t)); el.dispatchEvent(new Event('input', {bubbles: true}));
  return el.max;
})"""
UNCLIP = """(() => { const s = document.createElement('style');
  s.textContent = '.notebook-text, .radio, .panel table, .panel div { max-height: none !important; overflow: visible !important; }';
  document.head.appendChild(s); })()"""
PAD = 10


def rect_js(expr: str, pad: int = PAD) -> str:
    return f"""(() => {{ const r = ({expr}); return JSON.stringify({{x: r.left + scrollX - {pad}, y: r.top + scrollY - {pad},
      width: r.width + 2 * {pad}, height: r.height + 2 * {pad}}}); }})()"""


# Each shot: run, tick, optional preparation JS, and a JS expression giving a DOMRect to capture.
MAZE = "document.querySelector('.maze svg').getBoundingClientRect()"
GATEWAY = """(() => { const c = document.querySelector('rect[data-cell="10,14"]'); const svg = c.ownerSVGElement;
  const ns = 'http://www.w3.org/2000/svg'; const x = +c.getAttribute('x') + c.getAttribute('width') / 2,
  y = +c.getAttribute('y') + c.getAttribute('height') / 2;
  const ring = document.createElementNS(ns, 'circle'); ring.setAttribute('cx', x); ring.setAttribute('cy', y);
  ring.setAttribute('r', c.getAttribute('width') * 0.62); ring.setAttribute('fill', 'none');
  ring.setAttribute('stroke', '#d00'); ring.setAttribute('stroke-width', '3'); svg.appendChild(ring);
  const label = document.createElementNS(ns, 'text'); label.setAttribute('x', x); label.setAttribute('y', y - c.getAttribute('height'));
  label.setAttribute('text-anchor', 'middle'); label.setAttribute('fill', '#d00'); label.setAttribute('font-size', '13');
  label.setAttribute('font-weight', 'bold'); label.setAttribute('stroke', '#fff'); label.setAttribute('stroke-width', '4'); label.setAttribute('paint-order', 'stroke'); label.textContent = 'the way in, passed 6 times'; svg.appendChild(label); })()"""


def radio(lo: int, hi: int) -> tuple[str, str]:
    prep = (
        UNCLIP
        + f""";(() => {{ for (const tr of document.querySelectorAll('table.radio tbody tr')) {{
      const sent = +tr.children[2].textContent; tr.style.display = (sent >= {lo} && sent <= {hi}) ? '' : 'none'; }} }})()"""
    )
    return prep, "document.querySelector('table.radio').getBoundingClientRect()"


def notebook(agent: str, start: str, end: str) -> tuple[str, str]:
    prep = (
        UNCLIP
        + f""";(() => {{ const nb = [...document.querySelectorAll('.notebook')].find(n => n.querySelector('h4').textContent.includes('Notebook {agent}'));
      const sel = [...nb.querySelectorAll('select')][1]; const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
      set.call(sel, 'none'); sel.dispatchEvent(new Event('change', {{bubbles: true}})); }})()"""
    )
    expr = f"""(() => {{ const nb = [...document.querySelectorAll('.notebook')].find(n => n.querySelector('h4').textContent.includes('Notebook {agent}'));
      const pre = nb.querySelector('pre.notebook-text'); const node = pre.firstChild; const text = node.textContent;
      let i = text.indexOf({json.dumps(start)}); i = text.lastIndexOf('\\n', i) + 1;
      let j = text.indexOf({json.dumps(end)}, i); j = text.indexOf('\\n', j); if (j < 0) j = text.length;
      const range = document.createRange(); range.setStart(node, i); range.setEnd(node, j);
      const r = range.getBoundingClientRect(); const p = pre.getBoundingClientRect();
      return new DOMRect(p.left, r.top + 1, p.width, r.height + 5); }})()"""
    return prep, expr


SHOTS = [
    ("maze-sonnet-12x12-team-success-t110", "efb5bfcde844", 110, "", MAZE),
    ("maze-haiku-17x17-team-success-t236", "1c461f2ef226", 236, "", MAZE),
    ("maze-haiku-15x15-missed-gateway-t600", "ec6580b5c45c", 600, GATEWAY, MAZE),
    ("radio-sonnet-landmark-relay", "efb5bfcde844", 96, *radio(88, 96)),
    ("radio-haiku-10x10-waiting-for-coordinates", "ebe880ccf91e", 60, *radio(41, 60)),
    ("notebook-haiku-meeting-offset", "ed1ea6a5c483", 76, *notebook("C", "Tick 72:", "Tick75")),
    ("notebook-qwen-temperature-lock-in", "211579962f41", 16, *notebook("C", "Tick 9:", "Tick 16:")),
    ("notebook-haiku-frontier-list", "3e75a6a13206", 44, *notebook("B", "Tick41", "Tick44")),
]


async def shoot(ws_url: str, name: str, tick: int, prep: str, target: str) -> None:
    async with websockets.connect(ws_url, max_size=2**27) as ws:
        ids = itertools.count(1)

        async def call(method: str, **params: object) -> dict:
            i = next(ids)
            await ws.send(json.dumps({"id": i, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == i:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg["result"]

        async def js(expr: str) -> object:
            res = await call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
            if "exceptionDetails" in res:
                raise RuntimeError(res["exceptionDetails"])
            return res["result"].get("value")

        width = 720 if name.startswith("notebook") else 1100
        await call(
            "Emulation.setDeviceMetricsOverride", width=width, height=5000, deviceScaleFactor=2, mobile=False
        )
        for _ in range(150):
            await asyncio.sleep(0.2)
            if await js(
                "!!document.querySelector('.maze svg') && !!document.querySelector('input[aria-label=\"Scrub to tick\"]')"
            ):
                break
        await asyncio.sleep(1.5)
        await js(f"{SEEK}({tick})")
        await asyncio.sleep(2.5)  # notebooks and observations load for the new tick
        if prep:
            await js(prep)
            await asyncio.sleep(0.8)
        height = await js("document.documentElement.scrollHeight")
        await call(
            "Emulation.setDeviceMetricsOverride",
            width=width,
            height=int(height) + 200,
            deviceScaleFactor=2,
            mobile=False,
        )
        await asyncio.sleep(1.0)
        clip = json.loads(
            await js(rect_js(target, 2 if target == MAZE else 0 if name.startswith("notebook") else PAD))
        )
        clip["scale"] = 1
        shot = await call("Page.captureScreenshot", format="png", clip=clip)
        path = OUT / f"{name}.png"
        path.write_bytes(base64.b64decode(shot["data"]))
        print(f"{path.name}: {round(clip['width'])}x{round(clip['height'])} css px", flush=True)


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp()
    edge = subprocess.Popen(
        [
            EDGE,
            "--headless=new",
            "--remote-debugging-port=9333",
            f"--user-data-dir={profile}",
            "--window-size=1400,1000",
            "about:blank",
        ]
    )
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:9333/json/version")
                break
            except OSError:
                time.sleep(0.2)
        for name, run, tick, prep, target in SHOTS:
            req = urllib.request.Request(f"http://127.0.0.1:9333/json/new?{VIEWER}%23run={run}", method="PUT")
            tab = json.load(urllib.request.urlopen(req))
            try:
                await shoot(tab["webSocketDebuggerUrl"], name, tick, prep, target)
            finally:
                urllib.request.urlopen(f"http://127.0.0.1:9333/json/close/{tab['id']}")
    finally:
        edge.terminate()


asyncio.run(main())
