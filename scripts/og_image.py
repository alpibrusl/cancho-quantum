#!/usr/bin/env python3
"""Write docs/demo/og.png (1200x630): the page's hero, for link previews.

    CHROME=path/to/chromium python3 scripts/og_image.py
"""
import asyncio
import os

from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


async def main():
    exe = os.environ.get("CHROME")
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1200, "height": 630}, color_scheme="light")
        await pg.goto("file://" + os.path.join(ROOT, "docs", "index.html"))
        await pg.wait_for_timeout(8000)   # let the terminal replay finish
        await pg.screenshot(path=os.path.join(ROOT, "docs", "demo", "og.png"))
        await b.close()


asyncio.run(main())
