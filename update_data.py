import pandas as pd
from datetime import datetime

def update_web_page():
    # 1. 데이터 로드 (실제 환경에서는 크롤링 코드 삽입 가능)
    df = pd.read_csv('BEP_EV_Recruitment_Master.csv')
    
    # 2. 데이터 가공
    df['first_seen'] = pd.to_datetime(df['first_seen'])
    df = df.sort_values(by='first_seen', ascending=True)
    df['first_seen'] = df['first_seen'].dt.strftime('%Y-%m-%d')
    df = df.fillna('-')

    # 3. HTML 테이블 생성
    html_table = df[['공고명', '주요업무', 'first_seen', 'completed_date', '상세URL']].to_html(index=False, classes='table')
    
    # 4. index.html 파일 저장
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(f"<html><head><link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css'></head><body>")
        f.write(f"<div class='container mt-5'><h1>BEP 채용 공고 (업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M')})</h1>")
        f.write(html_table)
        f.write("</div></body></html>")

if __name__ == "__main__":
    update_web_page()
