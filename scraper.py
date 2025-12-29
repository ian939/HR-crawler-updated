import time
import pandas as pd
import os
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import google.generativeai as genai
from io import BytesIO
from PIL import Image

# Gemini API 설정
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

def get_ai_summary(text, image_urls):
    """Gemini를 사용하여 텍스트와 이미지를 요약함"""
    if not text.strip() and not image_urls.strip():
        return "수집된 내용 없음"
    
    try:
        prompt = f"다음 채용 공고를 분석해서 '주요업무, 자격요건, 우대사항, 혜택'을 중심으로 5줄 이내로 간결하게 요약해줘. 한국어로 작성해.\n\n텍스트 내용: {text[:2000]}"
        contents = [prompt]

        # 이미지 처리 (헤더 추가하여 차단 방지)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        valid_imgs = [url for url in image_urls.split("|") if "http" in url][:3]
        
        for img_url in valid_imgs:
            try:
                img_res = requests.get(img_url, headers=headers, timeout=10)
                if img_res.status_code == 200:
                    img = Image.open(BytesIO(img_res.content))
                    contents.append(img)
            except Exception as e:
                print(f"이미지 다운로드 실패 ({img_url}): {e}")
                continue

        response = model.generate_content(contents)
        return response.text.strip()
    except Exception as e:
        print(f"AI 요약 중 오류 발생: {e}")
        return f"요약 실패 (오류: {str(e)[:50]})"

def scrape_saramin():
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온"]
    csv_file = "saramin_results.csv"
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 1. 기존 데이터 로드 및 전처리
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        # URL을 기준으로 중복 제거 (데이터 무결성 확보)
        df_old = df_old.drop_duplicates(subset=['URL'], keep='first')
    else:
        df_old = pd.DataFrame(columns=["기업명", "공고명", "요약내용", "이미지링크", "URL", "first-seen", "completed_date"])

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    scraped_urls = [] # 이번 회차에 발견된 URL들

    try:
        for target_company in companies:
            print(f">>> '{target_company}' 검색 중...")
            driver.get(f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}&recruitSort=relation")
            time.sleep(5)

            job_elements = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            for job in job_elements:
                try:
                    # 정확한 기업명 매칭 확인
                    corp_name = job.find_element(By.CSS_SELECTOR, ".corp_name a").text.strip()
                    if target_company not in corp_name: continue
                    
                    link = job.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href").split('?')[0] # 파라미터 제거하여 고유 URL 확보
                    scraped_urls.append(link)

                    # 이미 수집되어 있고 요약까지 완료된 건이면 건너뜀
                    if link in df_old['URL'].values:
                        existing_summary = df_old.loc[df_old['URL'] == link, '요약내용'].values[0]
                        if pd.notna(existing_summary) and "실패" not in str(existing_summary):
                            continue

                    title = job.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    
                    # 상세 페이지 이동
                    driver.execute_script("window.open('');")
                    driver.switch_to.window(driver.window_handles[1])
                    driver.get(link)
                    time.sleep(3)

                    # 내용 및 이미지 추출
                    content_text = ""
                    image_links = []
                    
                    # iframe 우선 확인
                    if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                        driver.switch_to.frame("iframe_content_0")
                        body = driver.find_element(By.TAG_NAME, "body")
                        content_text = body.text.strip()
                        image_links = [img.get_attribute("src") for img in body.find_elements(By.TAG_NAME, "img") if img.get_attribute("src")]
                        driver.switch_to.default_content()
                    else:
                        try:
                            detail = driver.find_element(By.CSS_SELECTOR, ".user_content")
                            content_text = detail.text.strip()
                            image_links = [img.get_attribute("src") for img in detail.find_elements(By.TAG_NAME, "img") if img.get_attribute("src")]
                        except: pass

                    img_str = "|".join(image_links)
                    
                    # AI 요약 수행
                    print(f"   - 신규 공고 요약 중: {title[:20]}...")
                    summary = get_ai_summary(content_text, img_str)

                    # 기존 데이터에 추가 또는 업데이트
                    if link in df_old['URL'].values:
                        df_old.loc[df_old['URL'] == link, '요약내용'] = summary
                    else:
                        new_row = pd.DataFrame([{
                            "기업명": target_company,
                            "공고명": title,
                            "요약내용": summary,
                            "이미지링크": img_str,
                            "URL": link,
                            "first-seen": today,
                            "completed_date": None
                        }])
                        df_old = pd.concat([df_old, new_row], ignore_index=True)
                    
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except:
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    continue
    finally:
        driver.quit()

    # 2. 종료된 공고 처리 (지난번엔 있었으나 이번 검색에 없는 활성 공고)
    df_old.loc[(~df_old['URL'].isin(scraped_urls)) & (df_old['completed_date'].isna()), 'completed_date'] = today

    # 3. 최종 저장 (한 번 더 중복 제거)
    df_old.drop_duplicates(subset=['URL'], keep='last').to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f">>> 모든 작업 완료. 현재 총 {len(df_old)}개 공고 관리 중.")

if __name__ == "__main__":
    scrape_saramin()
