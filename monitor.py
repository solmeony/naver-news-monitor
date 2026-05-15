import asyncio
import json
import os
import requests
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

KEYWORDS = [
    "허영인", "허진수", "허희수", "상미당홀딩스",
    "SPC", "파리바게뜨", "배스킨라빈스", "던킨", "삼립"
]

KST = timezone(timedelta(hours=9))


def is_within_24h(pub_dt):
    now = datetime.now(KST)
    if pub_dt.tzinfo is None:
        pub_dt = pub_dt.replace(tzinfo=KST)
    return (now - pub_dt).total_seconds() <= 86400


def format_article(press, title, pub_dt):
    if is_within_24h(pub_dt):
        return f"[{press}] {title}"
    else:
        mm_dd = pub_dt.strftime("%m/%d")
        return f"{mm_dd} [{press}] {title}"


def parse_naver_time(time_text):
    now = datetime.now(KST)
    try:
        if "분 전" in time_text:
            mins = int(time_text.replace("분 전", "").strip())
            return now - timedelta(minutes=mins)
        elif "시간 전" in time_text:
            hours = int(time_text.replace("시간 전", "").strip())
            return now - timedelta(hours=hours)
        elif "일 전" in time_text:
            days = int(time_text.replace("일 전", "").strip())
            return now - timedelta(days=days)
        elif "." in time_text:
            clean = time_text.replace(".", "-").rstrip("-").strip()
            return datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=KST)
    except Exception:
        pass
    return now


async def scrape_keyword(page, keyword):
    url = f"https://search.naver.com/search.naver?where=news&query={keyword}&sm=tab_opt&sort=0"

    await page.goto(url, wait_until="networkidle", timeout=60000)

    # 뉴스 목록 로드 대기 (최대 10초)
    try:
        await page.wait_for_selector("ul.list_news", timeout=10000)
    except Exception:
        print(f"  [경고] '{keyword}' 뉴스 목록 로드 대기 타임아웃")

    await page.wait_for_timeout(2000)

    articles = []

    # 실제 뉴스 기사만 선택 (div.news_area 포함된 것만)
    items = await page.query_selector_all("ul.list_news > li.bx")
    print(f"  [디버그] '{keyword}' ul.list_news li.bx → {len(items)}개")

    if not items:
        # 페이지 전체 HTML 일부 출력해서 구조 파악
        body = await page.inner_html("body")
        print(f"  [BODY HTML] {body[:3000]}")
        return articles

    for item in items:
        if len(articles) >= 5:
            break
        try:
            # 뉴스 기사 영역인지 확인
            news_area = await item.query_selector("div.news_area")
            if not news_area:
                continue

            title_el = await news_area.query_selector("a.news_tit")
            if not title_el:
                continue

            title = await title_el.get_attribute("title")
            if not title:
                title = await title_el.inner_text()
            title = title.strip()
            if not title:
                continue

            link = await title_el.get_attribute("href") or ""

            # 언론사
            press_el = await news_area.query_selector("a.info.press")
            if not press_el:
                press_el = await news_area.query_selector("a.press")
            press = "알수없음"
            if press_el:
                press = (await press_el.inner_text()).strip()

            # 시간
            time_el = await news_area.query_selector("span.info")
            if not time_el:
                time_el = await news_area.query_selector("span.date")
            pub_dt = datetime.now(KST)
            if time_el:
                time_text = (await time_el.inner_text()).strip()
                pub_dt = parse_naver_time(time_text)

            formatted = format_article(press, title, pub_dt)
            articles.append({
                "formatted": formatted,
                "link": link,
                "press": press,
                "title": title,
            })
        except Exception as e:
            print(f"  [파싱 오류] {e}")
            continue

    return articles


async def main():
    result = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="ko-KR",
            viewport={"width": 1280, "height": 800},
            java_script_enabled=True,
        )

        # 자동화 감지 우회
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = await context.new_page()

        # 네이버 메인 먼저 방문 (쿠키 세팅)
        await page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        for keyword in KEYWORDS:
            print(f"검색 중: {keyword}")
            try:
                articles = await scrape_keyword(page, keyword)
                result[keyword] = articles
                print(f"  → {len(articles)}건 수집")
            except Exception as e:
                print(f"  → 오류: {e}")
                result[keyword] = []
            await asyncio.sleep(3)

        await browser.close()

    webhook_url = os.environ.get("GAS_WEBHOOK_URL")
    if webhook_url:
        payload = {
            "date": datetime.now(KST).strftime("%Y-%m-%d"),
            "data": result
        }
        resp = requests.post(webhook_url, json=payload)
        print(f"GAS 전송 완료: {resp.status_code}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
