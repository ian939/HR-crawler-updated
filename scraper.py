import time
import pandas as pd
import os
import requests
import traceback
import sys
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

# 1. 최신 Gemini SDK 로드 및 API 설정
try:
    from google import genai
    from google.genai import types
    print("Gemini SDK 로드 성공")
except ImportError:
    print("오류: 'google-genai' 패키지가 설치되지 않았습니다. GitHub Actions yml 파일에 'pip install google-genai'를 추가하세요.")
    sys.exit(1)

# API KEY 설정 (환경 변수 우선)
API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    print("오류: GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
    sys.exit(1)

# API 키 설정 바로 아래에 넣어서 딱 한 번만 실행해 보세요
try:
    print("--- 사용 가능한 모델 목록 조회 시작 ---")
    for m in client.models.list():
        print(f"발견된 모델 ID: {m.name}")
    print("--- 조회 완료 ---")
except Exception as e:
    print(f"모델 목록을 가져오지 못했습니다: {e}")

# 클라이언트 초기화
client = genai.Client(api_key=API_KEY)



# ==========================================
# 2. 보조 함수 정의
# ==========================================

def get_ai_summary(text, image_urls):
    """
    404 에러 방지를 위해 모델명을 정규화하고, 
    에러 발생 시 대체 모델(flash-002 등)을 자동으로 시도합니다.
    """
    if not text.strip() and not image_urls.strip():
        return "정보 없음"
    
    # 404 에러를 방지하기 위한 후보 모델 리스트
    model_list = ['gemini-1.5-flash', 'gemini-1.5-flash-002']
    
    for model_id in model_list:
        try:
            prompt = "채용 공고를 분석하여 [주요업무, 자격요건, 혜택] 위주로 5줄 내외의 한국어 요약을 작성해줘."
            contents = [prompt, f"공고 본문 내용:\n{text[:4000]}"]

            # 이미지 처리 (안정성을 위해 최대 1장만)
            headers = {"User-Agent": "Mozilla/5.0"}
            valid_imgs = [url.strip() for url in image_urls.split("|") if "http" in url]
            if valid_imgs:
                try:
                    res = requests.get(valid_imgs[0], headers=headers, timeout=5)
                    if res.status_code == 200:
                        img = Image.open(BytesIO(res.content))
                        img.thumbnail((1024, 1024))
                        contents.append(img)
                except:
                    pass

            # AI 호출 (models/ 접두사 없이 모델 ID만 사용)
            response = client.models.generate_content(
                model=model_id,
                contents=contents,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            
            if response.text:
                return response.text.strip()
            
        except Exception as e:
            if "404" in str(e):
                print(f"모델 {model_id} 찾기 실패(404), 다음 모델로 재시도합니다.")
                continue
            else:
                print(f"Gemini API 에러 ({model_id}): {e}")
                return f"요약 실패 (사유: {str(e)[:30]})"

    return "모든 모델 호출 실패 (404 지속)"

def clean_saramin_url(url):
    if not url: return ""
    u = urlparse(url)
    query = parse_qs(u.query)
    if 'rec_idx' in query:
        return f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={query['rec_idx'][0]}"
    return url

# ==========================================
# 3. 크롤링 메인 로직
# ==========================================

def scrape_saramin():
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온"]
    csv_file = "saramin_results.csv"
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 기존 데이터 로드 및 타입 고정 (SettingWithCopyWarning 방지)
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        df_old['completed_date'] = df_old['completed_date'].astype(str).replace('nan', '')
    else:
        df_old = pd.DataFrame(columns=["기업명", "공고명", "요약내용", "이미지링크", "URL", "first-seen", "completed_date"])

    # 브라우저 설정 (GitHub Actions 최적화)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
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
                    if target_company not in corp_name:
                        continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link)
                    scraped_urls.append(link)

                    # 기존 데이터가 있고 요약도 성공했다면 스킵
                    if link in df_old['URL'].values:
                        existing_idx = df_old[df_old['URL'] == link].index[0]
                        if pd.notna(df_old.at[existing_idx, '요약내용']) and "실패" not in str(df_old.at[existing_idx, '요약내용']):
                            continue

                    title = item.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    print(f"    - 요약 시도 중: {title[:25]}...")

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
                            "이미지링크": "|".join(image_links), "URL": link, "first-seen": today,
                            "completed_date": ""
                        }])
                        df_old = pd.concat([df_old, new_row], ignore_index=True)
                    
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception as e:
                    print(f"      오류 발생: {e}")
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])

    finally:
        driver.quit()

    # 마감 처리 (오늘 검색되지 않은 기존 공고들)
    mask = (~df_old['URL'].isin(scraped_urls)) & ((df_old['completed_date'] == "") | (df_old['completed_date'].isna()))
    df_old.loc[mask, 'completed_date'] = today
    
    # 저장
    df_old.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"\n[작업 완료] {len(scraped_urls)}개의 공고를 처리했습니다.")

if __name__ == "__main__":
    scrape_saramin()
