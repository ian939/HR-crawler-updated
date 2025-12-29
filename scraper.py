import time
import pandas as pd
import os
import requests
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import google.generativeai as genai
from io import BytesIO
from PIL import Image

# 1. Gemini 설정 (404 에러 방지를 위해 모델명에서 models/ 제거)
try:
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    # 최신 SDK에서는 'gemini-1.5-flash' 단독 사용이 표준입니다.
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # [디버깅 용도] 사용 가능한 모델 목록 확인 (로그에서 확인 가능)
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Available Model: {m.name}")
except Exception as e:
    print(f"Gemini 초기화 에러: {e}")

def clean_saramin_url(url):
    """URL에서 공고 번호(rec_idx)를 보존하여 중복 수집 및 1건 수집 문제 해결"""
    if not url: return ""
    u = urlparse(url)
    query = parse_qs(u.query)
    if 'rec_idx' in query:
        # 고유 번호인 rec_idx만 남겨서 모든 공고를 구분함
        new_query = {'rec_idx': query['rec_idx'][0]}
        return urlunparse((u.scheme, u.netloc, u.path, '', urlencode(new_query), ''))
    return url

def get_ai_summary(text, image_urls):
    if not text.strip() and not image_urls.strip():
        return "정보 없음"
    try:
        # 가이드 참고: 프롬프트와 데이터를 명확히 분리
        prompt = "채용 공고를 분석하여 [주요업무, 자격요건, 혜택] 위주로 5줄 내외의 한국어 요약을 작성해줘."
        contents = [prompt, f"공고 본문: {text[:2000]}"]

        headers = {"User-Agent": "Mozilla/5.0"}
        valid_imgs = [url.strip() for url in image_urls.split("|") if "http" in url][:2]
        
        for img_url in valid_imgs:
            try:
                res = requests.get(img_url, headers=headers, timeout=10)
                if res.status_code == 200:
                    contents.append(Image.open(BytesIO(res.content)))
            except: continue

        # AI 호출
        response = model.generate_content(contents)
        return response.text.strip()
    except Exception as e:
        print(f"요약 중 에러 발생: {e}")
        return f"요약 생성 실패"

def scrape_saramin():
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온"]
    csv_file = "saramin_results.csv"
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 기존 데이터 로드
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
    else:
        df_old = pd.DataFrame(columns=["기업명", "공고명", "요약내용", "이미지링크", "URL", "first-seen", "completed_date"])

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    scraped_urls = []

    try:
        for target_company in companies:
            print(f">>> {target_company} 검색 중...")
            driver.get(f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}")
            time.sleep(5)

            items = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            for item in items:
                try:
                    # 정확한 기업명 매칭
                    corp_name = item.find_element(By.CSS_SELECTOR, ".corp_name").text
                    if target_company not in corp_name: continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link) # 공고별 고유 URL 생성
                    scraped_urls.append(link)

                    # 이미 수집되어 있고 요약도 있는 경우 스킵
                    if link in df_old['URL'].values:
                        idx = df_old[df_old['URL'] == link].index[0]
                        if pd.notna(df_old.at[idx, '요약내용']) and "실패" not in str(df_old.at[idx, '요약내용']):
                            continue

                    title = item.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
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

                    summary = get_ai_summary(content_text, "|".join(image_links))

                    # 데이터 합치기
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
                except:
                    if len(driver.window_handles) > 1: driver.close(); driver.switch_to.window(driver.window_handles[0])
    finally:
        driver.quit()

    # 마감 처리 및 중복 제거
    df_old.loc[(~df_old['URL'].isin(scraped_urls)) & (df_old['completed_date'].isna()), 'completed_date'] = today
    df_old.drop_duplicates(subset=['URL'], keep='last').to_csv(csv_file, index=False, encoding="utf-8-sig")
    print("수집 및 요약 성공")

if __name__ == "__main__":
    scrape_saramin()
