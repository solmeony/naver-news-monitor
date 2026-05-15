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

async def scrape_keyword(page, keyword: str) -> list:
    url = f"https://search.naver.com/search.naver?where=news&query={keyword}&sm=tab_opt&sort=0"
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    articles = []

    # 뉴스 클러스터 카드 전체 선택
    clusters = await page.query_selector_all("div.news_wrap")

    for cluster in clusters:
        if len(articles) >= 5:
            break
        try:
            # 대표 기사 제목
            title_el = await cluster.query_selector("a.news_tit")
            if not title_el:
                continue
            title = await title_el.get_attribute("title") or await title_el.inner_text()
            title = title.strip()

            link = await title_el.get_attribute("href") or ""

            # 언론사명
            press_el = await cluster.query_selector("a.info.press")
            press = (await press_el.inner_text()).strip() if press_el else "알수없음"

            # 발행 시간
            time_el = await cluster.query_selector("span.info")
            pub_dt = datetime.now(KST)  # fallback
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
            print(f"[{keyword}] 파싱 오류: {e}")
            continue

    return articles

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
            # 예: 2024.04.20.
            clean = time_text.replace(".", "-").rstrip("-").strip()
            return datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=KST)
    except:
        pass
    return now

async def main():
    result = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
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
            await asyncio.sleep(2)  # 요청 간격

        await browser.close()

    # Google Apps Script 웹훅으로 전송
    webhook_url = os.environ.get("GAS_WEBHOOK_URL")
    if webhook_url:
        payload = {
            "date": datetime.now(KST).strftime("%Y-%m-%d"),
            "data": result
        }
        resp = requests.post(webhook_url, json=payload)
        print(f"GAS 전송 완료: {resp.status_code}")
    else:
        # 로컬 테스트용 출력
        print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
