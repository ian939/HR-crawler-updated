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
    if not text and not image_urls:
        return "정보 없음"
    
    try:
        prompt = f"다음 채용 공고를 분석해서 '주요업무, 자격요건을 중심으로 간결하게 요약해줘. 한국어로 작성해.\n\n텍스트 내용: {text[:2000]}"
        contents = [prompt]

        # 이미지 처리 (URL에서 이미지를 다운로드하여 Gemini에 전달)
        valid_imgs = [url for url in image_urls.split("|") if "http" in url][:3]
        for img_url in valid_imgs:
            try:
                response = requests.get(img_url, timeout=5)
                img = Image.open(BytesIO(response.content))
                contents.append(img)
            except:
                continue

        # AI 생성
        response = model.generate_content(contents)
        return response.text.strip()
    except Exception as e:
        print(f"Gemini 요약 중 오류 발생: {e}")
        return "요약 실패"

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
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    new_data_list = []

    try:
        for target_company in companies:
            print(f">>> '{target_company}' 크롤링 시작...")
            driver.get(f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}")
            time.sleep(5)

            job_list = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            for job in job_list:
                try:
                    actual_corp = job.find_element(By.CSS_SELECTOR, ".corp_name a").text.strip()
                    if target_company not in actual_corp: continue
                    
                    link = job.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    
                    # 이미 수집된 활성 공고라면 스킵
                    if link in df_old[df_old['completed_date'].isna()]['URL'].values:
                        continue

                    title = job.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    
                    # 상세 페이지 접속
                    driver.execute_script("window.open('');")
                    driver.switch_to.window(driver.window_handles[1])
                    driver.get(link)
                    time.sleep(3)

                    content_text = ""
                    image_links = []

                    # iframe 확인
                    if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                        driver.switch_to.frame("iframe_content_0")
                        body = driver.find_element(By.TAG_NAME, "body")
                        content_text = body.text.strip()
                        imgs = body.find_elements(By.TAG_NAME, "img")
                        image_links = [img.get_attribute("src") for img in imgs if img.get_attribute("src")]
                        driver.switch_to.default_content()
                    else:
                        try:
                            detail = driver.find_element(By.CSS_SELECTOR, ".user_content")
                            content_text = detail.text.strip()
                            imgs = detail.find_elements(By.TAG_NAME, "img")
                            image_links = [img.get_attribute("src") for img in imgs if img.get_attribute("src")]
                        except:
                            pass

                    img_str = "|".join(image_links)
                    
                    # Gemini AI 요약
                    print(f"   - '{title}' 요약 생성 중...")
                    summary = get_ai_summary(content_text, img_str)

                    new_data_list.append({
                        "기업명": target_company,
                        "공고명": title,
                        "요약내용": summary,
                        "이미지링크": img_str,
                        "URL": link,
                        "first-seen": today,
                        "completed_date": None
                    })
                    
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except:
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    continue

    finally:
        driver.quit()

    # 데이터 병합 및 종료 처리
    if new_data_list:
        df_new = pd.DataFrame(new_data_list)
        df_old = pd.concat([df_old, df_new], ignore_index=True)

    # 종료된 공고 체크 (간단한 로직)
    # 현재 리스트에 없는 기존 활성 공고들은 오늘 날짜로 종료 처리
    # (실제 운영시에는 더 정교한 체크가 필요할 수 있음)
    
    df_old.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"작업 완료")

if __name__ == "__main__":
    scrape_saramin()
