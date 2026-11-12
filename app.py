import json
import uuid
from datetime import date, timedelta

import streamlit as st

st.set_page_config(page_title="우리집 냉장고 도우미", page_icon="🥬", layout="wide")

# Keep the interactive backup controls in a fixed top-right rectangular panel.
st.markdown("""
<style>
.st-key-backup_panel {
    position: fixed;
    top: 64px;
    right: 20px;
    width: 300px;
    max-height: calc(100dvh - 84px);
    overflow-y: auto;
    background: var(--background-color, #ffffff);
    color: var(--text-color, #202624);
    border: 1px solid #d5ddd8;
    border-radius: 0;
    padding: 18px;
    box-shadow: 0 4px 16px rgba(25, 45, 34, 0.09);
    z-index: 100;
    box-sizing: border-box;
}
.st-key-backup_panel h3 { font-size: 1.2rem; padding-top: 0; }
.st-key-backup_panel button { border-radius: 0; }
.st-key-backup_panel [data-testid="stFileUploaderDropzone"] {
    border-radius: 0;
    padding: 10px;
}
[data-testid="stMainBlockContainer"] {
    max-width: none;
    padding-right: 350px;
}
@media (max-width: 760px) {
    .st-key-backup_panel {
        width: min(300px, calc(100vw - 24px));
        top: 60px;
        right: 12px;
        max-height: min(440px, calc(100dvh - 80px));
    }
    [data-testid="stMainBlockContainer"] {
        padding-right: 16px;
        padding-left: 16px;
        padding-top: 525px;
    }
}
</style>
""", unsafe_allow_html=True)


def initial():
    return {"foods": [], "shopping": [], "meals": {}}


def check_backup(data):
    if not isinstance(data, dict) or set(data) != {"foods", "shopping", "meals"}:
        raise ValueError("이 앱에서 받은 백업 파일을 선택해주세요.")
    if not isinstance(data["foods"], list) or not isinstance(data["shopping"], list) or not isinstance(data["meals"], dict):
        raise ValueError("기록 형식이 올바르지 않습니다.")
    ids = set()
    for group in ("foods", "shopping"):
        for item in data[group]:
            if not isinstance(item, dict):
                raise ValueError("잘못된 항목이 있습니다.")
            for key in ("id", "name", "qty"):
                if not isinstance(item.get(key), str) or not item[key].strip():
                    raise ValueError("이름과 수량을 확인해주세요.")
            if item["id"] in ids:
                raise ValueError("중복 항목 번호가 있습니다.")
            ids.add(item["id"])
            if group == "foods":
                date.fromisoformat(item["expiry"])
                if item.get("place") not in ("냉장", "냉동", "실온"):
                    raise ValueError("보관 장소가 올바르지 않습니다.")
            elif type(item.get("done")) is not bool:
                raise ValueError("구매 상태가 올바르지 않습니다.")
    for day, meals in data["meals"].items():
        date.fromisoformat(day)
        if not isinstance(meals, dict) or set(meals) != {"아침", "점심", "저녁"}:
            raise ValueError("식단 형식이 올바르지 않습니다.")
        if not all(isinstance(v, str) for v in meals.values()):
            raise ValueError("식단은 글자로 입력해주세요.")
    return data


if "fridge" not in st.session_state:
    st.session_state.fridge = initial()
if "backup_version" not in st.session_state:
    st.session_state.backup_version = 0
state = st.session_state.fridge
st.title("🥬 우리집 냉장고 도우미")
st.write("버리는 식재료는 줄이고, 오늘 먹을 것과 살 것을 한곳에서 확인하세요.")
today = st.date_input("기준 날짜", value=date.today(), help="서버 날짜가 다르면 실제 오늘 날짜로 바꿔주세요.")
with st.container(key="backup_panel"):
    st.subheader("💾 기록 보관")
    st.download_button("전체 기록 백업", json.dumps(state, ensure_ascii=False, indent=2), file_name="fridge_backup.json", mime="application/json", use_container_width=True)
    upload = st.file_uploader("백업 파일 선택", type="json")
    confirmed = st.checkbox("현재 기록을 백업 내용으로 교체합니다")
    if st.button("백업 불러오기", disabled=upload is None or not confirmed):
        try:
            if upload.size > 2_000_000:
                raise ValueError("2MB 이하 파일을 선택해주세요.")
            restored = check_backup(json.loads(upload.getvalue().decode("utf-8-sig")))
            st.session_state.fridge = restored
            st.session_state.backup_version += 1
            st.rerun()
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            st.error(f"불러오기 실패: {exc}")
    st.caption("사용 후 백업 파일을 보관해주세요.")

expired = [x for x in state["foods"] if date.fromisoformat(x["expiry"]) < today]
soon = [x for x in state["foods"] if 0 <= (date.fromisoformat(x["expiry"]) - today).days <= 3]
a, b, c = st.columns(3)
a.metric("소비기한 경과", len(expired))
b.metric("3일 이내 소비기한", len(soon))
c.metric("아직 안 산 물건", sum(not x["done"] for x in state["shopping"]))
fridge, plan, shop, help_tab = st.tabs(["🥬 냉장고", "🍚 주간 식단", "🛒 장보기", "📖 사용법"])

with fridge:
    with st.expander("식재료 추가", expanded=not state["foods"]):
        with st.form("food_add", clear_on_submit=True):
            name = st.text_input("식재료 이름", placeholder="예: 두부", max_chars=80)
            qty = st.text_input("수량 / 남은 양", placeholder="예: 1모, 반 봉지", max_chars=80)
            place = st.selectbox("보관 장소", ["냉장", "냉동", "실온"])
            expiry = st.date_input("제품에 표시된 소비기한", value=today + timedelta(days=3))
            if st.form_submit_button("냉장고에 등록", use_container_width=True):
                if name.strip() and qty.strip():
                    state["foods"].append({"id": uuid.uuid4().hex, "name": name.strip(), "qty": qty.strip(), "place": place, "expiry": expiry.isoformat()})
                    st.rerun()
                st.warning("이름과 수량을 모두 입력해주세요.")
    selected = st.selectbox("보관 장소별 보기", ["전체", "냉장", "냉동", "실온"])
    search = st.text_input("식재료 검색", placeholder="찾을 식재료 이름")
    items = sorted([x for x in state["foods"] if (selected == "전체" or x["place"] == selected) and search.strip().casefold() in x["name"].casefold()], key=lambda x: x["expiry"])
    if not items:
        st.caption("조건에 맞는 식재료가 없습니다. 식재료를 등록해보세요.")
    for item in items:
        remaining = (date.fromisoformat(item["expiry"]) - today).days
        label = f"🔴 {abs(remaining)}일 경과" if remaining < 0 else ("🟠 오늘까지" if remaining == 0 else f"{'🟠' if remaining <= 3 else '🟢'} {remaining}일 남음")
        with st.container(border=True):
            st.subheader(item["name"])
            st.write(f"{item['qty']} · {item['place']} · {item['expiry']}")
            st.write(label)
            left, right = st.columns(2)
            if left.button("다시 살 목록에 추가", key=f"buy_{item['id']}", use_container_width=True):
                duplicate = any(x["name"].casefold() == item["name"].casefold() and not x["done"] for x in state["shopping"])
                if duplicate:
                    st.warning("미구매 목록에 같은 이름이 있습니다.")
                else:
                    state["shopping"].append({"id": uuid.uuid4().hex, "name": item["name"], "qty": item["qty"], "done": False})
                    st.rerun()
            if right.button("다 먹음 / 목록에서 제거", key=f"remove_{item['id']}", use_container_width=True):
                state["foods"] = [x for x in state["foods"] if x["id"] != item["id"]]
                st.rerun()
    st.caption("색상은 입력한 날짜와 기준 날짜의 차이만 표시합니다. 실제 섭취 가능 여부를 판단하지 않습니다. 제품의 보관 조건과 개봉 후 안내를 확인하세요.")

with plan:
    start = st.date_input("주간 식단 시작일", value=today, key="week_start")
    st.caption("7일치 식단을 날짜별로 저장합니다. 저장한 뒤 다른 날짜로 이동해주세요.")
    days = [start + timedelta(days=i) for i in range(7)]
    with st.form(f"meal_plan_{start.isoformat()}_{st.session_state.backup_version}"):
        edits = {}
        for day in days:
            key = day.isoformat()
            st.markdown(f"**{day.month}월 {day.day}일 ({'월화수목금토일'[day.weekday()]})**")
            old = state["meals"].get(key, {})
            edits[key] = {meal: st.text_input(meal, value=old.get(meal, ""), max_chars=150, key=f"meal_{key}_{meal}_{start}_{st.session_state.backup_version}") for meal in ("아침", "점심", "저녁")}
        if st.form_submit_button("7일 식단 저장", use_container_width=True):
            state["meals"].update(edits)
            st.success("식단을 저장했습니다. 종료 전 전체 기록 백업도 다운로드해주세요.")
    lines = ["우리집 주간 식단"]
    for day in days:
        key = day.isoformat()
        meals = state["meals"].get(key, {})
        lines.append(key + " | " + " / ".join(f"{m}: {meals.get(m, '') or '미정'}" for m in ("아침", "점심", "저녁")))
    st.download_button("저장된 주간 식단 다운로드", "\n".join(lines), file_name="weekly_meals.txt", mime="text/plain")

with shop:
    with st.form("shopping_add", clear_on_submit=True):
        name = st.text_input("살 물건", max_chars=80)
        qty = st.text_input("수량", value="1개", max_chars=80)
        if st.form_submit_button("장보기 목록에 추가", use_container_width=True):
            if name.strip() and qty.strip():
                if any(x["name"].casefold() == name.strip().casefold() and not x["done"] for x in state["shopping"]):
                    st.warning("이미 미구매 목록에 있습니다. 수량을 바꾸려면 기존 항목을 삭제하고 다시 추가해주세요.")
                else:
                    state["shopping"].append({"id": uuid.uuid4().hex, "name": name.strip(), "qty": qty.strip(), "done": False})
                    st.rerun()
            else:
                st.warning("물건 이름과 수량을 입력해주세요.")
    if not state["shopping"]:
        st.caption("아직 살 물건이 없습니다.")
    for item in state["shopping"]:
        left, right = st.columns([5, 1])
        done = left.checkbox(f"{item['name']} · {item['qty']}", value=item["done"], key=f"done_{item['id']}_{st.session_state.backup_version}")
        if done != item["done"]:
            item["done"] = done
            st.rerun()
        if right.button("삭제", key=f"del_{item['id']}"):
            state["shopping"] = [x for x in state["shopping"] if x["id"] != item["id"]]
            st.rerun()
    pending = [f"□ {x['name']} — {x['qty']}" for x in state["shopping"] if not x["done"]]
    st.download_button("미구매 목록 다운로드", "\n".join(pending) or "살 물건이 없습니다.", file_name="shopping_list.txt", mime="text/plain")
    st.caption("구매 완료 체크만으로 냉장고에 자동 등록되지는 않습니다. 실제 제품의 소비기한을 확인해 냉장고 탭에 등록해주세요.")

with help_tab:
    st.markdown("""
### 가족에게 어떻게 도움이 되나요?
- 냉장고 속 재료를 날짜순으로 보고 먼저 확인할 재료를 찾습니다.
- 아침·점심·저녁 식단을 7일 단위로 작성합니다.
- 다 먹어가는 재료를 장보기 목록에 바로 추가합니다.
- 마트에서 구매한 항목은 체크하고, 남은 목록을 파일로 내려받습니다.

### GitHub → Streamlit 실행
1. 새 GitHub 저장소에 `app.py`, `requirements.txt`를 같은 위치에 올립니다.
2. Streamlit Community Cloud에서 GitHub 저장소를 연결합니다.
3. 메인 파일을 `app.py`로 지정해 배포합니다.

### 중요한 제한
- 앱 주소를 공유해도 가족 기기 사이에 기록이 자동 동기화되지는 않습니다.
- 자동 알림, 로그인, 영구 저장, 바코드 인식 기능은 없습니다.
- 한 가족 공용 기기에서 사용하거나 백업 JSON을 전달해 수동으로 기록을 옮길 수 있습니다.
- 백업을 불러오면 현재 기록이 교체되며 두 기록이 합쳐지지는 않습니다.
- 세션이 종료되면 기록이 사라질 수 있으므로 사용 후 전체 기록 백업을 다운로드하세요.
- 소비기한 안내는 입력한 날짜를 기준으로 하며 식품 안전을 보장하지 않습니다.
""")
