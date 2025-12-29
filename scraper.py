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

# 1. Gemini 설정 (404 에러 방지를 위해 명칭 고정)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
# 'models/'를 붙여서 호출하는 것이 가장 안정적입니다.
model = genai.GenerativeModel('models/gemini-1.5-flash')

def clean_saramin_url(url):
    """URL에서 공고 고유 번호(rec_idx)를 보존하여 중복 방지"""
    u = urlparse(url)
    query = parse_qs(u.query)
    if 'rec_idx' in query:
        # 공고 번호는 리스트의 첫 번째 값 사용
        new_query = {'rec_idx': query['rec_idx'][0]}
        return urlunparse((u.scheme, u.netloc, u.path, '', urlencode(new_query), ''))
    return url

def get_ai_summary(text, image_urls):
    if not text.strip() and not image_urls.strip():
        return "수집된 내용 없음"
    try:
        prompt = "채용 공고 요약: 주요업무, 자격요건, 우대사항을 5줄 내외로 요약해줘. 한국어로 작성해."
        contents = [prompt, f"텍스트 내용: {text[:1500]}"]

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
        return f"요약 에러: {str(e)[:30]}"

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
                    # 기업명 매칭
                    if target_company not in item.find_element(By.CSS_SELECTOR, ".corp_name a").text:
                        continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link)
                    scraped_urls.append(link)

                    # 중복 스킵 로직
                    if link in df_old['URL'].values:
                        if "에러" not in str(df_old.loc[df_old['URL'] == link, '요약내용'].values[0]):
                            continue

                    title = item.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    driver.execute_script(f"window.open('{link}');")
                    driver.switch_to.window(driver.window_handles[1])
                    time.sleep(4)

                    # 본문/이미지 추출 (iframe 대응)
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

                    # 데이터 저장
                    if link in df_old['URL'].values:
                        df_old.loc[df_old['URL'] == link, '요약내용'] = summary
                    else:
                        new_row = pd.DataFrame([{"기업명": target_company, "공고명": title, "요약내용": summary, "이미지링크": "|".join(image_links), "URL": link, "first-seen": today}])
                        df_old = pd.concat([df_old, new_row], ignore_index=True)
                    
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except:
                    if len(driver.window_handles) > 1: driver.close(); driver.switch_to.window(driver.window_handles[0])
    finally:
        driver.quit()

    df_old.drop_duplicates(subset=['URL'], keep='last').to_csv(csv_file, index=False, encoding="utf-8-sig")
    print("수집 완료")

if __name__ == "__main__":
    scrape_saramin()
