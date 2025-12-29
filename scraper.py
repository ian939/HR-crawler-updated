import time
import pandas as pd
import os
import requests
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
    
    # 1. 컬럼 구조 설정 ('경력' 컬럼을 3번째 자리에 추가)
    columns = ["기업명", "공고명", "경력", "공고문 컬럼", "이미지 링크", "URL", "first-seen", "completed_date"]
    
    # 기존 데이터 로드 및 구조 맞추기
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        # 컬럼 순서나 이름이 다를 경우를 대비해 재설정
        for col in columns:
            if col not in df_old.columns:
                df_old[col] = ""
        df_old = df_old[columns]
    else:
        df_old = pd.DataFrame(columns=columns)

    # 2. 브라우저 설정
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
                    # 기업명 매칭 확인
                    corp_name = item.find_element(By.CSS_SELECTOR, ".corp_name").text.replace(" ", "")
                    if target_company not in corp_name:
                        continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link)
                    scraped_urls.append(link)

                    # 검색 결과 페이지에서 바로 경력 정보 추출
                    try:
                        # .job_condition 안의 두 번째 span이 주로 경력 정보입니다.
                        condition_spans = item.find_elements(By.CSS_SELECTOR, ".job_condition span")
                        experience = condition_spans[1].text if len(condition_spans) > 1 else "정보없음"
                    except:
                        experience = "정보없음"

                    # 이미 수집된 URL이고 데이터가 차 있다면 스킵 (업데이트가 필요한 경우 주석 처리)
                    if link in df_old['URL'].values:
                        idx = df_old[df_old['URL'] == link].index[0]
                        if pd.notna(df_old.at[idx, '공고문 컬럼']) and len(str(df_old.at[idx, '공고문 컬럼'])) > 20:
                            continue

                    title = item.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    print(f"    - 데이터 수집 중: {title[:20]}... ({experience})")

                    # 상세페이지 이동 (텍스트 및 이미지 추출용)
                    driver.execute_script(f"window.open('{link}');")
                    driver.switch_to.window(driver.window_handles[1])
                    time.sleep(5)

                    raw_text = ""
                    image_links = []
                    
                    # 상세 공고문 내용 추출 (Iframe 우선)
                    if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                        driver.switch_to.frame("iframe_content_0")
                        body_element = driver.find_element(By.TAG_NAME, "body")
                        raw_text = body_element.text.strip()
                        imgs = body_element.find_elements(By.TAG_NAME, "img")
                        image_links = [i.get_attribute("src") for i in imgs if i.get_attribute("src")]
                        driver.switch_to.default_content()
                    else:
                        # Iframe이 없는 경우
                        raw_text = driver.find_element(By.TAG_NAME, "body").text.strip()[:5000]

                    image_links_str = "|".join(image_links)
                    
                    # 데이터 저장
                    if link in df_old['URL'].values:
                        t_idx = df_old[df_old['URL'] == link].index[0]
                        df_old.at[t_idx, '경력'] = experience
                        df_old.at[t_idx, '공고문 컬럼'] = raw_text
                        df_old.at[t_idx, '이미지 링크'] = image_links_str
                    else:
                        new_row = pd.DataFrame([{
                            "기업명": target_company, 
                            "공고명": title, 
                            "경력": experience,
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
                    print(f"      세부 오류: {e}")
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])

    finally:
        driver.quit()

    # 3. 마감 처리 및 CSV 저장
    mask = (~df_old['URL'].isin(scraped_urls)) & (df_old['completed_date'].isna() | (df_old['completed_date'] == ""))
    df_old.loc[mask, 'completed_date'] = today
    
    # 컬럼 순서 최종 고정 후 저장
    df_old = df_old[columns]
    df_old.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"\n[작업 완료] '경력' 정보가 포함된 {len(scraped_urls)}개의 공고 데이터를 저장했습니다.")

if __name__ == "__main__":
    scrape_saramin()
