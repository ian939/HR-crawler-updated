import time
import pandas as pd
import os
import requests
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import google.generativeai as genai
from io import BytesIO
from PIL import Image

# Gemini API 설정
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

def clean_saramin_url(url):
    """URL에서 rec_idx만 남기고 나머지 추적 파라미터 제거"""
    u = urlparse(url)
    query = parse_qs(u.query)
    if 'rec_idx' in query:
        new_query = {'rec_idx': query['rec_idx']}
        return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(new_query, doseq=True), u.fragment))
    return url

def get_ai_summary(text, image_urls):
    """Gemini를 사용하여 텍스트와 이미지를 분석/요약"""
    if not text.strip() and not image_urls.strip():
        return "수집된 내용 없음"
    
    try:
        # 프롬프트: 요약 가이드라인 설정
        prompt = (
            "당신은 채용 전문 헤드헌터입니다. 다음 공고를 분석하여 구직자가 한눈에 보기 쉽게 요약해주세요.\n"
            "1. 주요업무, 2. 자격요건 순서로 요약해.\n"
            "이미지에 글자가 있다면 그 내용도 반드시 포함해줘. 한국어로 5줄 내외로 작성해.\n\n"
            f"텍스트 내용: {text[:2000]}"
        )
        contents = [prompt]

        # 이미지 처리 (보안 헤더 추가)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        valid_imgs = [url for url in image_urls.split("|") if "http" in url][:2] # 비용 및 성능 위해 2개로 제한
        
        for img_url in valid_imgs:
            try:
                res = requests.get(img_url, headers=headers, timeout=10)
                if res.status_code == 200:
                    img = Image.open(BytesIO(res.content))
                    contents.append(img)
            except: continue

        response = model.generate_content(contents)
        return response.text.strip()
    except Exception as e:
        return f"요약 생성 실패: {str(e)[:50]}"

def scrape_saramin():
    # 1. 기업명 리스트 및 파일 설정
    companies = ["대영채비", "이브이시스", "플러그링크", "볼트업", "차지비", "에버온"]
    csv_file = "saramin_results.csv"
    today = datetime.now().strftime('%Y-%m-%d')
    
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
    else:
        df_old = pd.DataFrame(columns=["기업명", "공고명", "요약내용", "이미지링크", "URL", "first-seen", "completed_date"])

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    scraped_urls = []

    try:
        for target_company in companies:
            print(f">>> '{target_company}' 검색 시작...")
            # 검색 정확도를 높이기 위해 '관계도순'이 아닌 '최근등록순' 또는 기본 검색 사용
            driver.get(f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={target_company}")
            time.sleep(5)

            items = driver.find_elements(By.CSS_SELECTOR, ".item_recruit")
            for item in items:
                try:
                    # [수정] 기업명 매칭 로직 강화 (완전 일치 또는 명확한 포함)
                    corp_name = item.find_element(By.CSS_SELECTOR, ".corp_name a").text.strip()
                    if target_company not in corp_name: 
                        continue
                    
                    raw_link = item.find_element(By.CSS_SELECTOR, ".job_tit a").get_attribute("href")
                    link = clean_saramin_url(raw_link) # 공고 고유 ID 포함한 URL 추출
                    scraped_urls.append(link)

                    # 중복 체크: 이미 요약까지 완료된 건이면 패스
                    if link in df_old['URL'].values:
                        existing = df_old[df_old['URL'] == link].iloc[0]
                        if pd.notna(existing['요약내용']) and "실패" not in str(existing['요약내용']):
                            continue

                    title = item.find_element(By.CSS_SELECTOR, ".job_tit a").text.strip()
                    
                    # 상세 페이지로 이동
                    driver.execute_script(f"window.open('{link}');")
                    driver.switch_to.window(driver.window_handles[1])
                    time.sleep(4)

                    content_text = ""
                    image_links = []
                    
                    # 상세 내용 수집 (iframe 및 일반 컨텐츠)
                    if len(driver.find_elements(By.ID, "iframe_content_0")) > 0:
                        driver.switch_to.frame("iframe_content_0")
                        body = driver.find_element(By.TAG_NAME, "body")
                        content_text = body.text.strip()
                        image_links = [img.get_attribute("src") for img in body.find_elements(By.TAG_NAME, "img") if img.get_attribute("src")]
                        driver.switch_to.default_content()
                    else:
                        try:
                            content_area = driver.find_element(By.CSS_SELECTOR, ".user_content, .job_detail_content")
                            content_text = content_area.text.strip()
                            image_links = [img.get_attribute("src") for img in content_area.find_elements(By.TAG_NAME, "img") if img.get_attribute("src")]
                        except: pass

                    img_str = "|".join(image_links)
                    
                    # Gemini 요약 수행
                    print(f"   - [신규] {title[:20]}")
                    summary = get_ai_summary(content_text, img_str)

                    # 데이터 합치기
                    if link in df_old['URL'].values:
                        df_old.loc[df_old['URL'] == link, '요약내용'] = summary
                        df_old.loc[df_old['URL'] == link, 'completed_date'] = None # 재활성화 대응
                    else:
                        new_row = pd.DataFrame([{
                            "기업명": target_company,
                            "공고명": title,
                            "요약내용": summary,
                            "이미지링크": img_str,
                            "URL": link,
                            "first-seen": today,
                            "completed_date": None
                        }])
                        df_old = pd.concat([df_old, new_row], ignore_index=True)
                    
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception as e:
                    print(f"오류: {e}")
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
    finally:
        driver.quit()

    # 마감 공고 처리
    df_old.loc[(~df_old['URL'].isin(scraped_urls)) & (df_old['completed_date'].isna()), 'completed_date'] = today
    
    # 저장 전 최종 중복 제거 및 저장
    df_old.drop_duplicates(subset=['URL'], keep='last').to_csv(csv_file, index=False, encoding="utf-8-sig")
    print(f"\n✅ 완료: 현재 총 {len(df_old)}개의 공고가 관리되고 있습니다.")

if __name__ == "__main__":
    scrape_saramin()
