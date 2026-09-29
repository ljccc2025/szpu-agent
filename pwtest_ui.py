# -*- coding: utf-8 -*-
"""M19 练习页 + 新 UI 的浏览器验收脚本（TDD 红绿载体）。

用法：python pwtest_ui.py [base_url]
退出码 0 表示全部断言通过，非 0 表示有失败项。
"""
import io
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.100.136:8000"
fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else "  << " + str(detail)))
    if not cond:
        fails.append(name)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 950})
    errs, pageerrs = [], []
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: pageerrs.append(str(e)))
    page.on("dialog", lambda d: d.dismiss())

    page.goto(BASE, timeout=30000)
    page.wait_for_selector("header", timeout=15000)

    print("== 1. 结构与导航 ==")
    tabs = page.locator("nav .tab")
    check("导航含 3 个页签", tabs.count() == 3, "实际 %d" % tabs.count())
    names = [tabs.nth(i).inner_text().strip() for i in range(tabs.count())]
    check("存在「练习与批改」页签", any("练习" in n for n in names), names)
    check("导航不使用 emoji 图标", page.locator("nav .tab svg").count() >= 3,
          "svg 数 %d" % page.locator("nav .tab svg").count())
    check("存在主题切换按钮", page.locator("#theme").count() == 1)

    print("== 2. 深色模式 ==")
    page.click("#theme")
    page.wait_for_timeout(400)
    check("切换后 data-theme=dark",
          page.evaluate("document.documentElement.dataset.theme") == "dark")
    page.click("#theme")
    page.wait_for_timeout(300)

    print("== 3. 知识库页（XSS 修复回归） ==")
    page.click('nav .tab[data-pane="kb"]')
    page.wait_for_selector("#src-list .src", timeout=20000)
    n_src = page.locator("#src-list .src").count()
    check("知识库列出来源", n_src > 0, n_src)
    btn = page.locator("#src-list .del").first
    check("删除按钮用 data-src", bool(btn.get_attribute("data-src")))
    check("删除按钮无内联 onclick", btn.get_attribute("onclick") is None)
    check("删除按钮有 aria-label", bool(btn.get_attribute("aria-label")))

    print("== 4. 练习页控件 ==")
    page.click('nav .tab[data-pane="practice"]')
    page.wait_for_timeout(500)
    for sel, label in [("#topic", "知识点输入框"), ("#diff", "难度下拉"),
                       ("#qtype", "题型下拉"), ("#gen", "出题按钮"),
                       ("#wb", "错题本容器")]:
        check("存在 " + label, page.locator(sel).count() == 1)

    print("== 5. 出题 -> 作答 -> 批改 闭环 ==")
    page.fill("#topic", "Nginx 反向代理")
    page.select_option("#qtype", "单选题")
    page.click("#gen")
    page.wait_for_selector("#quiz-card .opt", timeout=150000)
    qno = page.locator("#q-no").inner_text()
    check("出题成功并显示题号", "#" in qno, qno)
    opts = page.locator("#quiz-card .opt")
    check("单选题渲染 4 个选项", opts.count() == 4, opts.count())
    check("页面不泄露正确答案",
          "正确答案" not in page.locator("#quiz-card").inner_text())
    opts.first.click()
    check("选项被选中", opts.first.get_attribute("aria-pressed") == "true")
    page.click("#submit")
    page.wait_for_selector("#grade-card .ring", timeout=150000)
    score = page.locator("#grade-card .ring .n").inner_text().strip()
    check("批改返回分数", score.isdigit(), score)
    check("批改结果显示出处",
          "出处" in page.locator("#grade-card").inner_text())

    print("== 6. 错题本 ==")
    page.wait_for_timeout(1500)
    wb_text = page.locator("#wb").inner_text()
    check("错题本区域有内容", len(wb_text.strip()) > 0)
    page.click("#f-all")
    page.wait_for_timeout(1500)
    check("全部记录含表格或空态",
          page.locator("#wb table").count() > 0 or "还没有" in page.locator("#wb").inner_text())

    print("== 7. 响应式 375px ==")
    page.set_viewport_size({"width": 375, "height": 760})
    page.wait_for_timeout(400)
    sw = page.evaluate("document.documentElement.scrollWidth")
    check("375px 无横向滚动", sw <= 376, "scrollWidth=%d" % sw)
    page.set_viewport_size({"width": 1440, "height": 950})

    page.screenshot(path="pw_ui.png", full_page=True)
    print("== 8. F12 控制台 ==")
    check("无 console.error", not errs, errs)
    check("无 pageerror", not pageerrs, pageerrs)
    browser.close()

print()
if fails:
    print("RESULT: FAILED %d 项 -> %s" % (len(fails), fails))
    sys.exit(1)
print("RESULT: ALL PASSED")
