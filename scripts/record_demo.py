#!/usr/bin/env python3
"""Record docs/demo/tour.mp4 and tour.poster.jpg from the landing page.

    pip install playwright   # and `ffmpeg` on PATH
    python3 scripts/record_demo.py

Opens docs/index.html in headless Chromium, takes screenshots as fast as it
can (each with its time, so playback is at real speed), and encodes them with
ffmpeg. The script lets the terminal replay, steps through the three circuits, and scrolls over the
gallery and the graphs. It records the page, not a live session. The video
is checked in; it is not part of `build_site.py --check` (an encoder's
output is not reproducible byte for byte).

Needs Playwright with Chromium (set CHROME to its executable if the
bundled one is not installed) and `ffmpeg`.
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
import time

from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEMO = os.path.join(ROOT, "docs", "demo")


async def script(pg):
    await pg.goto("file://" + os.path.join(ROOT, "docs", "index.html"))
    await pg.wait_for_timeout(9000)                      # the three refusals replay
    await pg.evaluate("document.getElementById('watch').scrollIntoView({behavior:'instant'})")
    await pg.evaluate("window.scrollBy(0, 150)")
    await pg.wait_for_timeout(7500)                      # Bell, autoplaying
    for name, wait in (("ghz4", 5500), ("teleport_unitary", 7000), ("qft4", 6500), ("grover3", 9500)):
        await pg.click(f'.tab[data-circuit="{name}"]')
        await pg.wait_for_timeout(wait)
    await pg.evaluate("document.getElementById('gallery').scrollIntoView({behavior:'smooth'})")
    await pg.wait_for_timeout(3500)
    await pg.evaluate("document.getElementById('measured').scrollIntoView({behavior:'smooth'})")
    await pg.wait_for_timeout(2500)
    await pg.evaluate("window.scrollBy({top: 520, behavior: 'smooth'})")
    await pg.wait_for_timeout(3500)


async def record(tmp):
    """Screenshots as fast as the browser gives them, each with its time, so the
    video plays at real speed whatever the screenshot rate was."""
    exe = os.environ.get("CHROME")
    frames = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1000, "height": 720})
        task = asyncio.create_task(script(pg))
        t0 = time.time()
        await asyncio.sleep(0.3)
        i = 0
        while not task.done():
            path = os.path.join(tmp, f"f{i:05d}.jpg")
            try:
                await pg.screenshot(path=path, type="jpeg", quality=80)
            except Exception:
                break
            frames.append((path, time.time() - t0))
            i += 1
        await task
        await b.close()
    return frames


def main():
    tmp = tempfile.mkdtemp(prefix="demo-")
    frames = asyncio.run(record(tmp))
    os.makedirs(DEMO, exist_ok=True)
    listing = os.path.join(tmp, "frames.txt")
    with open(listing, "w") as f:
        for k, (path, t) in enumerate(frames):
            dur = (frames[k + 1][1] - t) if k + 1 < len(frames) else 0.5
            f.write(f"file '{path}'\nduration {dur:.3f}\n")
        f.write(f"file '{frames[-1][0]}'\n")
    mp4 = os.path.join(DEMO, "tour.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing, "-vf", "fps=15,format=yuv420p",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-movflags", "+faststart", "-an", mp4], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "4", "-i", mp4, "-frames:v", "1", "-q:v", "4",
                    os.path.join(DEMO, "tour.poster.jpg")], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {mp4} ({os.path.getsize(mp4) / 1e6:.2f} MB, {len(frames)} screenshots)")


if __name__ == "__main__":
    main()
