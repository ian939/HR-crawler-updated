import pandas as pd
import requests
import os
import sys
from datetime import datetime

# =========================================================
# 1. 설정 정보 (GitHub Secrets에서 불러옴)
# =========================================================

# 환경변수에서 웹훅 URL을 가져옵니다.
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# 웹훅 URL이 없으면 에러 메시지를 출력하고 종료합니다.
if not SLACK_WEBHOOK_URL:
    print("❌ [에러] SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
    print("GitHub Settings > Secrets and variables > Actions에 'SLACK_WEBHOOK_URL'을 등록해주세요.")
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
        "title_col": "공고명"
    },
    {
        "name": "이브이시스(BEP)",
        "filename": "BEP_EV_Recruitment_Master.csv",
        "date_col": "first_seen",
        "url_col": "상세URL",
        "title_col": "공고명"
    }
]

# =========================================================
# 2. 함수 정의
# =========================================================

def load_sent_urls():
    """이미 알림을 보낸 URL 목록을 파일에서 불러옵니다."""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f)
    return set()

def save_sent_urls(urls):
    """알림을 보낸 URL을 파일에 추가합니다."""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        for url in urls:
            f.write(f"{url}\n")

def send_slack_message(source_name, jobs):
    """슬랙으로 알림 메시지를 전송합니다."""
    if not jobs:
        return

    # 메시지 내용 구성
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔔 [채용 알림] {source_name} 신규 공고",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"오늘 확인된 *{len(jobs)}건*의 새로운 공고가 있습니다."
            }
        }
    ]

    for job in jobs:
        title = job['title']
        link = job['url']
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"• *{title}*\n👉 <{link}|공고 보러가기>"
            }
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"📈 <{DASHBOARD_LINK}|전체 채용 대시보드 확인하기>"
            }
        ]
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
            # 날짜 비교를 위해 문자열로 변환
            df[target["date_col"]] = df[target["date_col"]].astype(str)
            
            # 오늘 날짜 & 아직 안 보낸 URL 필터링
            new_jobs_df = df[
                (df[target["date_col"]] == today_str) & 
                (~df[target["url_col"]].isin(sent_urls))
            ]

            if not new_jobs_df.empty:
                print(f"[{target['name']}] 알림 대상: {len(new_jobs_df)}건")
                
                jobs_to_send = []
                for _, row in new_jobs_df.iterrows():
                    url = str(row[target['url_col']])
                    title = str(row[target['title_col']])
                    jobs_to_send.append({"title": title, "url": url})
                    newly_sent_urls.append(url)
                
                send_slack_message(target["name"], jobs_to_send)
            else:
                print(f"[{target['name']}] 신규 공고 없음")

        except Exception as e:
            print(f"[{target['name']}] 오류: {e}")

    # 로그 파일 업데이트
    if newly_sent_urls:
        save_sent_urls(newly_sent_urls)
        print(f"전송 기록 {len(newly_sent_urls)}건 저장 완료")
    else:
        print("전송할 내역이 없습니다.")

if __name__ == "__main__":
    main()
