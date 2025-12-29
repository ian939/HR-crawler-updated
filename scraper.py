import time
import pandas as pd
import os
import requests
import sys
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from io import BytesIO
from PIL import Image

# Selenium 관련
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# 1. Gemini SDK 로드 및 클라이언트 설정 (순서 중요)
try:
    from google import genai
    from google.genai import types
    print("Gemini SDK 로드 성공")
except ImportError:
    print("오류: 'google-genai' 패키지가 필요합니다.")
    sys.exit(1)

# API KEY 설정
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("오류: GEMINI_API_KEY 환경 변수가 없습니다.")
    sys.exit(1)

# 클라이언트 먼저 정의
client = genai.Client(api_key=API_KEY)

# [디버깅] 사용 가능한 모델 목록 출력 (이제 client가 정의되어 에러가 나지 않습니다)
try:
    print("--- 사용 가능한 모델 목록 조회 ---")
    models = client.models.list()
    for m in models:
        print(f"사용 가능 모델: {m.name}")
    print("--------------------------------")
except Exception as e:
    print(f"모델 목록 조회 실패: {e}")

# ==========================================
# 2. 요약 함수 (404 방어 로직 강화)
# ==========================================

def get_ai_summary(text, image_urls):
    if not text.strip():
        return "본문 내용 없음"
    
    # 시도할 모델 순서 (Flash -> 8b 순서로 시도)
    # 8b 모델은 지역 제한이 적어 404 해결에 유리합니다.
    model_candidates = ['gemini-1.5-flash', 'gemini-1.5-flash-8b', 'gemini-1.5-flash-002']
    
    for model_id in model_candidates:
        try:
            prompt = "채용 공고를 분석하여 [주요업무, 자격요건, 혜택] 위주로 5줄 내외의 한국어 요약을 작성해줘."
            # 404가 계속되면 안정성을 위해 텍스트만 먼저 시도해봅니다.
            contents = [prompt, f"공고 본문:\n{text[:3500]}"]

            response = client.models.generate_content(
                model=model_id,
                contents=contents,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            
            if response.text:
                return response.text.strip()
                
        except Exception as e:
            err_msg = str(e)
            if "404" in err_msg:
                print(f"    [404 에러] {model_id} 접근 불가. 다음 모델 시도 중...")
                continue
            else:
                print(f"    [API 에러] {model_id}: {err_msg[:50]}")
                return f"요약 실패 ({err_msg[:20]})"

    return "모든 모델 호출 실패 (404 지속: API 키 권한 확인 필요)"

# ==========================================
# 3. 크롤링 로직 (기존과 동일)
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
    else:
        df_old = pd.DataFrame(columns=["기업명", "공고명", "요약내용", "이미지링크", "URL", "first-seen", "completed_date"])

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    scraped_urls = []

    try:
        for target_company in companies:
            print(f"\n>>> {target_company} 검색 중...")
            driver.get(f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}")
            time.sleep(5) 

            items = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            print(f"    (검색 결과 {len(items)}개 발견)")

            for item in items:
                try:
                    corp_name = item.find_element(By.CSS_SELECTOR, ".corp_name").text.replace(" ", "")
                    if target_company not in corp_name: continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link)
                    scraped_urls.append(link)

                    if link in df_old['URL'].values:
                        idx = df_old[df_old['URL'] == link].index[0]
                        if pd.notna(df_old.at[idx, '요약내용']) and "실패" not in str(df_old.at[idx, '요약내용']):
                            continue

                    title = item.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    print(f"    - 요약 시도 중: {title[:20]}...")

                    driver.execute_script(f"window.open('{link}');")
                    driver.switch_to.window(driver.window_handles[1])
                    time.sleep(5)

                    if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                        driver.switch_to.frame("iframe_content_0")
                        content_text = driver.find_element(By.TAG_NAME, "body").text.strip()
                        driver.switch_to.default_content()
                    else:
                        content_text = driver.find_element(By.TAG_NAME, "body").text[:2000]

                    # AI 요약
                    summary = get_ai_summary(content_text, "")

                    if link in df_old['URL'].values:
                        df_old.loc[df_old['URL'] == link, '요약내용'] = summary
                    else:
                        new_row = pd.DataFrame([{"기업명": target_company, "공고명": title, "요약내용": summary, "URL": link, "first-seen": today}])
                        df_old = pd.concat([df_old, new_row], ignore_index=True)
                    
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception as e:
                    print(f"      오류: {e}")
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
    finally:
        driver.quit()

    df_old.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print("\n[작업 완료]")

if __name__ == "__main__":
    scrape_saramin()
