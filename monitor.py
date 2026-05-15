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

    selectors = [
        "ul.list_news > li.bx:has(a.news_tit)",
        "li.bx:has(a.news_tit)",
        "li.bx:has(a[href*='news.naver'])",
        "li.bx:has(a[href*='http'])",
    ]

    items = []
    for selector in selectors:
        items = await page.query_selector_all(selector)
        if items:
            print(f"  [디버그] '{keyword}' 셀렉터 '{selector}' → {len(items)}개")
            break

    if not items:
        # 셀렉터 전부 실패시 첫번째 li.bx HTML 출력
        all_items = await page.query_selector_all("li.bx")
        print(f"  [디버그] '{keyword}' 전체 li.bx: {len(all_items)}개")
        if all_items:
            html = await all_items[1].inner_html()  # 두번째 아이템 확인 (첫번째는 정렬UI)
            print(f"  [HTML] {html[:2000]}")
        return articles

    for item in items:
        if len(articles) >= 5:
            break
        try:
            title_el = (
                await item.query_selector("a.news_tit") or
                await item.query_selector("a.title") or
                await item.query_selector("a[class*='news_tit']") or
                await item.query_selector("a[class*='title']")
            )
            if not title_el:
                html = await item.inner_html()
                print(f"  [제목없음 HTML] {html[:500]}")
                continue

            title = await title_el.get_attribute("title") or await title_el.inner_text()
            title = title.strip()
            if not title:
                continue

            link = await title_el.get_attribute("href") or ""

            press_el = (
                await item.query_selector("a.info.press") or
                await item.query_selector("a.press") or
                await item.query_selector("span.press") or
                await item.query_selector("a[class*='press']")
            )
            press = (await press_el.inner_text()).strip() if press_el else "알수없음"

            time_el = (
                await item.query_selector("span.info") or
                await item.query_selector("span.date") or
                await i
