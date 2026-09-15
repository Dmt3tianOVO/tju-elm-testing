# -*- coding: utf-8 -*-
"""
成员C 自动化冒烟脚本（复用 TC-01、TC-03，共 2 个测试，互不依赖）。

TC-01 / TC_login_func_001：
    未登录状态下在真实登录页输入真实账号/密码，等待跳转 /index，
    读取并解析 sessionStorage.user，断言 userId == 19112121212。

TC-03 / TC_business_func_003：
    自行完成登录准备后进入商家列表（美食类 orderTypeId=1），
    进入目标商家 10001「万家饺子（软件园E18店）」详情，
    在该商家食品列表中定位菜品「纯肉鲜肉（水饺）」，断言其价格为 ¥16.00
    （价格断言限定在该菜品所在的 <li> 内，不是全页面出现 16 即通过）。

运行前提见同目录《运行说明.md》。
从项目根目录执行：
    python -m pytest 05_自动化/test_smoke.py -q
"""

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ---------------- 环境与测试数据（与基线 8efcb99 的种子数据一致） ----------------
BASE_URL = os.environ.get("ELM_BASE_URL", "http://localhost:8084")
BACKEND_URL = os.environ.get("ELM_BACKEND_URL", "http://localhost:8080")
USER_ID = "19112121212"          # elm.user 种子账号（JAVA爱好者）
PASSWORD = "123456Qaq"
BUSINESS_ID = "10001"
BUSINESS_NAME = "万家饺子（软件园E18店）"
ORDER_TYPE_ID = "1"              # 美食类，business 10001 属于该类
FOOD_NAME = "纯肉鲜肉（水饺）"
FOOD_PRICE = "16.00"

WAIT_SECONDS = 15
EVIDENCE_DIR = Path(__file__).parent / "evidence" / os.environ.get("RUN_TAG", "manual")


def _build_driver():
    """每个测试构造一个干净浏览器会话（独立临时 user-data-dir，不共享 Cookie/存储）。"""
    options = Options()
    if os.environ.get("ELM_HEADFUL") != "1":
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=430,900")  # 页面按 vw 做移动端布局
    options.add_argument("--disable-dev-shm-usage")
    # 每个会话使用全新且独立的用户目录，保证 R1/R2 及两个用例之间互不污染
    user_data_dir = tempfile.mkdtemp(prefix="elm-chrome-")
    options.add_argument(f"--user-data-dir={user_data_dir}")

    driver_path = os.environ.get("CHROMEDRIVER_PATH")
    service = Service(executable_path=driver_path) if driver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_script_timeout(WAIT_SECONDS)
    return driver


@pytest.fixture
def driver(request):
    drv = _build_driver()
    yield drv
    # 无论通过失败都留一张截图，失败时文件名带 FAILED 便于组长核对
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    shot_name = f"{request.node.name}.png"
    try:
        drv.save_screenshot(str(EVIDENCE_DIR / shot_name))
    except Exception:
        pass
    drv.quit()


def _login(driver, user_id: str, password: str):
    """操作真实登录页完成登录（不允许直接写 sessionStorage 冒充登录）。"""
    driver.get(f"{BASE_URL}/login")
    wait = WebDriverWait(driver, WAIT_SECONDS)
    user_input = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "input[placeholder='手机号码']"))
    )
    pwd_input = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
    user_input.clear()
    user_input.send_keys(user_id)
    pwd_input.clear()
    pwd_input.send_keys(password)
    driver.find_element(By.XPATH, "//button[contains(., '登陆')]").click()


# ---------------- TC-01：真实登录功能 ----------------
def test_tc01_login_jump_and_session(driver):
    """未登录 -> 真实登录 -> /index；sessionStorage.user.userId == 19112121212。"""
    # 前置：全新会话必须未登录
    driver.get(f"{BASE_URL}/login")
    WebDriverWait(driver, WAIT_SECONDS).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='手机号码']"))
    )
    assert driver.execute_script("return sessionStorage.getItem('user');") is None

    _login(driver, USER_ID, PASSWORD)

    # 等待路由跳转 /index
    WebDriverWait(driver, WAIT_SECONDS).until(EC.url_contains("/index"))
    assert "/index" in driver.current_url

    # 读取并解析 sessionStorage.user
    raw_user = driver.execute_script("return sessionStorage.getItem('user');")
    assert raw_user, "登录后 sessionStorage.user 不应为空"
    user = json.loads(raw_user)
    assert user.get("userId") == "19112121212", f"userId 不匹配：{user.get('userId')}"


# ---------------- TC-03：商家列表 -> 商家详情 -> 目标菜品与价格 ----------------
def test_tc03_business_food_name_and_price(driver):
    """登录后进美食类商家列表，进入 10001，断言目标菜品及其价格（价格限定在该菜品 li 内）。"""
    _login(driver, USER_ID, PASSWORD)
    WebDriverWait(driver, WAIT_SECONDS).until(EC.url_contains("/index"))

    # 进入商家列表（美食类）
    driver.get(f"{BASE_URL}/businessList?orderTypeId={ORDER_TYPE_ID}")
    wait = WebDriverWait(driver, WAIT_SECONDS)

    # 断言目标商家确实出现在列表中（真实后端数据）
    business_entry = wait.until(
        EC.element_to_be_clickable((By.XPATH, f"//h3[normalize-space()='{BUSINESS_NAME}']"))
    )
    # 点击该商家的信息区进入详情
    business_entry.find_element(By.XPATH, "./ancestor::div[contains(@class,'business-info')]").click()

    # 详情页：URL 带 businessId=10001，且 h1 异步渲染为目标商家名
    WebDriverWait(driver, WAIT_SECONDS).until(EC.url_contains(f"businessId={BUSINESS_ID}"))
    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: d.find_element(By.CSS_SELECTOR, ".business-info h1").text.strip()
        == BUSINESS_NAME
    )
    h1 = driver.find_element(By.CSS_SELECTOR, ".business-info h1")
    assert h1.text.strip() == BUSINESS_NAME

    # 在食品列表中定位目标菜品所在的 <li>，价格断言只在该 li 内进行
    food_li = wait.until(
        EC.presence_of_element_located(
            (By.XPATH,
             f"//ul[contains(@class,'food')]/li[.//h3[normalize-space()='{FOOD_NAME}']]")
        )
    )
    name_in_detail = food_li.find_element(By.TAG_NAME, "h3").text.strip()
    assert name_in_detail == FOOD_NAME

    # 等待价格插值渲染完成（断言范围仅限本菜品 li）。
    # 注意：接口返回数值 16.00，JSON 数字经 JS 解析后尾零丢失，页面实际渲染为「¥16」，
    # 因此按数值相等断言（Decimal('16') == Decimal('16.00')），而非字符串包含。
    def _price_value(drv):
        txt = food_li.find_element(By.XPATH, ".//p[contains(., '¥')]").text.strip()
        if "¥" not in txt:
            return None
        try:
            return Decimal(txt.replace("¥", "").strip())
        except Exception:
            return None

    WebDriverWait(driver, WAIT_SECONDS).until(
        lambda d: _price_value(d) == Decimal(FOOD_PRICE)
    )
    price_text = food_li.find_element(By.XPATH, ".//p[contains(., '¥')]").text.strip()
    assert _price_value(driver) == Decimal(FOOD_PRICE), f"目标菜品价格异常：{price_text}"
