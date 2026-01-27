import time
import os
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
    
    # 1. 기존 데이터 로드 (인코딩 에러 해결 로직)
    df_master = None
    if os.path.exists(file_name):
        # 여러 인코딩 방식을 순차적으로 시도합니다.
        encodings = ['utf-8-sig', 'cp949', 'euc-kr', 'utf-8']
        for enc in encodings:
            try:
                df_master = pd.read_csv(file_name, encoding=enc)
                print(f"성공적으로 파일을 읽었습니다. (인코딩: {enc})")
                break
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        
        if df_master is None:
            print("파일을 읽을 수 없습니다. 인코딩을 확인해주세요.")
            return
    else:
        # 파일이 없는 경우 빈 데이터프레임 생성
        df_master = pd.DataFrame(columns=[
            "공고명", "부문", "채용정보", "주요업무", "지원자격", 
            "우대사항", "채용절차", "근무지", "상세URL", "first_seen", "completed_date"
        ])

    chrome_options = Options()
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    url = "https://watercharging.com/recruitments"
    print(f"접속 시도: {url}")
    
    try:
        driver.get(url)
        time.sleep(5) # 페이지 로딩 대기시간 충분히 확보
        
        # 워터 사이트는 동적으로 공고가 로드되므로 스크롤을 수행합니다.
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        # 공고 링크 요소 대기
        wait = WebDriverWait(driver, 20)
        # a 태그 중 href에 recruitments/ 가 포함된 요소 탐색
        items = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//a[contains(@href, '/recruitments/')]")))
        
        current_jobs = []
        for item in items:
            link = item.get_attribute('href')
            # 상세 페이지 링크인 경우만 수집 (예: .../recruitments/123)
            if link.split('/')[-1].isdigit():
                title = item.text.replace('\n', ' ').strip()
                if title:
                    current_jobs.append({"공고명": title, "URL": link})
        
        # 중복 제거
        current_jobs = list({v['URL']: v for v in current_jobs}.values())
        print(f"현재 모집 중인 공고: {len(current_jobs)}건 발견")

    except Exception as e:
        print(f"목록 수집 중 오류: {e}")
        driver.quit()
        return

    # 2. 상세 페이지 크롤링
    scraped_urls = [job['URL'] for job in current_jobs]
    new_results = []

    for job in current_jobs:
        # 이미 존재하는 URL이면 마감 날짜만 초기화하고 건너뜀
        if job['URL'] in df_master['상세URL'].values:
            df_master.loc[df_master['상세URL'] == job['URL'], 'completed_date'] = ""
            continue
            
        print(f"신규 공고 수집: {job['공고명']}")
        driver.get(job['URL'])
        time.sleep(3)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        main_content = soup.find('main') or soup.find('body')
        lines = main_content.get_text(separator="\n", strip=True).split('\n')
        
        data = {
            "공고명": job['공고명'], "부문": "WATER", "상세URL": job['URL'],
            "채용정보": "", "주요업무": "", "지원자격": "", "우대사항": "", 
            "채용절차": "", "근무지": "", "first_seen": today, "completed_date": ""
        }
        
        section = None
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # 워터 사이트 헤더 키워드 대응
            if any(k in line for k in ["주요 업무", "주요업무", "무슨 일을 하나요"]): section = "주요업무"
            elif any(k in line for k in ["지원 자격", "자격 요건", "이런 분을 찾습니다"]): section = "지원자격"
            elif any(k in line for k in ["우대 사항", "더 좋습니다"]): section = "우대사항"
            elif any(k in line for k in ["채용 절차", "전형 절차"]): section = "채용절차"
            elif any(k in line for k in ["근무지", "근무 장소"]): section = "근무지"
            elif any(k in line for k in ["복지", "혜택", "지원하기", "목록"]): section = None
            elif section:
                data[section] += line + "\n"
        
        new_results.append(data)

    # 3. 마감 처리
    active_mask = df_master['completed_date'].isna() | (df_master['completed_date'] == "")
    closed_jobs_mask = active_mask & (~df_master['상세URL'].isin(scraped_urls))
    df_master.loc[closed_jobs_mask, 'completed_date'] = today

    # 4. 데이터 병합 및 저장
    if new_results:
        df_new = pd.DataFrame(new_results)
        df_final = pd.concat([df_master, df_new], ignore_index=True)
    else:
        df_final = df_master

    # 저장 시에는 가장 호환성이 좋은 utf-8-sig 권장 (엑셀에서도 잘 열림)
    df_final.to_csv(file_name, index=False, encoding="utf-8-sig")
    print(f"\n[작업 완료] 신규: {len(new_results)}건 / 마감: {closed_jobs_mask.sum()}건")
    
    driver.quit()

if __name__ == "__main__":
    scrape_water_recruitment()
