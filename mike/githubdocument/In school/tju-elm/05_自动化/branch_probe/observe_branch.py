# -*- coding: utf-8 -*-
"""
Login.vue 第 83 行 `if (!user)` 单判定双分支运行观察脚本（证据工具，不计入主用例）。

做法：
  - 通过 CDP Page.addScriptToEvaluateOnNewDocument 在页面 JS 执行前注入轻量探针，
    仅记录 /UserController/getUserByIdByPass 的 XHR 响应（status、原始响应体），
    并把 window.alert 改为记录参数（原生 alert 会阻塞，无法自动继续），
    不修改业务源码、不注入 sessionStorage，登录均通过真实页面操作完成。
  - 在页面 JS 上下文中用与 axios 相同的规则还原 response.data，
    并求值 Login.vue 第 83 行的判定表达式 `!user`，记录条件值与实际命中分支效果。

两种输入：
  R-true  19112121212 / 123456Qaq  -> HTTP200 用户对象 -> !user=false -> 存 user、跳 /index
  R-false 19112121212 / Wrong123   -> HTTP200 空响应体 -> !user=true  -> alert 用户名或密码不正确
"""
import json
import os
import sys
import tempfile
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "http://localhost:8084"
USER_ID = "19112121212"
OUT_DIR = Path(__file__).resolve().parent.parent / "evidence" / "branch"

INIT_JS = r"""
window.__captured = [];
window.__alerts = [];
(function () {
  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__u = u; return origOpen.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (b) {
    this.addEventListener('load', function () {
      if (String(this.__u).indexOf('getUserByIdByPass') >= 0) {
        window.__captured.push({ url: String(this.__u), status: this.status, body: this.responseText });
      }
    });
    return origSend.apply(this, arguments);
  };
  window.alert = function (msg) { window.__alerts.push(String(msg)); };
})();
"""


def new_driver():
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--window-size=430,900")
    o.add_argument("--user-data-dir=" + tempfile.mkdtemp(prefix="elm-branch-"))
    drv = webdriver.Chrome(
        service=Service(os.environ.get(
            "CHROMEDRIVER_PATH",
            r"C:\Users\admin\.local\drivers\chromedriver-win64\chromedriver.exe")),
        options=o)
    drv.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": INIT_JS})
    return drv


def do_login(drv, password):
    drv.get(f"{BASE_URL}/login")
    w = WebDriverWait(drv, 15)
    w.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[placeholder='手机号码']"))).send_keys(USER_ID)
    drv.find_element(By.CSS_SELECTOR, "input[type='password']").send_keys(password)
    drv.find_element(By.XPATH, "//button[contains(., '登陆')]").click()


def observe(password, label, expect_branch):
    drv = new_driver()
    result = {"label": label, "password": password, "expect": expect_branch}
    try:
        do_login(drv, password)
        w = WebDriverWait(drv, 15)
        if expect_branch == "false(!user为假->保存并跳转)":
            w.until(EC.url_contains("/index"))
        else:
            w.until(lambda d: len(d.execute_script("return window.__alerts;")) > 0)

        # 在页面 JS 上下文还原 axios 的 response.data 并对第83行判定求值
        cond = drv.execute_script(
            "var c = window.__captured[window.__captured.length-1];"
            "var data = (c.body === '') ? '' : JSON.parse(c.body);"
            "return {"
            "status: c.status, rawBodyHead: c.body.substring(0, 60), rawBodyLen: c.body.length,"
            "dataType: typeof data, truthy: !!data, notUser: !data"
            "};"
        )
        result["http_status"] = cond["status"]
        result["raw_body_len"] = cond["rawBodyLen"]
        result["raw_body_head"] = cond["rawBodyHead"]
        result["data_type"] = cond["dataType"]
        result["user_truthy"] = cond["truthy"]
        result["not_user_condition"] = cond["notUser"]
        result["final_url"] = drv.current_url
        result["sessionStorage_user"] = drv.execute_script("return sessionStorage.getItem('user');")
        result["alerts"] = drv.execute_script("return window.__alerts;")

        # 分支命中核对
        if expect_branch == "false(!user为假->保存并跳转)":
            result["hit"] = (cond["notUser"] is False and result["sessionStorage_user"]
                             and "/index" in result["final_url"])
        else:
            result["hit"] = (cond["notUser"] is True and result["alerts"]
                             == ["用户名或密码不正确！"] and "/login" in result["final_url"]
                             and result["sessionStorage_user"] is None)
        shot = OUT_DIR / f"{label}.png"
        drv.save_screenshot(str(shot))
        result["screenshot"] = str(shot.name)
    finally:
        drv.quit()
    return result


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r1 = observe("123456Qaq", "branch_false_correct_pwd", "false(!user为假->保存并跳转)")
    r2 = observe("Wrong123", "branch_true_wrong_pwd", "true(!user为真->提示)")
    report = {"source": "src/views/Login.vue 第83行 if (!user)，基线 8efcb99",
              "observations": [r1, r2],
              "covered_branches": f"{int(r1['hit']) + int(r2['hit'])}/2"}
    out_json = OUT_DIR / "branch_observation.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if r1["hit"] and r2["hit"] else 1)
