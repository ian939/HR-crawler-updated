import time
import pandas as pd
import os
import re
import random
import sys
from datetime import datetime

# Selenium 관련
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def clean_remember_url(url):
    """URL에서 파라미터 제거 (순수 공고 ID만 남김)"""
    if not url: return ""
    return url.split('?')[0]

def extract_experience(text):
    """경력 정보 추출"""
    if not text: return "정보없음"
    match = re.search(r'(신입|경력\s*[\d\.\~\-\+]*\s*년.*?|경력\s*무관)', text)
    if match:
        return match.group(0).strip()
    return "정보없음"

def scrape_remember():
    # 1. 검색할 기업 리스트
    # companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온", "일렉링크"]
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온", "일렉링크"] # 테스트용

    csv_file = "remember_results.csv"
    today = datetime.now().strftime('%Y-%m-%d')
    
    columns = ["기업명", "공고명", "경력", "공고문 컬럼", "이미지 링크", "URL", "first-seen", "completed_date"]
    
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        for col in columns:
            if col not in df_old.columns:
                df_old[col] = ""
        df_old = df_old[columns]
    else:
        df_old = pd.DataFrame(columns=columns)

    # 2. 브라우저 옵션 설정
    options = Options()
    
    # [수정됨] 깃헙 액션(서버 환경)을 위한 헤드리스 모드 설정
    options.add_argument("--headless=new")  # 최신 헤드리스 모드 (탐지 회피 효과)
    options.add_argument("--disable-gpu")   # 리눅스 환경 안정성 확보
    
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 봇 탐지 회피
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 15)
    scraped_urls = []

    try:
        # [Step 1] 리멤버 채용 메인 접속
        base_url = "https://career.rememberapp.co.kr/job/postings"
        driver.get(base_url)
        time.sleep(3)

        for target_company in companies:
            print(f"\n>>> [리멤버] '{target_company}' 검색 시도...")
            
            try:
                # -------------------------------------------------------
                # 1. 검색창 찾기 및 입력
                # -------------------------------------------------------
                search_input = None
                try:
                    search_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='검색']")))
                except:
                    inputs = driver.find_elements(By.TAG_NAME, "input")
                    for inp in inputs:
                        if inp.get_attribute("type") in ["text", "search"]:
                            search_input = inp
                            break
                
                if not search_input:
                    print("    [!] 검색창 요소를 찾을 수 없습니다.")
                    continue

                # 강제 클릭 및 기존 내용 삭제
                driver.execute_script("arguments[0].click();", search_input)
                time.sleep(0.5)
                search_input.send_keys(Keys.CONTROL + "a")
                search_input.send_keys(Keys.BACK_SPACE)
                time.sleep(0.5)

                # 검색어 입력
                search_input.send_keys(target_company)
                time.sleep(0.5)
                search_input.send_keys(Keys.ENTER)
                
                # -------------------------------------------------------
                # 2. 검색 결과 찾기 (스크롤 로직 강화)
                # -------------------------------------------------------
                print("    - 검색어 입력 완료. 결과 로딩 및 스크롤 중...")
                time.sleep(3) 
                
                # [수정] 페이지 끝까지 스크롤하여 모든 공고 로딩 유도
                last_height = driver.execute_script("return document.body.scrollHeight")
                for _ in range(5): # 최대 5번 스크롤 시도
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1.5)
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        break
                    last_height = new_height
                
                # 혹시 모르니 맨 위로 한번 갔다가 조금씩 내리기 (렌더링 트리거)
                # driver.execute_script("window.scrollTo(0, 0);")
                # time.sleep(1)

                card_links = []
                try:
                    target_selector = "a[href*='/job/posting/']"
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, target_selector)))
                    anchors = driver.find_elements(By.CSS_SELECTOR, target_selector)
                    
                    print(f"    - 화면 내 공고 카드 후보: {len(anchors)}개")

                    for a in anchors:
                        try:
                            # 화면에 보이지 않아도 DOM에 있으면 가져오도록 is_displayed 체크 완화 가능
                            # 하지만 리멤버는 스크롤 안하면 렌더링 안될 수 있으므로 위 스크롤 로직이 중요
                            
                            link = a.get_attribute("href")
                            text_content = a.text 
                            
                            # [필터링]
                            if target_company in text_content:
                                clean_link = clean_remember_url(link)
                                if clean_link not in card_links:
                                    card_links.append(clean_link)
                        except:
                            continue
                    
                    print(f"    - '{target_company}' 최종 매칭 공고: {len(card_links)}개")

                except Exception as e:
                    print(f"    - 검색 결과 파싱 중 오류 (또는 결과 없음): {e}")
                    driver.get(base_url)
                    time.sleep(3)
                    continue

                if len(card_links) == 0:
                    print("    - 검색 결과 없음 (0건).")
                    driver.get(base_url)
                    time.sleep(3)
                    continue

                # -------------------------------------------------------
                # 3. 상세 페이지 크롤링
                # -------------------------------------------------------
                for link in card_links:
                    try:
                        # 이미 수집된 데이터 체크 (업데이트 필요 시 로직 변경 가능)
                        if link in df_old['URL'].values:
                            idx = df_old[df_old['URL'] == link].index[0]
                            existing_content = str(df_old.at[idx, '공고문 컬럼'])
                            # 내용이 충분히 있으면 스킵
                            if pd.notna(existing_content) and len(existing_content) > 50:
                                scraped_urls.append(link) 
                                print(f"    (Skip) 이미 수집됨: {link}")
                                continue

                        driver.get(link)
                        
                        try:
                            wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
                        except:
                            print(f"    - 상세 페이지 로딩 실패: {link}")
                            continue
                            
                        time.sleep(random.uniform(1.5, 2.5))

                        # (1) 공고명
                        try:
                            title = driver.find_element(By.TAG_NAME, "h1").text
                        except:
                            title = "제목없음"
                        
                        scraped_urls.append(link)

                        # (2) 경력 정보
                        experience = "정보없음"
                        try:
                            body_text = driver.find_element(By.TAG_NAME, "body").text
                            experience = extract_experience(body_text[:1000])
                        except:
                            pass

                        print(f"    - 수집 중: {title[:15]}... / 경력: {experience}")

                        # (3) 본문 및 이미지
                        raw_text = ""
                        image_links = []
                        
                        try:
                            target_keywords = ["주요업무", "주요 업무", "담당업무", "자격요건", "포지션 상세"]
                            anchor_element = None
                            for kw in target_keywords:
                                try:
                                    found_els = driver.find_elements(By.XPATH, f"//*[contains(text(), '{kw}')]")
                                    for el in found_els:
                                        if len(el.text) < 50:
                                            anchor_element = el
                                            break
                                    if anchor_element: break
                                except:
                                    continue
                            
                            if anchor_element:
                                content_container = anchor_element
                                final_container = None
                                for _ in range(8):
                                    try:
                                        content_container = content_container.find_element(By.XPATH, "./..")
                                        if len(content_container.text) > 100:
                                            final_container = content_container
                                            if ("자격" in content_container.text or "우대" in content_container.text) and len(content_container.text) > 200:
                                                break
                                    except:
                                        break
                                
                                if final_container:
                                    raw_text = final_container.text.strip()
                                    imgs = final_container.find_elements(By.TAG_NAME, "img")
                                    image_links = [i.get_attribute("src") for i in imgs if i.get_attribute("src")]
                            else:
                                try:
                                    content_container = driver.find_element(By.TAG_NAME, "article")
                                    raw_text = content_container.text.strip()
                                except:
                                    raw_text = ""

                        except Exception as e:
                            print(f"      본문 추출 실패: {e}")

                        image_links_str = "|".join(image_links)

                        # 저장 (Upsert)
                        if link in df_old['URL'].values:
                            t_idx = df_old[df_old['URL'] == link].index[0]
                            df_old.at[t_idx, '경력'] = experience
                            df_old.at[t_idx, '공고문 컬럼'] = raw_text
                            df_old.at[t_idx, '이미지 링크'] = image_links_str
                            if not df_old.at[t_idx, 'first-seen']:
                                df_old.at[t_idx, 'first-seen'] = today
                            df_old.at[t_idx, 'completed_date'] = ""
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
                        print(f"      상세 크롤링 에러 ({link}): {e}")

                # 메인으로 이동
                driver.get(base_url)
                time.sleep(2)

            except Exception as e:
                print(f"    [!] 프로세스 에러: {e}")
                driver.get(base_url)
                time.sleep(3)

    finally:
        driver.quit()

    # 마감 처리
    if len(scraped_urls) > 0:
        mask = (~df_old['URL'].isin(scraped_urls)) & (df_old['completed_date'].isna() | (df_old['completed_date'] == "")) & (df_old['기업명'].isin(companies))
        df_old.loc[mask, 'completed_date'] = today

    df_old = df_old[columns]
    df_old.to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"\n[리멤버 작업 완료] 총 {len(scraped_urls)}개의 공고 확인.")

if __name__ == "__main__":
    scrape_remember()
