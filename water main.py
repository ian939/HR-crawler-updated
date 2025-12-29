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

def scrape_bep_ev_recruitment():
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
    chrome_options.add_argument("--headless") # 정기 실행을 위해 헤드리스 모드 권장
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    url = "https://bep.co.kr/Career/recruitment?type=3"
    driver.get(url)
    
    current_jobs = []
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='recruitmentView']")))
        items = driver.find_elements(By.CSS_SELECTOR, "a[href*='recruitmentView']")

        for item in items:
            lines = [line.strip() for line in item.text.split('\n') if line.strip()]
            if not lines: continue
            
            status = lines[0]
            title_parts = [l for l in lines[1:] if "전기차충전사업부문" not in l]
            title = f"{status} - {' '.join(title_parts)}" if title_parts else " - ".join(lines)
            link = item.get_attribute('href')
            current_jobs.append({"공고명": title.strip(), "URL": link})
    except Exception as e:
        print(f"목록 수집 오류: {e}")
        driver.quit()
        return

    # 2. 상세 정보 수집 및 마스터 데이터 업데이트
    scraped_urls = [job['URL'] for job in current_jobs]
    new_results = []

    for job in current_jobs:
        # 이미 마스터에 있는 URL인지 확인
        is_existing = job['URL'] in df_master['상세URL'].values
        
        # 신규 공고일 때만 상세 페이지 접속 및 수집
        if not is_existing:
            print(f"신규 공고 발견: {job['공고명']}")
            driver.get(job['URL'])
            time.sleep(2.5)
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            all_text = soup.get_text(separator="\n", strip=True)
            lines = all_text.split('\n')
            
            data = {
                "공고명": job['공고명'], "부문": "전기차충전사업부문", "상세URL": job['URL'],
                "채용정보": "", "주요업무": "", "지원자격": "", "우대사항": "", 
                "채용절차": "", "근무지": "", "first_seen": today, "completed_date": ""
            }
            
            current_section = None
            for line in lines:
                line = line.strip()
                if not line: continue
                if any(k in line for k in ["채용 유형", "채용 직위"]): 
                    data["채용정보"] += line + " "
                    continue
                
                if "주요 업무" in line: current_section = "주요업무"
                elif "자격 요건" in line: current_section = "지원자격"
                elif "우대 사항" in line: current_section = "우대사항"
                elif "채용 절차" in line: current_section = "채용절차"
                elif "근무지" in line: current_section = "근무지"
                elif any(k in line for k in ["팀 소개", "지원 방법", "목록보기"]): current_section = None
                elif current_section:
                    if line not in job['공고명'] and "모집중" not in line:
                        data[current_section] += line + "\n"
            
            new_results.append(data)
        else:
            # 이미 있는 공고라면 마감 상태였다가 다시 올라온 경우를 위해 마감일 초기화
            df_master.loc[df_master['상세URL'] == job['URL'], 'completed_date'] = ""

    # 3. 마감된 공고 처리 (기존엔 있었으나 이번 크롤링 목록엔 없는 경우)
    # 현재 'completed_date'가 비어있는 항목들 중, 이번 크롤링 목록(scraped_urls)에 없는 항목 찾기
    active_mask = df_master['completed_date'].isna() | (df_master['completed_date'] == "")
    closed_jobs_mask = active_mask & (~df_master['상세URL'].isin(scraped_urls))
    df_master.loc[closed_jobs_mask, 'completed_date'] = today

    # 4. 신규 데이터 병합 및 저장
    if new_results:
        df_new = pd.DataFrame(new_results)
        df_final = pd.concat([df_master, df_new], ignore_index=True)
    else:
        df_final = df_master

    # 텍스트 정리
    for col in ["주요업무", "지원자격", "우대사항", "채용절차", "근무지"]:
        df_final[col] = df_final[col].fillna("").str.strip()

    df_final.to_csv(file_name, index=False, encoding="utf-8-sig")
    print(f"\n[업데이트 완료] 신규: {len(new_results)}건 / 마감 처리: {closed_jobs_mask.sum()}건")
    
    driver.quit()

if __name__ == "__main__":
    scrape_bep_ev_recruitment()