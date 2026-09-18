"""kobis_collect.py - KOBIS 일별 박스오피스를 정한 시작일부터 어제까지, 아직 없는 날짜만 받아 CSV에 이어 붙인다.

프롬프트 10-4(아직 없는 날짜를 이어받아 채우는 수집기)를 독자가 AI에게 넣었을 때 받을 법한 결과.
- 시작일은 설정(START_DATE)에서 한 번 정한 날짜로 고정하고, 종료일은 실행할 때마다 한국 시간 기준 어제로 계산한다.
- 처음 실행: 과거의 빈 날짜를 오래된 순으로 요청 횟수 상한(MAX_REQUESTS)까지 받는다. 재시도도 요청 횟수에 포함한다.
- 다음 실행: 아직 없는 날짜를 이어서 받는다. 다 채워진 뒤에는 어제 하루만 새로 받는다.
- 실행: KOBIS_KEY=... python kobis_collect.py
        MAX_REQUESTS(기본 2800), START_DATE(기본 20160918, YYYYMMDD)로 조정
"""
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.stdout.reconfigure(line_buffering=True)   # 깃허브 액션 로그에 진행 상황이 바로 보이게

KEY = os.environ.get("KOBIS_KEY", "").strip()
if not KEY:
    print("KOBIS_KEY가 없습니다. 실행 환경의 KOBIS_KEY에 영화진흥위원회 키를 넣어 주세요.")
    sys.exit(1)

URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
OUT = "data/kobis_daily_log.csv"
COLS = ["날짜", "순위", "영화코드", "영화명", "일관객", "누적관객", "스크린수", "상영횟수"]

# ── 설정 ──────────────────────────────────────────────────────
START_DATE = os.environ.get("START_DATE", "20160918")         # 수집 시작일(고정). 한 번 정하면 바꾸지 않는다.
MAX_REQUESTS = int(os.environ.get("MAX_REQUESTS", "2800"))   # 한 번 실행에 보낼 요청 횟수 상한(재시도 포함).
                                                             # 키의 이용 한도와 같은 키의 다른 사용량을 고려해 정한다.
RETRIES = 3          # 한 날짜당 최대 시도 횟수(연결 실패 때)
MAX_SECONDS = int(os.environ.get("MAX_SECONDS", "16200"))    # 이번 실행에 쓸 시간 상한(초). 기본 4시간 30분.
                                                             # 깃허브 액션 작업은 6시간이 지나면 강제 종료되므로,
                                                             # 그 전에 스스로 멈춰 받은 기록을 저장소에 반영할 시간을 남긴다.
RETRY_WAIT = 5       # 재시도 전 기다리는 초
PAUSE = 0.2          # 요청 사이 잠깐 쉬기
# ──────────────────────────────────────────────────────────────

KST = timezone(timedelta(hours=9))
today = datetime.now(KST).date()
yesterday = today - timedelta(days=1)
start = datetime.strptime(START_DATE, "%Y%m%d").date()

# 이미 저장한 날짜와 행
saved_rows = []
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
                saved_rows.append(row)
                have.add(row[0])

# 아직 없는 날짜를 오래된 순으로
missing = []
d = start
while d <= yesterday:
    s = d.strftime("%Y%m%d")
    if s not in have:
        missing.append(s)
    d += timedelta(days=1)

print(f"수집 기간 {start:%Y-%m-%d} ~ {yesterday:%Y-%m-%d} / 이미 저장한 날짜 {len(have)}일 / "
      f"아직 없는 날짜 {len(missing)}일 / 이번 실행 요청 횟수 상한 {MAX_REQUESTS}회")

def save_all():
    """받은 기록을 날짜·순위순으로 정렬해 저장한다. 도중에 멈춰도 여기까지는 남는다."""
    if not new_rows:
        return
    all_rows = saved_rows + new_rows
    all_rows.sort(key=lambda r: (r[0], int(r[1]) if str(r[1]).isdigit() else 99))
    os.makedirs("data", exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(all_rows)

requests_sent = 0
new_rows = []          # 이번 실행에서 정상 확인한 날짜의 행(한 날짜를 한 묶음으로)
added_days = []
failed_days = []
stopped_by_limit = False
stopped_by_api = False
consecutive_failures = 0

started = time.monotonic()
stopped_by_time = False
for s in missing:
    if requests_sent >= MAX_REQUESTS:
        stopped_by_limit = True
        break
    if time.monotonic() - started >= MAX_SECONDS:
        stopped_by_time = True
        break
    js = None
    for attempt in range(1, RETRIES + 1):
        if requests_sent >= MAX_REQUESTS:
            break
        requests_sent += 1
        try:
            res = requests.get(URL, params={"key": KEY, "targetDt": s}, timeout=10)
            js = res.json()
            break
        except Exception as e:                       # 주소(키 포함)는 출력하지 않는다
            print(f"{s} 요청 실패({attempt}/{RETRIES}): {type(e).__name__}")
            if attempt < RETRIES and requests_sent < MAX_REQUESTS:
                time.sleep(RETRY_WAIT)
    if js is None:
        failed_days.append(s)
        consecutive_failures += 1
        if consecutive_failures >= 3:
            print("연결 실패가 이어져 이번 실행을 멈춥니다. 남은 날짜는 다음 실행에서 이어받습니다.")
            break
        continue
    if "faultInfo" in js:
        # 한도 초과·키 오류 등은 여기서 멈춘다(남은 날짜는 다음 실행에서 이어받는다)
        print(f"{s} 응답 오류: {js['faultInfo'].get('message', '')}. 이번 실행을 멈춥니다.")
        failed_days.append(s)
        stopped_by_api = True
        break
    rows = js.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
    if not rows:
        failed_days.append(s)
        print(f"{s} 결과 없음(집계 전이거나 자료가 없는 날). 저장하지 않습니다.")
        consecutive_failures = 0
        continue
    for m in rows:
        new_rows.append([s, m.get("rank"), m.get("movieCd"), m.get("movieNm"), m.get("audiCnt"),
                         m.get("audiAcc"), m.get("scrnCnt"), m.get("showCnt")])
    added_days.append(s)
    consecutive_failures = 0
    if len(added_days) % 100 == 0:
        save_all()   # 중간 저장(도중에 멈춰도 여기까지는 남는다)
        print(f"진행: {len(added_days)}일 확인, 요청 {requests_sent}회, 여기까지 저장")
    time.sleep(PAUSE)

save_all()   # 마지막으로 한 번 더 저장

still_missing = len(missing) - len(added_days)
print(f"요청 횟수 {requests_sent}회 / 새로 저장한 날짜 {len(added_days)}일({len(new_rows)}행) / "
      f"실패한 날짜 {len(failed_days)}일{'(' + ', '.join(failed_days[:5]) + ('…' if len(failed_days) > 5 else '') + ')' if failed_days else ''} / "
      f"아직 없는 날짜 {still_missing}일")
if stopped_by_limit:
    print("요청 횟수 상한에 도달해 멈췄습니다. 남은 날짜는 다음 실행에서 이어받습니다.")
if stopped_by_time:
    print(f"수집 시간 상한({MAX_SECONDS}초)에 도달해 멈췄습니다. 남은 날짜는 다음 실행에서 이어받습니다.")
if not added_days and missing:
    sys.exit(1)   # 받을 날짜가 있었는데 하나도 저장하지 못했으면 실패로 알린다
