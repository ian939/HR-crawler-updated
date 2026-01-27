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
    # 기존 파일명 유지 (데이터 연속성)
    file_name = "BEP_EV_Recruitment_Master.csv"
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 1. 기존 데이터 로드
    if os.path.exists(file_name):
        df_master = pd.read_csv(file_name)
    else:
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
    
    # 신규 사이트 URL
    url = "https://watercharging.com/recruitments"
    print(f"접속 중: {url}")
    driver.get(url)
    
    current_jobs = []
    try:
        # 페이지 로딩 및 스크롤 (SPA 대응)
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        # 공고 링크 찾기 (더 유연한 방식: 'recruitments/'가 포함된 모든 a 태그)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/recruitments/')]"))
        )
        
        items = driver.find_elements(By.XPATH, "//a[contains(@href, '/recruitments/')]")
        print(f"찾은 링크 수: {len(items)}개")

        for item in items:
            link = item.get_attribute('href')
            # 'recruitments' 뒤에 숫자가 붙은 상세 페이지 링크만 필터링
            if link.split('/')[-1].isdigit():
                title_text = item.text.replace('\n', ' ').strip()
                if not title_text: continue
                current_jobs.append({"공고명": title_text, "URL": link})
        
        # 중복 제거
        current_jobs = list({v['URL']: v for v in current_jobs}.values())
        print(f"최종 수집 대상: {len(current_jobs)}개")

    except Exception as e:
        print(f"목록 수집 중 오류 발생: {e}")
        # 오류 발생 시 페이지 상태 확인용 코드
        print(f"현재 페이지 제목: {driver.title}")
        driver.quit()
        return

    # 2. 상세 정보 수집
    scraped_urls = [job['URL'] for job in current_jobs]
    new_results = []

    for job in current_jobs:
        # 이미 마스터에 있는 URL인지 확인
        if job['URL'] in df_master['상세URL'].values:
            df_master.loc[df_master['상세URL'] == job['URL'], 'completed_date'] = ""
            continue
            
        print(f"신규 공고 분석 중: {job['공고명']}")
        driver.get(job['URL'])
        time.sleep(3) # 상세 페이지 로딩 대기
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 텍스트 추출 (main 태그 위주로 탐색)
        main_content = soup.find('main') or soup.find('body')
        all_text = main_content.get_text(separator="\n", strip=True)
        lines = all_text.split('\n')
        
        data = {
            "공고명": job['공고명'], "부문": "WATER", "상세URL": job['URL'],
            "채용정보": "", "주요업무": "", "지원자격": "", "우대사항": "", 
            "채용절차": "", "근무지": "", "first_seen": today, "completed_date": ""
        }
        
        current_section = None
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # 워터 사이트 전용 키워드 매칭
            if any(k in line for k in ["주요 업무", "무슨 일을 하나요", "주요업무"]): 
                current_section = "주요업무"
            elif any(k in line for k in ["자격 요건", "지원 자격", "이런 분을 찾습니다"]): 
                current_section = "지원자격"
            elif any(k in line for k in ["우대 사항", "더 좋습니다"]): 
                current_section = "우대사항"
            elif any(k in line for k in ["채용 절차", "전형 절차"]): 
                current_section = "채용절차"
            elif "근무지" in line or "근무 장소" in line: 
                current_section = "근무지"
            elif any(k in line for k in ["복지", "혜택", "목록으로", "지원하기"]): 
                current_section = None
            elif current_section:
                data[current_section] += line + "\n"
        
        new_results.append(data)

    # 3. 마감 처리
    active_mask = df_master['completed_date'].isna() | (df_master['completed_date'] == "")
    closed_jobs_mask = active_mask & (~df_master['상세URL'].isin(scraped_urls))
    df_master.loc[closed_jobs_mask, 'completed_date'] = today

    # 4. 데이터 저장
    if new_results:
        df_new = pd.DataFrame(new_results)
        df_final = pd.concat([df_master, df_new], ignore_index=True)
    else:
        df_final = df_master

    # 최종 정리 및 CSV 저장
    for col in ["주요업무", "지원자격", "우대사항", "채용절차", "근무지"]:
        df_final[col] = df_final[col].fillna("").str.strip()

    df_final.to_csv(file_name, index=False, encoding="utf-8-sig")
    print(f"\n[업데이트 완료] 신규: {len(new_results)}건 / 마감 처리: {closed_jobs_mask.sum()}건")
    
    driver.quit()

if __name__ == "__main__":
    scrape_water_recruitment()
