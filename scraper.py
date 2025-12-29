import time
import pandas as pd
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

def scrape_saramin():
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온"]
    csv_file = "saramin_results.csv"
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 기존 데이터 로드 (없으면 빈 데이터프레임)
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
    else:
        df_old = pd.DataFrame(columns=["기업명", "공고명", "내용", "이미지링크", "URL", "first-seen", "completed_date"])

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    new_data = []

    try:
        for target_company in companies:
            print(f">>> '{target_company}' 검색 중...")
            # 검색 결과에서 기업명을 더 정확히 매칭하기 위해 검색어 수정
            search_url = f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}"
            driver.get(search_url)
            time.sleep(5)

            job_list = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            for job in job_list:
                try:
                    # 1) 정확한 기업명 체크 (타사 공고 배제)
                    actual_corp = job.find_element(By.CSS_SELECTOR, ".corp_name a").text.strip()
                    if target_company not in actual_corp:
                        continue
                    
                    link = job.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    title = job.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    
                    # 상세 페이지 접속
                    driver.execute_script("window.open('');")
                    driver.switch_to.window(driver.window_handles[1])
                    driver.get(link)
                    time.sleep(3)

                    content_text = ""
                    image_links = []

                    # 2) 내용 및 이미지 URL 수집 강화
                    if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                        driver.switch_to.frame("iframe_content_0")
                        body = driver.find_element(By.TAG_NAME, "body")
                        content_text = body.text.strip()
                        # 이미지 태그 모두 찾기
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
                            content_text = "내용 없음"

                    new_data.append({
                        "기업명": target_company,
                        "공고명": title,
                        "내용": content_text[:1000], # 너무 길면 잘라냄
                        "이미지링크": "|".join(image_links),
                        "URL": link,
                        "temp_active": True # 현재 활성 상태 표시
                    })
                    
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception as e:
                    print(f"상세 수집 오류: {e}")
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    continue

    finally:
        driver.quit()

    # 3) 날짜 관리 로직 (First-seen, Completed_date)
    df_new = pd.DataFrame(new_data)
    
    if not df_new.empty:
        # URL 기준으로 중복 제거 및 병합
        for idx, row in df_new.iterrows():
            if row['URL'] in df_old['URL'].values:
                # 기존에 있던 공고: first-seen 유지, completed_date 초기화(재활성화 대비)
                df_old.loc[df_old['URL'] == row['URL'], 'completed_date'] = None
            else:
                # 새로운 공고: 오늘 날짜로 first-seen 추가
                new_row = row.to_dict()
                new_row['first-seen'] = today
                new_row['completed_date'] = None
                df_old = pd.concat([df_old, pd.DataFrame([new_row])], ignore_index=True)

        # 4) 공고 종료 처리: 이번 스캔에 없는데 기존에 '활성'이었던 것들
        active_urls = df_new['URL'].tolist()
        df_old.loc[(~df_old['URL'].isin(active_urls)) & (df_old['completed_date'].isna()), 'completed_date'] = today

    # 임시 컬럼 제거 후 저장
    if 'temp_active' in df_old.columns:
        df_old = df_old.drop(columns=['temp_active'])
    
    df_old.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"업데이트 완료: {len(df_new)}개 공고 처리됨")

if __name__ == "__main__":
    scrape_saramin()
