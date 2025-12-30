import pandas as pd
import requests
import os
import sys
from datetime import datetime

# =========================================================
# 1. 설정 정보 (GitHub Secrets 사용)
# =========================================================

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

if not SLACK_WEBHOOK_URL:
    print("❌ [에러] SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
    sys.exit(1)

DASHBOARD_LINK = "https://ian939.github.io/HR-crawler-updated/"
LOG_FILE = "sent_logs.txt"

# 감시할 CSV 파일 리스트 및 설정
TARGET_FILES = [
    {
        "name": "사람인(Saramin)",
        "filename": "saramin_results.csv",
        "date_col": "first-seen",
        "url_col": "URL",
        "title_col": "공고명",
        "company_col": "기업명",        # CSV에 기업명 컬럼이 있는 경우
        "default_company": "알수없음"   # 컬럼이 비었을 때 대체 텍스트
    },
    {
        "name": "워터(BEP)",
        "filename": "BEP_EV_Recruitment_Master.csv",
        "date_col": "first_seen",
        "url_col": "상세URL",
        "title_col": "공고명",
        "company_col": None,            # CSV에 기업명 컬럼이 없는 경우
        "default_company": "워터(BEP)" # 고정된 기업명 사용
    }
]

# =========================================================
# 2. 함수 정의
# =========================================================

def load_sent_urls():
    """이미 알림을 보낸 URL 목록을 로드"""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f)
    return set()

def save_sent_urls(urls):
    """알림 보낸 URL 저장"""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        for url in urls:
            f.write(f"{url}\n")

def send_slack_message(source_name, jobs):
    """슬랙 알림 전송 (디자인 수정됨)"""
    if not jobs:
        return

    # 메시지 블록 구성
    blocks = [
        # 1. 헤더
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔔 [채용 알림] {source_name} 신규 공고",
                "emoji": True
            }
        },
        # 2. 대시보드 링크 (최상단 배치)
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"👉 <{DASHBOARD_LINK}|전체 채용 대시보드 확인하기>"
            }
        },
        # 3. 구분선
        {"type": "divider"},
        # 4. 요약 멘트
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"오늘 확인된 *{len(jobs)}건*의 새로운 공고가 있습니다."
            }
        }
    ]

    # 5. 각 공고 리스트 (기업명 포함)
    for job in jobs:
        company = job['company']
        title = job['title']
        link = job['url']
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                # [기업명] 공고제목 형태로 표시
                "text": f"• *[{company}] {title}*\n   📄 <{link}|공고 내용 자세히 보기>"
            }
        })

    payload = {"blocks": blocks}

    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        print(f"[{source_name}] 슬랙 전송 성공")
    except Exception as e:
        print(f"[{source_name}] 슬랙 전송 실패: {e}")

# =========================================================
# 3. 메인 로직
# =========================================================

def main():
    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"--- {today_str} 신규 공고 알림 체크 ---")
    
    sent_urls = load_sent_urls()
    newly_sent_urls = []

    for target in TARGET_FILES:
        file_path = target["filename"]
        
        if not os.path.exists(file_path):
            print(f"[Skip] 파일 없음: {file_path}")
            continue
            
        try:
            df = pd.read_csv(file_path)
            df[target["date_col"]] = df[target["date_col"]].astype(str)
            
            # 오늘 날짜 & 미발송 URL 필터링
            new_jobs_df = df[
                (df[target["date_col"]] == today_str) & 
                (~df[target["url_col"]].isin(sent_urls))
            ]

            if not new_jobs_df.empty:
                print(f"[{target['name']}] 알림 대상: {len(new_jobs_df)}건")
                
                jobs_to_send = []
                for _, row in new_jobs_df.iterrows():
                    # 기업명 추출 로직
                    if target["company_col"] and target["company_col"] in df.columns:
                        company_name = str(row[target["company_col"]])
                        # 값이 비어있으면 기본값 사용
                        if company_name == "nan" or not company_name.strip():
                            company_name = target["default_company"]
                    else:
                        company_name = target["default_company"]

                    url = str(row[target['url_col']])
                    title = str(row[target['title_col']])
                    
                    jobs_to_send.append({
                        "company": company_name,
                        "title": title, 
                        "url": url
                    })
                    newly_sent_urls.append(url)
                
                send_slack_message(target["name"], jobs_to_send)
            else:
                print(f"[{target['name']}] 신규 공고 없음")

        except Exception as e:
            print(f"[{target['name']}] 오류 발생: {e}")

    if newly_sent_urls:
        save_sent_urls(newly_sent_urls)
        print(f"전송 기록 {len(newly_sent_urls)}건 저장 완료")
    else:
        print("전송할 내역이 없습니다.")

if __name__ == "__main__":
    main()
