# -*- coding: utf-8 -*-
"""Playwright 端到端验证 (M07-M10 RAG 版):
1) 知识库 tab: 确认已入库的课件出现在列表
2) 对话 tab: 提 RAG 问题→等 AI 回复→验证出处卡并展开
3) 全页截图 + 控制台错误报告
"""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

URL = "http://192.168.100.136:8000"
Q = "nginx 反向代理怎么配置？"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL, timeout=20000)
    pg.wait_for_selector("#ipt", timeout=10000)

    # --- 1. 知识库 tab ---
    pg.click('.tab[data-p="kb"]')
    pg.wait_for_selector("#src-list .src-item", timeout=15000)
    kb_text = pg.locator("#src-list").inner_text().strip()
    print("KB_LIST:", kb_text.replace("\n", " | ")[:200])

    # --- 2. 对话 + 出处卡 ---
    pg.click('.tab[data-p="chat"]')
    n0 = pg.locator("#list > *").count()
    pg.fill("#ipt", Q)
    pg.click("#btn")
    pg.wait_for_function(
        "n => document.getElementById('list').children.length >= n + 2",
        arg=n0, timeout=120000)
    deadline = time.time() + 120
    last = ""
    while time.time() < deadline:
        t = pg.locator("#list > *").last.inner_text().strip()
        if len(t) > 10 and t == last:
            break
        last = t
        pg.wait_for_timeout(2500)

    cite = pg.locator(".cite-h").last
    has_cite = cite.count() > 0
    if has_cite:
        print("CITE_HEADER:", cite.inner_text().replace("\n", " "))
        cite.click()  # 展开出处折叠卡
        pg.wait_for_timeout(600)

    pg.screenshot(path="pw_result.png", full_page=True)
    print("QUESTION:", Q)
    print("REPLY:", last[:400])
    print("HAS_SOURCE_CARD:", has_cite)
    print("CONSOLE_ERRORS:", errs if errs else "NONE")
    b.close()
print("PW_TEST_DONE")
