import time
import pandas as pd
import os
import requests
import traceback
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from io import BytesIO
from PIL import Image

# Selenium 관련
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# 최신 Gemini SDK (google-genai)
try:
    from google import genai
    from google.genai import types
except ImportError:
    print("오류: 'pip install -U google-genai'를 실행하여 최신 SDK를 설치하세요.")

# ==========================================
# 1. Gemini API 설정 (최신 SDK 방식)
# ==========================================
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

def get_ai_summary(text, image_urls):
    if not text.strip() and not image_urls.strip():
        return "정보 없음"
    
    try:
        prompt = "채용 공고를 분석하여 [주요업무, 자격요건, 혜택] 위주로 5줄 내외의 한국어 요약을 작성해줘."
        contents = [prompt, f"공고 본문 내용:\n{text[:4000]}"]

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        valid_imgs = [url.strip() for url in image_urls.split("|") if "http" in url]
        
        img_count = 0
        for img_url in valid_imgs:
            if img_count >= 1: break # 안정성을 위해 이미지 1장만 포함
            try:
                res = requests.get(img_url, headers=headers, timeout=5)
                if res.status_code == 200:
                    img = Image.open(BytesIO(res.content))
                    img.thumbnail((1024, 1024))
                    contents.append(img)
                    img_count += 1
            except: continue

        # 최신 SDK 호출 방식
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(temperature=0.2)
        )
        
        return response.text.strip() if response.text else "AI 응답 없음"

    except Exception as e:
        print(f"--- Gemini API 에러: {e}")
        return f"요약 생성 실패 (사유: {str(e)[:50]})"

# ==========================================
# 2. 크롤링 메인 로직
# ==========================================

def clean_saramin_url(url):
    if not url: return ""
    u = urlparse(url)
    query = parse_qs(u.query)
    if 'rec_idx' in query:
        return f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={query['rec_idx'][0]}"
    return url

def scrape_saramin():
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온"]
    csv_file = "saramin_results.csv"
    today = datetime.now().strftime('%Y-%m-%d')
    
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        # dtype 경고 방지를 위해 미리 변환
        df_old['completed_date'] = df_old['completed_date'].astype(object)
    else:
        df_old = pd.DataFrame(columns=["기업명", "공고명", "요약내용", "이미지링크", "URL", "first-seen", "completed_date"])

    options = Options()
    options.add_argument("--headless") 
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    scraped_urls = []

    try:
        for target_company in companies:
            print(f"\n>>> {target_company} 검색 중...")
            driver.get(f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}")
            time.sleep(5) # 로딩 시간 충분히 확보

            items = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            print(f"    (검색 결과 {len(items)}개 발견)")

            for item in items:
                try:
                    # 기업명 매칭 확인 (공백 제거 후 비교)
                    corp_name = item.find_element(By.CSS_SELECTOR, ".corp_name").text.replace(" ", "")
                    if target_company not in corp_name:
                        continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link)
                    scraped_urls.append(link)

                    # 기존 데이터 확인 로직
                    if link in df_old['URL'].values:
                        existing = df_old[df_old['URL'] == link].iloc[0]
                        if pd.notna(existing['요약내용']) and "실패" not in str(existing['요약내용']):
                            continue

                    title = item.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    print(f"    - 요약 시도 중: {title[:20]}")

                    # 상세페이지 이동
                    driver.execute_script(f"window.open('{link}');")
                    driver.switch_to.window(driver.window_handles[1])
                    time.sleep(5)

                    content_text = ""
                    image_links = []
                    
                    if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                        driver.switch_to.frame("iframe_content_0")
                        body = driver.find_element(By.TAG_NAME, "body")
                        content_text = body.text.strip()
                        image_links = [i.get_attribute("src") for i in body.find_elements(By.TAG_NAME, "img") if i.get_attribute("src")]
                        driver.switch_to.default_content()
                    else:
                        content_text = driver.find_element(By.TAG_NAME, "body").text[:2000]

                    # AI 요약 수행
                    summary = get_ai_summary(content_text, "|".join(image_links))

                    if link in df_old['URL'].values:
                        df_old.loc[df_old['URL'] == link, '요약내용'] = summary
                    else:
                        new_row = pd.DataFrame([{
                            "기업명": target_company, "공고명": title, "요약내용": summary, 
                            "이미지링크": "|".join(image_links), "URL": link, "first-seen": today
                        }])
                        df_old = pd.concat([df_old, new_row], ignore_index=True)
                    
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception as e:
                    print(f"      개별 공고 처리 오류: {e}")
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])

    finally:
        driver.quit()

    # 마무리 및 저장
    df_old.loc[(~df_old['URL'].isin(scraped_urls)) & (df_old['completed_date'].isna()), 'completed_date'] = today
    df_old.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print("\n[수집 완료] CSV 파일이 업데이트되었습니다.")

if __name__ == "__main__":
    scrape_saramin()
