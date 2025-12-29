import time
import pandas as pd
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def scrape_saramin():
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온"]
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # GitHub 서버 환경에서 봇 탐지를 피하기 위한 설정
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    all_results = []

    try:
        for target_company in companies:
            print(f">>> '{target_company}' 검색 중...")
            search_url = f"https://www.saramin.co.kr/zf_user/search/recruit?search_done=y&searchword={target_company}"
            driver.get(search_url)
            time.sleep(5) # 외부 서버이므로 로딩 대기시간을 넉넉히 줌

            job_list = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            links = []
            for job in job_list: 
                try:
                    link = job.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    links.append(link)
                except: continue

            print(f"발견된 공고: {len(links)}개")

            for link in links[:5]: # 테스트를 위해 기업당 최대 5개만 수집
                try:
                    driver.get(link)
                    time.sleep(3)
                    title = driver.find_element(By.CSS_SELECTOR, ".tit_job").text.strip()
                    
                    # 상세 내용 수집 로직 (기존과 동일)
                    content_text = ""
                    if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                        driver.switch_to.frame("iframe_content_0")
                        content_text = driver.find_element(By.TAG_NAME, "body").text.strip()
                        driver.switch_to.default_content()
                    else:
                        content_text = driver.find_element(By.CSS_SELECTOR, ".user_content").text.strip()

                    all_results.append({
                        "기업명": target_company,
                        "공고명": title,
                        "내용": content_text[:500],
                        "URL": link
                    })
                except: continue

    finally:
        driver.quit()

    if all_results:
        df = pd.DataFrame(all_results)
        df.to_csv("saramin_results.csv", index=False, encoding="utf-8-sig")
        print("CSV 파일 생성 완료")

if __name__ == "__main__":
    scrape_saramin()
