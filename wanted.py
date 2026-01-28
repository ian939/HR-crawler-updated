import time
import pandas as pd
import os
import re
import sys
import random
from datetime import datetime
from urllib.parse import urlparse, parse_qs

# Selenium 관련
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def clean_wanted_url(url):
    """URL에서 파라미터를 제거하고 순수 공고 링크만 반환합니다."""
    if not url: return ""
    return url.split('?')[0]

def extract_experience(text):
    """텍스트에서 경력 정보를 추출합니다 (예: 신입, 경력 3년, 경력 무관)."""
    if not text: return "정보없음"
    # 정규식 개선: '경력 3~5년', '경력 3년 이상' 등 다양한 패턴 대응
    match = re.search(r'(신입|경력\s*[\d\.\~\-\+]*\s*년.*?|경력\s*무관)', text)
    if match:
        return match.group(0).strip()
    return "정보없음"

def scrape_wanted():
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온", "일렉링크"]
    csv_file = "wanted_results.csv"
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 1. 컬럼 구조 설정
    columns = ["기업명", "공고명", "경력", "공고문 컬럼", "이미지 링크", "URL", "first-seen", "completed_date"]
    
    # 기존 데이터 로드
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        # 컬럼 보정
        for col in columns:
            if col not in df_old.columns:
                df_old[col] = ""
        df_old = df_old[columns]
    else:
        df_old = pd.DataFrame(columns=columns)

    # 2. 브라우저 설정
    options = Options()
    
    # [수정됨] 깃헙 액션(서버 환경)을 위한 헤드리스 모드 설정
    options.add_argument("--headless=new")  # 최신 헤드리스 모드 (탐지 회피 효과)
    options.add_argument("--disable-gpu")   # 리눅스 환경 안정성 확보

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 봇 탐지 회피를 위한 옵션 추가
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 15)
    scraped_urls = []

    try:
        for target_company in companies:
            print(f"\n>>> {target_company} 검색 시작...")
            search_url = f"https://www.wanted.co.kr/search?query={target_company}&tab=position"
            driver.get(search_url)
            time.sleep(random.uniform(2, 4)) # 랜덤 대기

            # 검색 결과에서 URL 수집
            card_links = []
            try:
                # 공고 카드 리스트 찾기
                anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/wd/']")
                for a in anchors:
                    link = a.get_attribute("href")
                    if "/wd/" in link:
                        card_links.append(clean_wanted_url(link))
                
                card_links = list(set(card_links))
                print(f"    (검색 결과 {len(card_links)}개 발견)")
                
            except Exception as e:
                print(f"    검색 결과 파싱 실패: {e}")
                continue

            # 각 공고 상세 크롤링
            for link in card_links:
                try:
                    # 이미 수집되었고 내용이 충분하면 스킵
                    if link in df_old['URL'].values:
                        idx = df_old[df_old['URL'] == link].index[0]
                        existing_content = str(df_old.at[idx, '공고문 컬럼'])
                        # 내용이 있고(Not NaN), 길이가 50자 이상이면 스킵
                        if pd.notna(existing_content) and existing_content != "nan" and len(existing_content) > 50:
                            scraped_urls.append(link) 
                            continue

                    driver.get(link)
                    
                    # [핵심] 페이지 로딩 대기: 제목(h1)이 뜰 때까지
                    try:
                        wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
                    except:
                        print(f"    - 페이지 로딩 실패/시간초과: {link}")
                        continue
                    
                    time.sleep(random.uniform(1.5, 3)) # 렌더링 안정화 대기

                    # 1. 공고명 추출
                    try:
                        title_el = driver.find_element(By.TAG_NAME, "h1")
                        title = title_el.text
                    except:
                        title = "제목없음"
                    
                    # URL 수집 목록에 추가
                    scraped_urls.append(link)

                    # 2. 경력 정보 추출 (제목 근처의 헤더 정보 긁어오기)
                    experience = "정보없음"
                    try:
                        # 전략: 제목(h1)의 부모 혹은 부모의 부모 태그 텍스트에서 '경력' 찾기
                        # 보통 h1 옆이나 위에 경력 정보가 있음
                        header_text = ""
                        current_el = title_el
                        for _ in range(3): # 상위 3단계까지 탐색
                            current_el = current_el.find_element(By.XPATH, "./..")
                            header_text += " " + current_el.text
                        
                        experience = extract_experience(header_text)
                        
                        # 만약 위 방법 실패 시, '경력' 단어가 포함된 특정 span 찾기
                        if experience == "정보없음":
                            exp_candidates = driver.find_elements(By.XPATH, "//*[contains(text(), '경력') or contains(text(), '신입')]")
                            for cand in exp_candidates:
                                # 너무 긴 텍스트는 본문일 가능성이 높으므로 제외 (50자 미만만 확인)
                                if len(cand.text) < 50 and len(cand.text) > 0:
                                    experience = extract_experience(cand.text)
                                    if experience != "정보없음": break
                    except:
                        pass

                    print(f"    - 수집 중: {title[:15]}... / 경력: {experience}")

                    # 3. 공고문 본문 및 이미지 추출 (가장 중요)
                    raw_text = ""
                    image_links = []
                    
                    try:
                        # [전략] '주요업무' 텍스트를 찾아서 그 부모를 타고 올라감
                        # 원티드 본문은 보통 '주요업무', '자격요건', '우대사항' 등이 순서대로 나열됨
                        # 이들을 모두 감싸는 컨테이너를 찾아야 함.
                        
                        # 1) 본문 로딩 대기 (주요업무 텍스트가 뜰 때까지 최대 5초)
                        try:
                            wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '주요') and contains(text(), '업무')]")))
                        except:
                            # 주요업무 텍스트가 없으면 자격요건으로 시도
                            pass

                        # 2) '주요업무' 혹은 '주요 업무' 텍스트를 가진 요소 찾기
                        # contains(text(), '주요업무')는 정확히 매칭되어야 하므로, 더 유연하게 검색
                        target_keywords = ["주요업무", "주요 업무", "자격요건", "자격 요건", "포지션 상세"]
                        anchor_element = None
                        
                        for kw in target_keywords:
                            try:
                                found_els = driver.find_elements(By.XPATH, f"//*[contains(text(), '{kw}')]")
                                # h2, h3, h6, strong 등 헤더급 요소 우선 선택
                                for el in found_els:
                                    if el.tag_name in ['h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'span']:
                                        anchor_element = el
                                        break
                                if anchor_element: break
                            except:
                                continue
                        
                        if anchor_element:
                            # 3) 부모를 타고 올라가며 컨테이너 찾기
                            # 컨테이너의 조건: 텍스트 길이가 충분히 길고(200자 이상), '자격요건'이나 '우대사항'도 포함하고 있어야 함
                            content_container = anchor_element
                            final_container = None
                            
                            for _ in range(6): # 최대 6단계 상위로 이동
                                try:
                                    content_container = content_container.find_element(By.XPATH, "./..")
                                    curr_text = content_container.text
                                    
                                    # 내용이 충분히 많으면 후보로 선정
                                    if len(curr_text) > 100:
                                        final_container = content_container
                                        # 자격요건/우대사항까지 포함되었다면 루프 중단 (충분한 영역 확보)
                                        if ("자격" in curr_text or "우대" in curr_text) and len(curr_text) > 300:
                                            break
                                except:
                                    break
                            
                            if final_container:
                                raw_text = final_container.text.strip()
                                # 이미지 추출
                                imgs = final_container.find_elements(By.TAG_NAME, "img")
                                image_links = [i.get_attribute("src") for i in imgs if i.get_attribute("src")]
                            else:
                                raw_text = "본문 컨테이너 찾기 실패"
                        
                        else:
                            # 키워드로 못 찾은 경우: 클래스명으로 시도 (백업)
                            try:
                                content_container = driver.find_element(By.CSS_SELECTOR, "div[class*='JobContent_description']")
                                raw_text = content_container.text.strip()
                            except:
                                raw_text = ""

                    except Exception as e:
                        print(f"      본문 추출 에러: {e}")

                    # 텍스트가 너무 짧으면 수집 실패로 간주
                    if len(raw_text) < 50:
                        print(f"      [주의] 본문 내용이 너무 짧음 ({len(raw_text)}자). 선택자 확인 필요.")

                    image_links_str = "|".join(image_links)

                    # 데이터 저장 (Upsert)
                    if link in df_old['URL'].values:
                        t_idx = df_old[df_old['URL'] == link].index[0]
                        df_old.at[t_idx, '경력'] = experience
                        df_old.at[t_idx, '공고문 컬럼'] = raw_text
                        df_old.at[t_idx, '이미지 링크'] = image_links_str
                        if not df_old.at[t_idx, 'first-seen']:
                             df_old.at[t_idx, 'first-seen'] = today
                        df_old.at[t_idx, 'completed_date'] = "" # 재오픈 시 마감일 제거
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

                except Exception as e:
                    print(f"      에러 발생 ({link}): {e}")

    finally:
        driver.quit()

    # 3. 마감 처리
    if len(scraped_urls) > 0:
        mask = (~df_old['URL'].isin(scraped_urls)) & (df_old['completed_date'].isna() | (df_old['completed_date'] == "")) & (df_old['기업명'].isin(companies))
        df_old.loc[mask, 'completed_date'] = today

    # 저장
    df_old = df_old[columns]
    df_old.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"\n[작업 완료] 총 {len(scraped_urls)}개의 공고를 확인했습니다.")

if __name__ == "__main__":
    scrape_wanted()
