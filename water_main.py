import time
import os
import re
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def scrape_water_recruitment():
    file_name = "BEP_EV_Recruitment_Master.csv"
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 1. 기존 데이터 로드 (인코딩 대응)
    df_master = None
    if os.path.exists(file_name):
        for enc in ['utf-8-sig', 'cp949', 'euc-kr', 'utf-8']:
            try:
                df_master = pd.read_csv(file_name, encoding=enc)
                print(f"기존 파일 로드 완료 (인코딩: {enc})")
                break
            except: continue
    
    if df_master is None:
        df_master = pd.DataFrame(columns=["공고명", "부문", "채용정보", "주요업무", "지원자격", "우대사항", "채용절차", "근무지", "상세URL", "first_seen", "completed_date"])

    # 2. 브라우저 설정 (우회 설정 강화)
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    # webdriver 속성 제거 (우회)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    url = "https://watercharging.com/recruitments"
    print(f"사이트 접속 중: {url}")
    
    current_jobs = []
    try:
        driver.get(url)
        time.sleep(5) # 초기 로딩 대기

        # 여러 번 스크롤하여 동적 컨텐츠 로드 유도
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

        # 모든 a 태그를 가져와서 필터링 (가장 확실한 방법)
        all_links = driver.find_elements(By.TAG_NAME, "a")
        print(f"페이지 내 총 {len(all_links)}개의 링크 탐색됨")

        for link_element in all_links:
            try:
                href = link_element.get_attribute('href')
                if href and '/recruitments/' in href:
                    # 상세페이지 패턴 확인 (/recruitments/숫자)
                    if re.search(r'/recruitments/\d+', href):
                        title = link_element.text.replace('\n', ' ').strip()
                        # 텍스트가 비어있으면 내부 span이나 div에서 다시 시도
                        if not title:
                            title = link_element.get_attribute('innerText').strip()
                        
                        if title:
                            current_jobs.append({"공고명": title, "URL": href})
            except: continue

        # 중복 제거
        current_jobs = list({v['URL']: v for v in current_jobs}.values())
        print(f"수집된 유효 공고 수: {len(current_jobs)}건")

        if not current_jobs:
            print("공고를 찾지 못했습니다. 페이지 구조를 다시 확인합니다.")
            # 디버깅용: 페이지 소스 길이 출력
            print(f"Page Source Length: {len(driver.page_source)}")

    except Exception as e:
        print(f"목록 수집 오류: {e}")
        driver.quit()
        return

    # 3. 상세 정보 수집 (기존 로직 유지)
    scraped_urls = [job['URL'] for job in current_jobs]
    new_results = []

    for job in current_jobs:
        if job['URL'] in df_master['상세URL'].values:
            df_master.loc[df_master['상세URL'] == job['URL'], 'completed_date'] = ""
            continue
            
        print(f"신규 수집: {job['공고명']}")
        try:
            driver.get(job['URL'])
            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # 본문 추출 로직
            content = soup.find('main') or soup.find('body')
            lines = content.get_text(separator="\n", strip=True).split('\n')
            
            data = {
                "공고명": job['공고명'], "부문": "WATER", "상세URL": job['URL'],
                "채용정보": "", "주요업무": "", "지원자격": "", "우대사항": "", 
                "채용절차": "", "근무지": "", "first_seen": today, "completed_date": ""
            }
            
            curr = None
            for line in lines:
                line = line.strip()
                if not line: continue
                if any(k in line for k in ["주요 업무", "주요업무", "무슨 일을"]): curr = "주요업무"
                elif any(k in line for k in ["지원 자격", "자격 요건", "찾습니다"]): curr = "지원자격"
                elif any(k in line for k in ["우대 사항", "더 좋습니다"]): curr = "우대사항"
                elif any(k in line for k in ["채용 절차", "전형 절차"]): curr = "채용절차"
                elif "근무지" in line: curr = "근무지"
                elif any(k in line for k in ["복지", "혜택", "지원하기"]): curr = None
                elif curr: data[curr] += line + "\n"
            
            new_results.append(data)
        except Exception as e:
            print(f"상세 페이지 수집 실패 ({job['URL']}): {e}")

    # 4. 마감 처리 및 저장
    active_mask = df_master['completed_date'].isna() | (df_master['completed_date'] == "")
    closed_jobs_mask = active_mask & (~df_master['상세URL'].isin(scraped_urls))
    df_master.loc[closed_jobs_mask, 'completed_date'] = today

    if new_results:
        df_final = pd.concat([df_master, pd.DataFrame(new_results)], ignore_index=True)
    else:
        df_final = df_master

    df_final.to_csv(file_name, index=False, encoding="utf-8-sig")
    print(f"\n[업데이트 완료] 신규 {len(new_results)}건 / 마감 {closed_jobs_mask.sum()}건")
    driver.quit()

if __name__ == "__main__":
    scrape_water_recruitment()
