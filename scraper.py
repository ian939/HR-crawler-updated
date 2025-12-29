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

# 1. Gemini 설정 (가장 안정적인 호출 방식)
try:
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    # 모델명에서 'models/'를 빼고 호출하는 것이 최신 SDK의 표준입니다.
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    print(f"Gemini 초기화 에러: {e}")

def clean_saramin_url(url):
    """공고 고유 번호를 유지하여 중복 수집 방지"""
    if not url: return ""
    u = urlparse(url)
    query = parse_qs(u.query)
    if 'rec_idx' in query:
        new_query = {'rec_idx': query['rec_idx'][0]}
        return urlunparse((u.scheme, u.netloc, u.path, '', urlencode(new_query), ''))
    return url

def get_ai_summary(text, image_urls):
    if not text.strip() and not image_urls.strip():
        return "정보 없음"
    try:
        prompt = "채용 공고의 핵심(주요업무, 자격요건, 혜택)을 구직자 관점에서 5줄 내외 한국어로 요약해줘."
        # 안전한 데이터 전달을 위해 리스트 구성
        contents = [prompt, f"본문 내용:\n{text[:1500]}"]

        headers = {"User-Agent": "Mozilla/5.0"}
        valid_imgs = [url.strip() for url in image_urls.split("|") if "http" in url][:2]
        
        for img_url in valid_imgs:
            try:
                res = requests.get(img_url, headers=headers, timeout=10)
                if res.status_code == 200:
                    contents.append(Image.open(BytesIO(res.content)))
            except: continue

        # AI 호출 및 응답 처리
        response = model.generate_content(contents)
        
        # 성인물/폭력성 등 세이프티 필터에 걸릴 경우를 대비
        if response.candidates and response.candidates[0].content.parts:
            return response.text.strip()
        else:
            return "요약 실패: AI가 내용을 분석할 수 없음 (Safety Filter)"
            
    except Exception as e:
        print(f"Gemini 호출 상세 에러: {e}")
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
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    scraped_urls = []

    try:
        for target_company in companies:
            print(f">>> {target_company} 공고 확인 중...")
            driver.get(f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}")
            time.sleep(5)

            items = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            for item in items:
                try:
                    # 정확한 기업명 매칭
                    if target_company not in item.find_element(By.CSS_SELECTOR, ".corp_name").text:
                        continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link)
                    scraped_urls.append(link)

                    # 이미 수집된 완료 공고는 패스
                    if link in df_old['URL'].values:
                        idx = df_old[df_old['URL'] == link].index[0]
                        if pd.notna(df_old.at[idx, '요약내용']) and "에러" not in str(df_old.at[idx, '요약내용']):
                            continue

                    title = item.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    driver.execute_script(f"window.open('{link}');")
                    driver.switch_to.window(driver.window_handles[1])
                    time.sleep(5)

                    # 공고 상세 내용 추출
                    content_text = ""
                    image_links = []
                    
                    try:
                        if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                            driver.switch_to.frame("iframe_content_0")
                            body = driver.find_element(By.TAG_NAME, "body")
                            content_text = body.text.strip()
                            image_links = [i.get_attribute("src") for i in body.find_elements(By.TAG_NAME, "img") if i.get_attribute("src")]
                            driver.switch_to.default_content()
                        else:
                            content_text = driver.find_element(By.TAG_NAME, "body").text[:2000]
                    except:
                        content_text = "상세내용 추출 불가"

                    summary = get_ai_summary(content_text, "|".join(image_links))

                    # 데이터 병합 (Update or Insert)
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

    # 마감 처리 및 저장
    df_old.loc[(~df_old['URL'].isin(scraped_urls)) & (df_old['completed_date'].isna()), 'completed_date'] = today
    df_old.drop_duplicates(subset=['URL'], keep='last').to_csv(csv_file, index=False, encoding="utf-8-sig")
    print("모든 작업이 완료되었습니다.")

if __name__ == "__main__":
    scrape_saramin()
