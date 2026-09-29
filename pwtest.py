# -*- coding: utf-8 -*-
"""Playwright 端到端验证:打开测试页→提问→等AI回复→截图+报告"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

URL = "http://192.168.100.136:8000"
Q = "现在几点了？"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL, timeout=20000)
    pg.wait_for_selector("#ipt", timeout=10000)
    n0 = pg.locator("#list > *").count()
    pg.fill("#ipt", Q)
    pg.click("#btn")
    pg.wait_for_function(
        "n => document.getElementById('list').children.length >= n + 2",
        arg=n0, timeout=90000)
    deadline = time.time() + 90
    last = ""
    while time.time() < deadline:
        t = pg.locator("#list > *").last.inner_text().strip()
        if len(t) > 10 and t == last:
            break
        last = t
        pg.wait_for_timeout(2500)
    pg.screenshot(path="pw_result.png", full_page=True)
    print("QUESTION:", Q)
    print("REPLY:", last[:500])
    print("CONSOLE_ERRORS:", errs if errs else "NONE")
    b.close()
print("PW_TEST_DONE")
