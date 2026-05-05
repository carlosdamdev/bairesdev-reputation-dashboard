from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

BASE_URL = "https://clutch.co/profile/bairesdev"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
    )
    page = ctx.new_page()

    # Try direct URL navigation without hash
    page.goto(f"{BASE_URL}?page=1", wait_until="load", timeout=60000)
    try:
        page.wait_for_selector("article.profile-review", timeout=15000)
        print("Selector found")
    except:
        print("Selector timeout")

    count = page.locator("article.profile-review").count()
    print(f"Playwright count (page 2, no hash): {count}")

    html = page.content()
    soup = BeautifulSoup(html, "lxml")
    reviews = soup.select("article.profile-review")
    print(f"BeautifulSoup count: {len(reviews)}")
    if reviews:
        print("First title:", reviews[0].select_one("div.profile-review__header").get_text(strip=True)[:80])

    browser.close()
