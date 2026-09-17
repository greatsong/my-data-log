"""kobis_collect.py - KOBIS 일별 박스오피스에서 어제 하루(1~10위)를 받아 CSV에 이어 붙인다.

프롬프트 10-1(어제 하루를 받아 파일에 남기기)을 독자가 AI에게 넣었을 때 받을 법한 결과.
실행: KOBIS_KEY=... python kobis_collect.py
"""
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

KEY = os.environ.get("KOBIS_KEY", "").strip()
if not KEY:
    print("KOBIS_KEY가 없습니다. 실행 환경의 KOBIS_KEY에 영화진흥위원회 키를 넣어 주세요.")
    sys.exit(1)

URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
OUT = "data/kobis_daily_log.csv"
COLS = ["날짜", "순위", "영화코드", "영화명", "일관객", "누적관객", "스크린수", "상영횟수"]

KST = timezone(timedelta(hours=9))
target = (datetime.now(KST) - timedelta(days=1)).strftime("%Y%m%d")   # 한국 시간 기준 어제

# 이미 받은 날짜 확인
have = set()
if os.path.exists(OUT):
    with open(OUT, encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        header = next(r, None)
        if header and [h.strip() for h in header] != COLS:
            print(f"{OUT}의 열이 다릅니다: {header}")
            sys.exit(1)
        for row in r:
            if row:
                have.add(row[0])
if target in have:
    print(f"{target}은 이미 저장되어 있어 다시 저장하지 않습니다.")
    sys.exit(0)

try:
    res = requests.get(URL, params={"key": KEY, "targetDt": target}, timeout=15)
    js = res.json()
except Exception as e:
    print(f"요청 실패: {type(e).__name__}")
    sys.exit(1)
if "faultInfo" in js:
    print(f"응답 오류: {js['faultInfo'].get('message', '')}")
    sys.exit(1)
rows = js.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
if not rows:
    print(f"{target}의 집계가 아직 없습니다. 저장하지 않고 종료합니다.")
    sys.exit(1)

is_new = not os.path.exists(OUT)
os.makedirs("data", exist_ok=True)
with open(OUT, "a", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    if is_new:
        w.writerow(COLS)
    for m in rows:
        w.writerow([target, m.get("rank"), m.get("movieCd"), m.get("movieNm"), m.get("audiCnt"),
                    m.get("audiAcc"), m.get("scrnCnt"), m.get("showCnt")])
print(f"{target} 저장 완료: {len(rows)}행")
