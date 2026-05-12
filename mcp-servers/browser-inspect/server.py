#!/usr/bin/env python3
"""MCP server: headless browser inspection (Playwright Chromium).

Lets the agent actually verify UIs — open a URL, take screenshots, read the DOM,
capture console logs, monitor network, run JS expressions. The thing CommandCode
can't do natively.
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright

mcp = FastMCP("browser-inspect")

DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
DEFAULT_TIMEOUT = 15000  # ms
SCREENSHOT_DIR = Path("/tmp/cc-browser-screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)


async def _browser_session():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    return p, browser


def _save_screenshot(png: bytes, prefix: str) -> str:
    import time
    fname = f"{prefix}-{int(time.time() * 1000)}.png"
    path = SCREENSHOT_DIR / fname
    path.write_bytes(png)
    return str(path)


@mcp.tool()
async def screenshot(url: str, full_page: bool = False, width: int = 1280, height: int = 800,
                     wait_for_selector: str | None = None) -> str:
    """Take a screenshot of a URL. Saves to /tmp/cc-browser-screenshots/.

    Args:
        url: Target URL (http/https/file://).
        full_page: Capture the whole scrolling page (not just viewport).
        width: Viewport width.
        height: Viewport height.
        wait_for_selector: Optional CSS selector to wait for before capture.

    Returns:
        JSON: {path, width, height, status, title}
    """
    p, browser = await _browser_session()
    try:
        ctx = await browser.new_context(viewport={"width": width, "height": height})
        page = await ctx.new_page()
        resp = await page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        if wait_for_selector:
            await page.wait_for_selector(wait_for_selector, timeout=DEFAULT_TIMEOUT)
        png = await page.screenshot(full_page=full_page)
        title = await page.title()
        path = _save_screenshot(png, "screenshot")
        return json.dumps({
            "path": path,
            "width": width,
            "height": height,
            "status": resp.status if resp else None,
            "title": title,
            "url": page.url,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    finally:
        await browser.close()
        await p.stop()


@mcp.tool()
async def dom(url: str, selector: str | None = None, max_chars: int = 8000) -> str:
    """Get the rendered HTML of a page or a specific element.

    Args:
        url: Target URL.
        selector: Optional CSS selector. Default: full <body>.
        max_chars: Truncate output. Default 8000.

    Returns:
        JSON: {selector, html, truncated}
    """
    p, browser = await _browser_session()
    try:
        ctx = await browser.new_context(viewport=DEFAULT_VIEWPORT)
        page = await ctx.new_page()
        await page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        if selector:
            el = await page.query_selector(selector)
            html = await el.inner_html() if el else ""
            if not el:
                return json.dumps({"error": f"selector not found: {selector}"})
        else:
            html = await page.inner_html("body")
        truncated = len(html) > max_chars
        return json.dumps({
            "selector": selector or "body",
            "html": html[:max_chars],
            "truncated": truncated,
            "full_length": len(html),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    finally:
        await browser.close()
        await p.stop()


@mcp.tool()
async def console(url: str, wait_seconds: int = 3) -> str:
    """Capture console messages emitted during page load.

    Args:
        url: Target URL.
        wait_seconds: How long to wait after load to collect lazy logs. Default 3.

    Returns:
        JSON: {messages: [{type, text}], errors: [...]}
    """
    p, browser = await _browser_session()
    try:
        ctx = await browser.new_context(viewport=DEFAULT_VIEWPORT)
        page = await ctx.new_page()
        messages = []
        errors = []
        page.on("console", lambda msg: messages.append({"type": msg.type, "text": msg.text}))
        page.on("pageerror", lambda err: errors.append(str(err)))
        await page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        await asyncio.sleep(wait_seconds)
        return json.dumps({
            "messages": messages[-200:],
            "errors": errors[-50:],
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    finally:
        await browser.close()
        await p.stop()


@mcp.tool()
async def network(url: str, filter_status: int | None = None) -> str:
    """Capture network requests made during page load.

    Args:
        url: Target URL.
        filter_status: Only return responses with this status (e.g. 404, 500).

    Returns:
        JSON: [{method, url, status, type, size}]
    """
    p, browser = await _browser_session()
    try:
        ctx = await browser.new_context(viewport=DEFAULT_VIEWPORT)
        page = await ctx.new_page()
        records: list[dict] = []

        async def on_response(resp):
            try:
                if filter_status is None or resp.status == filter_status:
                    records.append({
                        "method": resp.request.method,
                        "url": resp.url,
                        "status": resp.status,
                        "type": resp.request.resource_type,
                    })
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(on_response(r)))
        await page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        return json.dumps(records[-300:], ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    finally:
        await browser.close()
        await p.stop()


@mcp.tool()
async def eval_js(url: str, expression: str) -> str:
    """Evaluate a JS expression in the page context after load. Returns the JSON-serializable result.

    Args:
        url: Target URL.
        expression: JS expression (must return a JSON-serializable value).

    Returns:
        JSON: {result} or {error}.
    """
    p, browser = await _browser_session()
    try:
        ctx = await browser.new_context(viewport=DEFAULT_VIEWPORT)
        page = await ctx.new_page()
        await page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        result = await page.evaluate(expression)
        return json.dumps({"result": result}, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    finally:
        await browser.close()
        await p.stop()


@mcp.tool()
async def click_and_capture(url: str, selector: str, full_page: bool = False) -> str:
    """Open URL, click an element matching selector, take a screenshot of the result.

    Args:
        url: Target URL.
        selector: CSS selector to click.
        full_page: Whole page or viewport only.

    Returns:
        JSON: {path, before_path, after_url}
    """
    p, browser = await _browser_session()
    try:
        ctx = await browser.new_context(viewport=DEFAULT_VIEWPORT)
        page = await ctx.new_page()
        await page.goto(url, timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        before = await page.screenshot(full_page=full_page)
        before_path = _save_screenshot(before, "before-click")
        await page.click(selector, timeout=DEFAULT_TIMEOUT)
        await page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT)
        after = await page.screenshot(full_page=full_page)
        after_path = _save_screenshot(after, "after-click")
        return json.dumps({
            "before_path": before_path,
            "path": after_path,
            "after_url": page.url,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    finally:
        await browser.close()
        await p.stop()


if __name__ == "__main__":
    mcp.run()
