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

# 1. Gemini 설정 (404 에러 방지를 위한 호출 방식 변경)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
# 'models/' 접두사 없이 'gemini-1.5-flash'만 사용해보세요.
model = genai.GenerativeModel('gemini-1.5-flash')

def clean_saramin_url(url):
    """URL에서 rec_idx를 유지하여 각 공고를 고유하게 식별"""
    u = urlparse(url)
    query = parse_qs(u.query)
    if 'rec_idx' in query:
        # 공고 번호인 rec_idx만 남기고 나머지는 제거하여 중복 방지
        new_query = {'rec_idx': query['rec_idx'][0]}
        return urlunparse((u.scheme, u.netloc, u.path, '', urlencode(new_query), ''))
    return url

def get_ai_summary(text, image_urls):
    if not text.strip() and not image_urls.strip():
        return "수집된 내용 없음"
    try:
        prompt = "채용 공고의 [주요업무, 자격요건, 우대사항]을 5줄 내외의 한국어로 요약해줘."
        contents = [prompt, f"텍스트: {text[:1500]}"]

        headers = {"User-Agent": "Mozilla/5.0"}
        valid_imgs = [url.strip() for url in image_urls.split("|") if "http" in url][:2]
        for img_url in valid_imgs:
            try:
                res = requests.get(img_url, headers=headers, timeout=10)
                if res.status_code == 200:
                    contents.append(Image.open(BytesIO(res.content)))
            except: continue

        response = model.generate_content(contents)
        return response.text.strip()
    except Exception as e:
        print(f"DEBUG - Gemini Error: {e}")
        return f"요약 생성 실패"

def scrape_saramin():
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온"]
    csv_file = "saramin_results.csv"
    today = datetime.now().strftime('%Y-%m-%d')
    
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
            print(f">>> {target_company} 수집 중...")
            driver.get(f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}")
            time.sleep(5)

            items = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            for item in items:
                try:
                    # 기업명 체크 강화
                    corp_name = item.find_element(By.CSS_SELECTOR, ".corp_name a").text
                    if target_company not in corp_name: continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link)
                    scraped_urls.append(link)

                    # 이미 요약 완료된 것은 건너뜀
                    if link in df_old['URL'].values:
                        if "실패" not in str(df_old.loc[df_old['URL'] == link, '요약내용'].values[0]):
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

                    # 데이터 저장 로직
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
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
    finally:
        driver.quit()

    # 마감 처리 및 중복 제거 저장
    df_old.drop_duplicates(subset=['URL'], keep='last').to_csv(csv_file, index=False, encoding="utf-8-sig")
    print("수집 및 요약 완료")

if __name__ == "__main__":
    scrape_saramin()
