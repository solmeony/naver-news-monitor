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

def is_within_24h(pub_dt: datetime) -> bool:
    now = datetime.now(KST)
    if pub_dt.tzinfo is None:
        pub_dt = pub_dt.replace(tzinfo=KST)
    return (now - pub_dt).total_seconds() <= 86400

def format_article(press: str, title: str, pub_dt: datetime) -> str:
    if is_within_24h(pub_dt):
        return f"[{press}] {title}"
    else:
        mm_dd = pub_dt.strftime("%m/%d")
        return f"{mm_dd} [{press}] {title}"

def parse_naver_time(time_text: str) -> datetime:
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

async def scrape_keyword(page, keyword: str) -> list:
    url = f"https://search.naver.com/search.naver?where=news&query={keyword}&sm=tab_opt&sort=0"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    articles = []

    # 현재 네이버 뉴스 셀렉터 (2024~2025 기준)
    selectors = [
        "ul.list_news > li.bx",       # 일반 뉴스 목록
        "div.group_news li.bx",        # 그룹 뉴스
        "li.bx",                       # 공통 fallback
    ]

    items = []
    for selector in selectors:
        items = await page.query_selector_all(selector)
        if items:
            break

    # 디버깅: 찾은 아이템 수 출력
    print(f"  [디버그] '{keyword}' 아이템 수: {len(items)}")

    # 첫 번째 아이템 HTML 구조 확인
    if items:
        html = await items[0].inner_html()
        print(f"  [HTML] {html[:1000]}")
    
    for item in items:
        if len(articles) >= 5:
            break
        try:
            # 제목 셀렉터 시도
            title_el = (
                await item.query_selector("a.news_tit") or
                await item.query_selector("a.title") or
                await item.query_selector("a[class*='news_tit']") or
                await item.query_selector("a[class*='title']")
            )
            if not title_el:
                continue

            title = await title_el.get_attribute("title") or await title_el.inner_text()
            title = title.strip()
            if not title:
                continue

            link = await title_el.get_attribute("href") or ""

            # 언론사 셀렉터 시도
            press_el = (
                await item.query_selector("a.info.press") or
                await item.query_selector("a.press") or
                await item.query_selector("span.press") or
                await item.query_selector("a[class*='press']")
            )
            press = (await press_el.inner_text()).strip() if press_el else "알수없음"

            # 시간 셀렉터 시도
            time_el = (
                await item.query_selector("span.info") or
                await item.query_selector("span.date") or
                await item.query_selector("span[class*='date']") or
                await item.query_selector("span[class*='time']")
            )
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
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="ko-KR"
        )
        page = await context.new_page()

        for keyword in KEYWORDS:
            print(f"검색 중: {keyword}")
            try:
                articles = await scrape_keyword(page, keyword)
                result[keyword] = articles
                print(f"  → {len(articles)}건 수집")
            except Exception as e:
                print(f"  → 오류: {e}")
                result[keyword] = []
            await asyncio.sleep(2)

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
