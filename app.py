"""우리집 당번표 — GitHub + Streamlit Community Cloud 배포용

[배포]
1. GitHub 저장소에 app.py, requirements.txt 두 파일을 올립니다.
2. Streamlit Community Cloud에서 저장소를 연결하고 app.py를 실행합니다.
3. 아래 Supabase 설정 후 앱의 '공유'에서 배포 주소로 QR을 만듭니다.
   GitHub는 소스 보관용이며, 앱 실행 주소는 Streamlit 배포 주소입니다.

[실제 가족 공유 설정 — 무료 Supabase 프로젝트 필요]
Supabase SQL Editor에서 다음 SQL을 한 번 실행합니다.

create table public.family_duties (
 id uuid primary key,
 room text not null,
 day date not null,
 person text not null,
 role text not null,
 done boolean not null default false,
 completed_at timestamptz,
 created_at timestamptz not null default now()
);
create index family_duties_room_day on public.family_duties(room, day);
alter table public.family_duties enable row level security;
-- 공개 접근 정책은 만들지 않습니다. 서버의 service_role 키만 사용합니다.

Streamlit 앱 Settings > Secrets에 다음을 저장합니다.
SUPABASE_URL = "https://프로젝트주소.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "서버용 service_role 키"
FAMILY_CODE = "가족끼리만아는충분히긴암호"
APP_URL = "https://내앱.streamlit.app"

키/암호는 GitHub나 공개 파일에 넣지 마세요. service_role 키는 서버에서만
사용합니다. FAMILY_CODE는 다른 가정과 구분하는 서버 측 데이터 구역이자
접속 암호입니다. QR에는 암호가 포함되지 않습니다. 가족은 첫 접속 시 암호를
입력합니다. 가족 간 강력한 본인 인증 서비스는 아니므로 민감한 정보를
입력하지 마세요. 설정을 바꾸면 체험 데이터는 자동 이전되지 않습니다.

[체험 모드]
Supabase 설정이 전혀 없으면 각 브라우저 세션에서만 작동합니다.
새로고침/재시작 시 사라질 수 있고 다른 휴대폰과 공유되지 않습니다.

[범위]
당일 안내는 앱 안에서 제공합니다. 앱을 닫은 상태의 푸시 알림은 없습니다.
일정은 한국 날짜 기준이며, 주간 달력은 월~일입니다. 작은 화면/확대 글꼴에서는
접근성을 위해 스크롤을 허용합니다. 필수 콘텐츠를 잘라 숨기지 않습니다.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import io
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import qrcode
import requests
import streamlit as st

st.set_page_config(page_title="우리집 당번표", page_icon="🏡", layout="centered", initial_sidebar_state="collapsed")
KST = ZoneInfo("Asia/Seoul")
PEOPLE = ["엄마", "아빠", "나", "형제자매"]
ROLES = ["🍽️ 설거지", "♻️ 분리수거", "🧹 청소", "🧺 빨래", "🗑️ 쓰레기 버리기", "🌱 물 주기", "🛒 장보기", "✏️ 직접 입력"]
COLORS = ["#7C3AED", "#2563EB", "#0F766E", "#C2410C"]


def secret(key: str) -> str:
    try:
        return str(st.secrets.get(key, "")).strip()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return ""


URL = secret("SUPABASE_URL").rstrip("/")
KEY = secret("SUPABASE_SERVICE_ROLE_KEY")
CODE = secret("FAMILY_CODE")
SHARED = bool(URL and KEY and CODE)
PARTIAL = bool(URL or KEY or CODE) and not SHARED
ROOM = hashlib.sha256(CODE.encode()).hexdigest() if SHARED else "demo"

st.markdown("""<style>
#MainMenu, footer {visibility:hidden;}
header[data-testid="stHeader"] {background:transparent;height:1.5rem;}
.block-container {max-width:510px;padding:1.7rem .8rem .7rem;}
[data-testid="stAppViewContainer"] {background:#F7F7FC;}
h1 {font-size:1.5rem !important;padding:0 !important;margin-bottom:.12rem !important;}
[data-testid="stVerticalBlock"] {gap:.45rem;}
[data-testid="stCaptionContainer"] p {font-size:.75rem;}
.st-key-toolbar [data-testid="stHorizontalBlock"],
.st-key-weeknav [data-testid="stHorizontalBlock"] {flex-wrap:nowrap !important;gap:.3rem;}
.st-key-toolbar [data-testid="stColumn"],
.st-key-weeknav [data-testid="stColumn"] {min-width:0 !important;flex:1 1 0 !important;width:0 !important;}
.st-key-toolbar button {padding:.2rem .1rem;min-height:2.3rem;}
.st-key-calendar_days [data-testid="stHorizontalBlock"],
.st-key-calendar_nav [data-testid="stHorizontalBlock"] {flex-wrap:nowrap !important;gap:4px;}
.st-key-calendar_days [data-testid="stColumn"],
.st-key-calendar_nav [data-testid="stColumn"] {min-width:0 !important;flex:1 1 0 !important;width:0 !important;}
.st-key-calendar_days button {padding:5px 2px;min-height:68px;}
.st-key-calendar_days button p {font-size:11px;line-height:1.4;overflow-wrap:anywhere;}
.st-key-calendar_days button[kind="secondary"] {background:#FFFFFF !important;color:#1F2937 !important;border-color:#D0D5DD !important;}
.st-key-calendar_days button[kind="secondary"] p {color:#1F2937 !important;}
.week {display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px;margin:2px 0;}
.day {border:1px solid #E1E3ED;border-radius:12px;padding:7px 2px;min-height:91px;text-align:center;background:#FFFFFF;color:#1F2937 !important;overflow-wrap:anywhere;color-scheme:light;}
.day.sel {border:2px solid #7C3AED;background:#F2ECFF;padding:6px 1px;}
.day .dow {font-size:10px;color:#475467 !important;}.day .num {font-size:16px;font-weight:750;color:#1F2937 !important;}
.day .mini {font-size:10px;line-height:1.45;margin-top:3px;color:#1F2937 !important;}.day .dot {font-size:9px;color:#475467 !important;}
.day .num.today {color:#6D28D9 !important;}.notice {background:#EEEBFF;color:#4C2889;border-radius:10px;padding:8px 10px;font-size:12px;}
@media(max-width:380px){.block-container{padding-left:.5rem;padding-right:.5rem}.day{min-height:85px}.mini{font-size:9px}}
</style>""", unsafe_allow_html=True)

if PARTIAL:
    st.error("공유 설정이 일부만 입력됐어요. Secrets에 SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, FAMILY_CODE를 모두 입력해 주세요.")
    st.stop()

if SHARED and not st.session_state.get("authenticated", False):
    st.title("🏡 우리집 당번표")
    st.caption("같은 가족 암호로 접속하면 일정과 완료 상태가 공유돼요.")
    with st.form("login"):
        password = st.text_input("가족 암호", type="password")
        enter = st.form_submit_button("우리집 들어가기", use_container_width=True)
    if enter:
        if hmac.compare_digest(password.encode(), CODE.encode()):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("가족 암호를 확인해 주세요.")
    st.stop()


def api(method: str, params=None, payload=None):
    response = requests.request(
        method, URL + "/rest/v1/family_duties",
        headers={"apikey": KEY, "Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json", "Prefer": "return=representation"},
        params=params, json=payload, timeout=15,
    )
    response.raise_for_status()
    return response.json() if response.content else []


def load_tasks(start: date):
    end = start + timedelta(days=6)
    if SHARED:
        return api("GET", [("select", "*"), ("room", "eq." + ROOM),
                           ("day", "gte." + start.isoformat()),
                           ("day", "lte." + end.isoformat()), ("order", "created_at.asc")])
    return [r for r in st.session_state.setdefault("demo_tasks", [])
            if start.isoformat() <= r["day"] <= end.isoformat()]


def save_task(day: date, person: str, role: str):
    row = {"id": str(uuid.uuid4()), "room": ROOM, "day": day.isoformat(),
           "person": person, "role": role, "done": False, "completed_at": None}
    if SHARED:
        api("POST", payload=row)
    else:
        st.session_state.setdefault("demo_tasks", []).append(row)


def update_task(task_id: str, done: bool):
    patch = {"done": done, "completed_at": datetime.now(KST).isoformat() if done else None}
    if SHARED:
        api("PATCH", [("room", "eq." + ROOM), ("id", "eq." + task_id)], patch)
    else:
        for row in st.session_state.get("demo_tasks", []):
            if row["id"] == task_id:
                row.update(patch)


def delete_task(task_id: str):
    if SHARED:
        api("DELETE", [("room", "eq." + ROOM), ("id", "eq." + task_id)])
    else:
        st.session_state.demo_tasks = [r for r in st.session_state.get("demo_tasks", []) if r["id"] != task_id]


def fail():
    st.error("저장소 연결에 실패했어요. 인터넷, Supabase 테이블과 Secrets 설정을 확인한 뒤 다시 시도해 주세요. 변경은 완료되지 않았을 수 있어요.")


@st.dialog("➕ 당번 등록")
def add_dialog(selected: date):
    with st.form("add_form"):
        day = st.date_input("날짜", selected)
        person = st.selectbox("가족", PEOPLE + ["직접 입력"])
        custom_person = st.text_input("직접 입력한 가족 이름", max_chars=12)
        role = st.selectbox("역할", ROLES)
        custom_role = st.text_input("직접 입력한 역할", max_chars=30)
        repeat = st.checkbox("다음 3주에도 같은 요일로 등록")
        submit = st.form_submit_button("달력에 등록", use_container_width=True, type="primary")
    if submit:
        who = custom_person.strip() if person == "직접 입력" else person
        what = custom_role.strip() if role == "✏️ 직접 입력" else role
        if not who or not what:
            st.warning("직접 입력한 이름 또는 역할을 채워 주세요.")
            return
        try:
            for offset in ([0, 7, 14, 21] if repeat else [0]):
                save_task(day + timedelta(days=offset), who, what)
        except requests.RequestException:
            fail()
            return
        st.session_state.selected_day = day
        st.rerun()


@st.dialog("🔗 가족에게 공유")
def share_dialog():
    st.caption("배포한 앱 주소를 넣으면 QR이 만들어져요. 같은 주소와 가족 암호로 접속하세요.")
    address = st.text_input("Streamlit 앱 주소", value=secret("APP_URL"), placeholder="https://우리앱.streamlit.app")
    if address.startswith("https://") and " " not in address:
        image = qrcode.make(address)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        st.image(buffer.getvalue(), width=210)
        st.download_button("QR 이미지 저장", buffer.getvalue(), "우리집_당번표_QR.png", "image/png")
        st.link_button("앱 주소 열기", address)
    elif address:
        st.warning("https://로 시작하는 배포 주소를 입력해 주세요.")
    st.info("QR에는 접속 주소만 담겨요. 앱을 닫으면 알림은 오지 않아요.")


@st.dialog("🗑️ 당번 삭제")
def delete_dialog(task):
    st.write(f"{task['day']} · {task['person']} · {task['role']}")
    st.caption("이 당번 1건만 삭제하며, 되돌릴 수 없어요.")
    if st.button("이 당번 삭제", type="primary", use_container_width=True):
        try:
            delete_task(task["id"])
        except requests.RequestException:
            fail()
            return
        st.rerun()


TODAY = datetime.now(KST).date()
st.session_state.setdefault("selected_day", TODAY)
st.session_state.setdefault("viewer", "전체")


def change_week(delta):
    st.session_state.selected_day += timedelta(days=delta)


def go_today():
    st.session_state.selected_day = TODAY


@st.dialog("📅 우리집 주간 달력")
def calendar_dialog():
    selected = st.session_state.selected_day
    start = selected - timedelta(days=selected.weekday())
    days = [start + timedelta(days=i) for i in range(7)]
    try:
        tasks = load_tasks(start)
    except (requests.RequestException, ValueError):
        fail()
        return
    st.caption("날짜를 누르면 그날의 모든 당번을 볼 수 있어요. 숫자는 등록된 당번 수예요.")
    with st.container(key="calendar_nav"):
        prev, center, nxt = st.columns([1, 2, 1])
        prev.button("‹ 이전", key="cal_prev", on_click=change_week, args=(-7,), use_container_width=True)
        center.button(f"{start:%m.%d}–{days[-1]:%m.%d} · 오늘", key="cal_today", on_click=go_today, use_container_width=True)
        nxt.button("다음 ›", key="cal_next", on_click=change_week, args=(7,), use_container_width=True)
    with st.container(key="calendar_days"):
        columns = st.columns(7)
        for i, day in enumerate(days):
            count = sum(t["day"] == day.isoformat() for t in tasks)
            with columns[i]:
                label = f"{'월화수목금토일'[i]} {day.day}일 · {count}건"
                st.button(label, key=f"cal_day_{day.isoformat()}",
                          type="primary" if day == selected else "secondary",
                          on_click=select_calendar_day, args=(day,), use_container_width=True)
    st.markdown(f"### {selected:%m월 %d일} ({'월화수목금토일'[selected.weekday()]})")
    entries = [t for t in tasks if t["day"] == selected.isoformat()]
    if not entries:
        st.info("등록된 당번이 없어요.")
    else:
        completed = sum(bool(t["done"]) for t in entries)
        st.caption(f"전체 {len(entries)}개 · 완료 {completed}개 · 남음 {len(entries)-completed}개")
        # 모든 항목을 생략 없이 표시합니다. 많으면 팝업 안에서 스크롤합니다.
        for task in entries:
            status = "✅ 완료" if task["done"] else "⬜ 미완료"
            content = (f'<div style="background:#FFFFFF;color:#1F2937;border:1px solid #E1E3ED;'
                       f'border-radius:10px;padding:10px 12px;margin:5px 0;overflow-wrap:anywhere;">'
                       f'<strong>{html.escape(task["person"])}</strong> · {html.escape(task["role"])}'
                       f'<br><span style="font-size:12px;color:#475467;">{status}</span></div>')
            st.markdown(content, unsafe_allow_html=True)
    if st.button("이 날짜 선택하고 닫기", key="calendar_apply", type="primary", use_container_width=True):
        st.rerun()


def select_calendar_day(day):
    st.session_state.selected_day = day


@st.fragment(run_every="15s")
def main():
    selected = st.session_state.selected_day
    start = selected - timedelta(days=selected.weekday())
    days = [start + timedelta(days=i) for i in range(7)]
    try:
        tasks = load_tasks(start)
    except (requests.RequestException, ValueError):
        fail()
        return
    st.title("🏡 우리집 당번표")
    mode = "가족 공유 · 15초마다 갱신" if SHARED else "체험 모드 · 이 브라우저에서만 저장"
    st.caption(mode)
    with st.container(key="toolbar"):
        c1, c2, c3 = st.columns(3)
        if c1.button("＋ 등록", use_container_width=True):
            add_dialog(selected)
        if c2.button("🔗 공유", use_container_width=True):
            share_dialog()
        if c3.button("↻ 새로고침", use_container_width=True):
            st.rerun()
    with st.container(key="weeknav"):
        c1, c2, c3 = st.columns([1, 2, 1])
        c1.button("‹ 이전", on_click=change_week, args=(-7,), use_container_width=True)
        c2.button(f"{start:%m.%d}–{days[-1]:%m.%d} · 오늘", on_click=go_today, use_container_width=True)
        c3.button("다음 ›", on_click=change_week, args=(7,), use_container_width=True)
    if st.button("📅 달력 열기 · 날짜별 전체 당번", use_container_width=True):
        calendar_dialog()
    st.caption(f"선택한 날짜: {selected:%m월 %d일} ({'월화수목금토일'[selected.weekday()]}) · 날짜 변경은 달력에서")
    names = list(dict.fromkeys(PEOPLE + [t["person"] for t in tasks]))
    viewer = st.selectbox("가족 필터", ["전체"] + names, key="viewer", label_visibility="collapsed")
    relevant = [t for t in tasks if t["day"] == selected.isoformat() and (viewer == "전체" or t["person"] == viewer)]
    left_today = sum(not t["done"] for t in tasks if t["day"] == TODAY.isoformat() and (viewer == "전체" or t["person"] == viewer))
    text = f"오늘 남은 당번 {left_today}개 · 완료하면 아래에서 체크해 주세요." if TODAY in days else "선택한 주의 당번을 확인하고 완료 표시해 주세요."
    st.markdown('<div class="notice">' + text + '</div>', unsafe_allow_html=True)
    if relevant:
        mapping = {t["id"]: t for t in relevant}
        choice = st.selectbox("당번 선택", list(mapping),
                               format_func=lambda x: ("✅ " if mapping[x]["done"] else "⬜ ") + mapping[x]["person"] + " · " + mapping[x]["role"],
                               label_visibility="collapsed", key=f"task_{selected}_{viewer}")
        task = mapping[choice]
        # 버튼으로 명시적으로 값을 저장하여 자동 갱신이 미저장 체크 상태를 덮지 않습니다.
        if st.button("↩ 완료 취소" if task["done"] else "✓ 수행 완료 체크", type="primary", use_container_width=True):
            try:
                update_task(task["id"], not task["done"])
            except requests.RequestException:
                fail()
                return
            st.rerun(scope="fragment")
        stamp = task.get("completed_at")
        if task["done"] and stamp:
            try:
                when = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(KST)
                st.caption(f"✓ {task['person']} 담당 역할 완료 표시 · {when:%m/%d %H:%M} (한국 시간)")
            except ValueError:
                st.caption("✓ 완료가 공유됐어요.")
        else:
            st.caption("가족 누구나 완료를 표시할 수 있어요. 역할 담당자 본인 인증은 하지 않아요.")
        if st.button("선택한 당번 삭제", key="delete", use_container_width=True):
            delete_dialog(task)
    else:
        st.info("이 날짜의 당번이 없어요. 위의 ＋ 등록을 눌러 주세요.")
    if not SHARED:
        st.caption("실제 가족 공유: app.py 맨 위 안내대로 Supabase와 Secrets를 설정하세요.")


main()
