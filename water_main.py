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

def scrape_water_ev_recruitment():
    file_name = "Water_EV_Recruitment_Master.csv"
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
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    # 신규 URL 접속
    url = "https://watercharging.com/recruitments"
    driver.get(url)
    
    current_jobs = []
    try:
        # 공고 목록 로딩 대기 (링크 패턴 변경: /recruitments/ 숫자 형태)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/recruitments/']")))
        items = driver.find_elements(By.CSS_SELECTOR, "a[href*='/recruitments/']")

        for item in items:
            link = item.get_attribute('href')
            # 텍스트 추출 시 불필요한 공백 제거 및 정리
            raw_text = item.text.strip()
            if not raw_text: continue
            
            # 목록에서 제목 추출 (보통 첫 줄이 제목이거나 모집 상태 포함)
            lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
            title = " ".join(lines)
            
            current_jobs.append({"공고명": title, "URL": link})
            
        # 중복 제거 (목록에 동일 링크가 여러 개 있을 경우 대비)
        current_jobs = list({v['URL']: v for v in current_jobs}.values())
        
    except Exception as e:
        print(f"목록 수집 오류: {e}")
        driver.quit()
        return

    # 2. 상세 정보 수집 및 마스터 데이터 업데이트
    scraped_urls = [job['URL'] for job in current_jobs]
    new_results = []

    for job in current_jobs:
        is_existing = job['URL'] in df_master['상세URL'].values
        
        if not is_existing:
            print(f"신규 공고 발견: {job['공고명']}")
            driver.get(job['URL'])
            time.sleep(3) # 페이지 렌더링 대기
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # 본문 텍스트 추출
            content_area = soup.find('main') or soup.find('body')
            all_text = content_area.get_text(separator="\n", strip=True)
            lines = all_text.split('\n')
            
            # 상세 페이지 제목 재추출 (h1 태그 등 우선순위)
            page_title = soup.find('h1').get_text(strip=True) if soup.find('h1') else job['공고명']
            
            data = {
                "공고명": page_title, "부문": "전기차충전사업부문(WATER)", "상세URL": job['URL'],
                "채용정보": "", "주요업무": "", "지원자격": "", "우대사항": "", 
                "채용절차": "", "근무지": "", "first_seen": today, "completed_date": ""
            }
            
            current_section = None
            for line in lines:
                line = line.strip()
                if not line: continue
                
                # 섹션 판단 키워드 (사이트에 맞게 최적화)
                if any(k in line for k in ["주요 업무", "무슨 일을 하나요", "주요업무"]): current_section = "주요업무"
                elif any(k in line for k in ["자격 요건", "지원 자격", "이런 분을 찾습니다", "지원자격"]): current_section = "지원자격"
                elif any(k in line for k in ["우대 사항", "우대사항", "더 좋습니다"]): current_section = "우대사항"
                elif any(k in line for k in ["채용 절차", "채용절차", "전형 절차"]): current_section = "채용절차"
                elif any(k in line for k in ["근무지", "근무 장소"]): current_section = "근무지"
                elif any(k in line for k in ["복지", "혜택", "지원 방법", "목록으로"]): current_section = None
                elif current_section:
                    # 제목과 겹치는 내용 제외하고 수집
                    if line not in page_title:
                        data[current_section] += line + "\n"
            
            new_results.append(data)
        else:
            # 기존 공고가 목록에 있다면 마감일 초기화 (재오픈 대응)
            df_master.loc[df_master['상세URL'] == job['URL'], 'completed_date'] = ""

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

    # 텍스트 정리 및 저장
    cols_to_fix = ["주요업무", "지원자격", "우대사항", "채용절차", "근무지"]
    for col in cols_to_fix:
        df_final[col] = df_final[col].fillna("").str.strip()

    df_final.to_csv(file_name, index=False, encoding="utf-8-sig")
    print(f"\n[업데이트 완료] 신규: {len(new_results)}건 / 마감 처리: {closed_jobs_mask.sum()}건")
    
    driver.quit()

if __name__ == "__main__":
    scrape_water_ev_recruitment()
