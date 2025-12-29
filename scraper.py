import time
import pandas as pd
import os
import requests
import traceback
import sys
from datetime import datetime
from urllib.parse import urlparse, parse_qs

# Selenium 관련
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

def clean_saramin_url(url):
    """URL에서 고유 공고 번호만 추출하여 정제합니다."""
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
    
    # 1. 기존 데이터 로드 및 컬럼 구조 설정
    columns = ["기업명", "공고명", "공고문 컬럼", "이미지 링크", "URL", "first-seen", "completed_date"]
    
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        # 기존 파일에 '공고문 컬럼'이 없거나 '요약내용'이 있다면 이름 변경 또는 재설정
        if '요약내용' in df_old.columns:
            df_old.rename(columns={'요약내용': '공고문 컬럼'}, inplace=True)
        if '이미지링크' in df_old.columns:
            df_old.rename(columns={'이미지링크': '이미지 링크'}, inplace=True)
    else:
        df_old = pd.DataFrame(columns=columns)

    # 2. 브라우저 설정 (Headless 모드)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    scraped_urls = []

    try:
        for target_company in companies:
            print(f"\n>>> {target_company} 검색 시작...")
            driver.get(f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}")
            time.sleep(4) 

            items = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            print(f"    (검색 결과 {len(items)}개 발견)")

            for item in items:
                try:
                    # 기업명 매칭
                    corp_name = item.find_element(By.CSS_SELECTOR, ".corp_name").text.replace(" ", "")
                    if target_company not in corp_name:
                        continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link)
                    scraped_urls.append(link)

                    # 이미 상세 수집된 공고라면 스킵
                    if link in df_old['URL'].values:
                        idx = df_old[df_old['URL'] == link].index[0]
                        if pd.notna(df_old.at[idx, '공고문 컬럼']) and len(str(df_old.at[idx, '공고문 컬럼'])) > 10:
                            continue

                    title = item.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    print(f"    - 데이터 수집 중: {title[:25]}...")

                    # 상세페이지 이동
                    driver.execute_script(f"window.open('{link}');")
                    driver.switch_to.window(driver.window_handles[1])
                    time.sleep(5)

                    raw_text = ""
                    image_links = []
                    
                    # 공고문 본문(Iframe) 접근
                    if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                        driver.switch_to.frame("iframe_content_0")
                        body_element = driver.find_element(By.TAG_NAME, "body")
                        
                        # 공고문 텍스트 추출
                        raw_text = body_element.text.strip()
                        # 이미지 링크 추출
                        imgs = body_element.find_elements(By.TAG_NAME, "img")
                        image_links = [i.get_attribute("src") for i in imgs if i.get_attribute("src")]
                        
                        driver.switch_to.default_content()
                    else:
                        # Iframe이 없는 경우 일반 body에서 추출
                        raw_text = driver.find_element(By.TAG_NAME, "body").text.strip()[:3000]

                    # 데이터 저장/업데이트
                    image_links_str = "|".join(image_links)
                    
                    if link in df_old['URL'].values:
                        target_idx = df_old[df_old['URL'] == link].index[0]
                        df_old.at[target_idx, '공고문 컬럼'] = raw_text
                        df_old.at[target_idx, '이미지 링크'] = image_links_str
                    else:
                        new_row = pd.DataFrame([{
                            "기업명": target_company, 
                            "공고명": title, 
                            "공고문 컬럼": raw_text, 
                            "이미지 링크": image_links_str, 
                            "URL": link, 
                            "first-seen": today,
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

    # 3. 마감 처리 및 저장
    mask = (~df_old['URL'].isin(scraped_urls)) & (df_old['completed_date'].isna() | (df_old['completed_date'] == ""))
    df_old.loc[mask, 'completed_date'] = today
    
    df_old.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"\n[작업 완료] {len(scraped_urls)}개의 공고 데이터를 수집했습니다.")

if __name__ == "__main__":
    scrape_saramin()
