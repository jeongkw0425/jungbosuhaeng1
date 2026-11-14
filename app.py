"""WATO — 별도 서비스 가입 없이 실행
app.py와 requirements.txt를 GitHub에 올리고 Streamlit Community Cloud에서 app.py 실행.
Python 내장 SQLite로 가족코드와 기록을 서버의 wato.sqlite3에 저장합니다.
앱에서 6자리 코드 발급 → 사용자 이름으로 입장 → 사용자 선택.
서버 재생성/재배포 시 로컬 데이터는 사라질 수 있습니다. 장기 보관 보장 없음.
같은 서버 인스턴스의 사용자끼리 공유합니다. 외부 데이터베이스/API 키 불필요.
별도 인증이 없습니다. 배포 링크를 아는 사람은 접근할 수 있습니다. 민감한 일정 정보는 넣지 마세요.
"""
import calendar
import copy
import hashlib
import hmac
import html
import json
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone

import sqlite3
import time as clock
import streamlit as st

st.set_page_config(page_title='WATO · We Are The One',page_icon='🍀',layout='centered')
KST=timezone(timedelta(hours=9))
TODAY=datetime.now(KST).date()
LAST=TODAY+timedelta(days=364)
COOLDOWN={'소목':2,'중목':4,'대목':8}
# title, suggested duration(hours), minimum duration(hours), note
EVENTS={
'소목':[
('벌곡 바베큐 나들이',6,1,'캠핑장 대여 2만원은 사용자 제보입니다. 실제 요금·당일 이용·장비 확인 필수.'),
('영화관에서 영화 보기',4,1,''),('윷놀이 용돈 따기',2,1,'실제 돈 대신 가족이 합의한 소액 상한 또는 간식 쿠폰으로 진행하세요.'),
('가족 외식',3,1,''),('양촌 곶감축제 체험',6,1,'개최 기간 확인 필수'),('봄꽃 축제 나들이',5,1,'개최 기간 확인 필수'),
('가족 볼링',3,1,''),('동네 카페와 산책',3,1,''),('전통시장 먹거리 탐방',4,1,''),('가족 보드게임',3,1,''),
('공원 피크닉',4,1,'기상 확인'),('가족 사진 찍기',3,1,''),('도자기 원데이 클래스',4,1,'예약 확인'),('미술관 나들이',4,1,'휴관일 확인')],
'중목':[
('배낚시 체험',10,1,'운항·기상·멀미·구명조끼 확인'),('겨울 빙어낚시',10,1,'공식 운영장·개최 기간·얼음 안전 확인'),
('가족 등산',8,1,'가족 체력에 맞는 낮은 코스'),('뮤지컬 관람',7,1,'공연 일정·예매 확인'),('공연 관람',7,1,'공연 일정·예매 확인'),
('공주 백제문화제',10,1,'공식 행사명·일정 확인'),('공주 폭죽축제 나들이',9,1,'사용자 제안 행사: 실제 개최 여부·공식 행사명 확인'),
('천안삼거리 축제 나들이',9,1,'사용자 제안 행사: 실제 개최 여부·공식 행사명 확인'),
('수목원 당일 여행',8,1,''),('가족 야구 직관',8,1,'경기·좌석 예약 확인'),('딸기 수확 체험',7,1,'계절·농장 운영 확인'),
('바다 유람선과 식사',10,1,'운항·기상 확인'),('가족 한복·고궁 나들이',8,1,''),('한우 맛집 당일 기차여행',12,1,'운행·예산 확인')],
'대목':[
('자연휴양림 1박 2일',32,24,'예약·이동시간 확인'),('해운대 여유 여행',32,24,'걷기 적은 동선·휴식 중심'),
('태안 1박 2일',32,24,'해변 산책과 숙소 휴식'),('대천 조개구이 1박 2일',32,24,'해산물 섭취 가능 여부 확인'),
('온천 휴식 여행',32,24,'온천 이용은 건강 상태에 맞게'),('일본 효도 여행',72,48,'여권·출입국 요건·여행자보험·예산 확인'),
('제주도 효도 관광',56,48,'렌터카/택시·짧은 이동·휴식 중심'),('경주 역사·호텔 휴식',32,24,''),
('부여 리조트 효도 여행',32,24,''),('남해 바다 전망 숙소 여행',32,24,''),('여수 야경·호텔 휴식',32,24,''),
('강릉 바다와 카페 여행',32,24,''),('단양 유람선·리조트 여행',32,24,'운항 확인'),('통영 케이블카·휴식 여행',32,24,'기상·운영 확인')]
}
REGIONS=['태안','대천·보령','공주','부여','천안','논산·양촌','대전','전주','경주','여수','강릉','남해','통영','제주','부산·해운대','단양']

LIVE=True
PARTIAL=False
ROOM='our-family'
DB_PATH=str(__import__('pathlib').Path(__file__).with_name('wato.sqlite3'))

def connection():
    db=sqlite3.connect(DB_PATH,timeout=20)
    db.execute('PRAGMA busy_timeout=20000')
    db.execute('CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS attempts (client TEXT PRIMARY KEY, failures INTEGER NOT NULL, until_time REAL NOT NULL)')
    db.commit()
    return db


def room_exists(room):
    with connection() as db:
        return db.execute('SELECT 1 FROM rooms WHERE id=?',(room,)).fetchone() is not None


def register_room(room,data):
    with connection() as db:
        cur=db.execute('INSERT OR IGNORE INTO rooms VALUES (?,0,?)',(room,json.dumps(data,ensure_ascii=False)))
        return cur.rowcount==1


def initial():
    return {'members':['엄마','아빠','나'],'availability':{},'blocked':{},'current':None,'history':[], 'next_draw':None,'dart':None}


def load():
    with connection() as db:
        row=db.execute('SELECT data,revision FROM rooms WHERE id=?',(ROOM,)).fetchone()
    if row is None:
        register_room(ROOM,initial())
        return load()
    data=json.loads(row[0])
    data.setdefault('blocked',{})
    return data,row[1]


def save(state,revision):
    with connection() as db:
        cur=db.execute('UPDATE rooms SET data=?,revision=revision+1 WHERE id=? AND revision=?',
            (json.dumps(state,ensure_ascii=False),ROOM,revision))
        if cur.rowcount!=1:raise ValueError('다른 가족이 먼저 수정했습니다. 새로고침 후 다시 진행하세요.')


def commit(state,revision,message,animation=None):
    try:
        save(state,revision)
        if animation:
            st.session_state.roulette_pending=animation
        st.session_state.flash=message
        st.rerun()
    except (sqlite3.Error,ValueError) as e:
        st.error(str(e) if isinstance(e,ValueError) else '저장 결과를 확인할 수 없습니다. 새로고침으로 실제 반영 여부를 확인한 뒤 다시 조작하세요.')


def add_months(day,months):
    m=day.month-1+months
    y=day.year+m//12;m=m%12+1
    return date(y,m,min(day.day,calendar.monthrange(y,m)[1]))


def draw_group():
    n=secrets.randbelow(100)
    return '소목' if n<80 else '중목' if n<95 else '대목'


def intervals(state,member):
    # Default availability is the whole day. Only explicit exclusions remove it.
    blocked=set(state.get('blocked',{}).get(member,[]))
    result=[]
    for i in range(365):
        day=TODAY+timedelta(days=i)
        if day.isoformat() not in blocked:
            a=datetime.combine(day,time())
            result.append((a,a+timedelta(days=1)))
    return merge_intervals(result)


def merge_intervals(items):
    merged=[]
    for a,b in sorted(items):
        if merged and a<=merged[-1][1]: merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else: merged.append((a,b))
    return merged


def intersect(a,b):
    i=j=0;out=[]
    while i<len(a) and j<len(b):
        lo=max(a[i][0],b[j][0]);hi=min(a[i][1],b[j][1])
        if lo<hi: out.append((lo,hi))
        if a[i][1]<b[j][1]: i+=1
        else: j+=1
    return out


def slots(state,hours):
    members=state['members']
    if not members:return []
    common=intervals(state,members[0])
    for m in members[1:]:common=intersect(common,intervals(state,m))
    now=datetime.now(KST).replace(tzinfo=None)
    duration=timedelta(hours=hours);result=[]
    for lo,hi in common:
        lo=max(lo,now)
        # Hourly candidate starts, including non-midnight multi-day trips.
        at=lo.replace(minute=0,second=0,microsecond=0)
        if at<lo:at+=timedelta(hours=1)
        while at+duration<=hi and len(result)<200:
            result.append((at,at+duration));at+=timedelta(hours=1)
    return result


def time_label(n):return f'{n//60:02d}:{n%60:02d}'

def roulette_animation(labels, weights, selected):
    # The committed draw is authoritative; the animation only reveals that result.
    import streamlit.components.v1 as components
    payload=json.dumps({'labels':labels,'weights':weights,'selected':selected},ensure_ascii=False).replace('<','\\u003c')
    template=r"""<!doctype html><html lang="ko"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
    body{margin:0;background:#fff;font-family:system-ui,sans-serif;color:#152D41;text-align:center;}
    .wrap{width:100%;max-width:340px;margin:0 auto;position:relative;padding-top:4px;box-sizing:border-box;}
    html,body{width:100%;overflow-x:hidden;}
    canvas{display:block;width:min(100%,300px);height:auto;margin:auto;}
    #result{font-size:19px;font-weight:750;min-height:52px;margin:10px 8px;overflow-wrap:anywhere;}
    button{border:0;background:#D92D4C;color:white;padding:10px 18px;border-radius:12px;font-size:15px;}
    
[data-testid="stSelectbox"] [data-baseweb="select"] > div {background:#FFFFFF !important;color:#252525 !important;border-color:#D8DDE3 !important;}
[data-testid="stSelectbox"] [data-baseweb="select"] span {color:#252525 !important;}
[data-baseweb="popover"] [role="listbox"], [data-baseweb="popover"] [role="option"] {background:#FFFFFF !important;color:#252525 !important;}
[data-testid="stDialog"] [role="dialog"] {max-height:85dvh !important;overflow-y:auto !important;}

</style></head><body><div class="wrap"><canvas id="wheel" width="660" height="660" aria-label="행사 추첨 룰렛"></canvas>
    <div id="result" role="status" aria-live="polite">두근두근… 룰렛이 돌아갑니다!</div></div>
    <script>const cfg=__PAYLOAD__;const canvas=document.getElementById('wheel'),ctx=canvas.getContext('2d');
    const total=cfg.weights.reduce((a,b)=>a+b,0), tau=Math.PI*2;
    const colors=['#D92D4C','#A83165','#B45B19','#4D667F','#6C4D99','#13776D'];
    let boundaries=[],cursor=0;
    cfg.weights.forEach(w=>{boundaries.push([cursor,cursor+w/total*tau]);cursor+=w/total*tau;});
    function paint(rotation){ctx.clearRect(0,0,660,660);ctx.save();ctx.translate(330,330);ctx.rotate(rotation);
      boundaries.forEach((b,i)=>{ctx.beginPath();ctx.moveTo(0,0);ctx.arc(0,0,290,b[0]-Math.PI/2,b[1]-Math.PI/2);ctx.closePath();ctx.fillStyle=colors[i%colors.length];ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=3;ctx.stroke();
      ctx.save();ctx.rotate((b[0]+b[1])/2-Math.PI/2);ctx.translate(185,0);ctx.rotate(Math.PI/2);ctx.fillStyle='#fff';ctx.textAlign='center';ctx.font='bold '+(cfg.labels.length>8?'21':'32')+'px sans-serif';
      const label=cfg.labels[i];ctx.fillText(label.length>10?label.slice(0,9)+'…':label,0,0);ctx.restore();});
      ctx.beginPath();ctx.arc(0,0,48,0,tau);ctx.fillStyle='#fff';ctx.fill();ctx.fillStyle='#D92D4C';ctx.font='bold 20px sans-serif';ctx.textAlign='center';ctx.fillText('WATO',0,7);ctx.restore();
      ctx.beginPath();ctx.moveTo(312,15);ctx.lineTo(348,15);ctx.lineTo(330,60);ctx.closePath();ctx.fillStyle='#152D41';ctx.fill();}
    function run(){document.getElementById('result').textContent='두근두근… 룰렛이 돌아갑니다!';
      const b=boundaries[cfg.selected],mid=(b[0]+b[1])/2,target=6*tau+(tau-mid),start=performance.now();
      const duration=matchMedia('(prefers-reduced-motion: reduce)').matches?100:4600;
      function frame(now){const t=Math.min(1,(now-start)/duration),ease=1-Math.pow(1-t,4);paint(target*ease);
      if(t<1)requestAnimationFrame(frame);else{document.getElementById('result').textContent='🎉 '+cfg.labels[cfg.selected]+' 당첨!';}}
      requestAnimationFrame(frame);}
    run();</script></body></html>"""
    components.html(template.replace('__PAYLOAD__',payload),height=415,scrolling=False)


@st.dialog('🎡 WATO 행운의 룰렛',width='small')
def roulette_dialog(category, title=None):
    st.caption('이번 추첨 결과를 룰렛으로 확인하세요.')
    if title is None:
        labels=['소목','중목','대목']
        roulette_animation(labels,[80,15,5],labels.index(category))
    else:
        labels=[item[0] for item in EVENTS[category]]
        roulette_animation(labels,[1]*len(labels),labels.index(title))
    if st.button('결과 확인하고 계속',type='primary',use_container_width=True):
        st.rerun()


st.markdown('''<style>
/* Keep light surfaces and dark text paired, even under a dark browser theme. */
:root {color-scheme:light;}
[data-testid="stApp"], [data-testid="stMain"], [data-testid="stAppViewContainer"] {background:#F4F7FA !important;color:#152D41 !important;}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color:#475569 !important;}
.stButton button, .stFormSubmitButton button, [data-testid="stDownloadButton"] button, [data-testid="stPopover"] button {
 background:#FFFFFF !important;color:#152D41 !important;border:1px solid #BCCBD8 !important;}
.stButton button p,.stFormSubmitButton button p,[data-testid="stDownloadButton"] button p,[data-testid="stPopover"] button p {color:#152D41 !important;}
.stButton button[kind="primary"],.stFormSubmitButton button[kind="primary"] {background:#D92D4C !important;color:#FFFFFF !important;border-color:#D92D4C !important;}
.stButton button[kind="primary"] p,.stFormSubmitButton button[kind="primary"] p {color:#FFFFFF !important;}
button:disabled {opacity:.55;}
[data-testid="stTextInput"] input,[data-testid="stNumberInput"] input,[data-testid="stTextArea"] textarea {
 background:#FFFFFF !important;color:#152D41 !important;-webkit-text-fill-color:#152D41 !important;}
[data-baseweb="select"] > div,[data-baseweb="input"], [data-baseweb="base-input"] {background:#FFFFFF !important;color:#152D41 !important;}
[data-baseweb="select"] span {color:#152D41 !important;}
[role="listbox"],[role="option"], [data-testid="stPopoverBody"], [data-testid="stForm"], [data-testid="stExpanderDetails"] {background:#FFFFFF !important;color:#152D41 !important;}
[role="option"] span,[role="option"] div {color:#152D41 !important;}
[data-baseweb="calendar"] {background:#FFFFFF !important;color:#152D41 !important;}
[data-baseweb="calendar"] button,[data-baseweb="calendar"] [role="gridcell"] {color:#152D41 !important;}
[data-baseweb="tab"] {background:transparent !important;color:#152D41 !important;}
[data-testid="stAlert"] {background:#EAF3FA !important;color:#152D41 !important;}
[data-testid="stAppViewContainer"]{background:#F4F7FA;color:#152D41;}
[data-testid="stHeader"]{background:#F4F7FA;}
.block-container{max-width:820px;padding-top:1.3rem;}
h1,h2,h3,p,label{color:#152D41;}
h1{font-size:1.9rem!important;} h3{font-size:1.15rem!important;}
.stButton button,.stFormSubmitButton button{border-radius:13px;min-height:44px;}
.stButton button[kind="primary"],.stFormSubmitButton button[kind="primary"]{background:#D92D4C;border-color:#D92D4C;color:white;}
.stButton button[kind="primary"] p,.stFormSubmitButton button[kind="primary"] p{color:white;}
[data-testid="stExpander"]{background:white;border-radius:14px;}
[data-baseweb="tab"]{color:#152D41;}
.st-key-monthgrid [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:3px;}
.st-key-monthgrid [data-testid="stColumn"]{min-width:0!important;width:0!important;flex:1 1 0!important;}
.st-key-monthgrid button{width:100%;min-height:54px;padding:3px 0;}
.st-key-monthgrid button p{font-size:12px;line-height:1.35;}
.card{background:white;border:1px solid #DEE8F0;border-radius:18px;padding:18px;margin:10px 0;color:#152D41;}
.weekdays{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));text-align:center;line-height:28px;color:#34495E;font-size:13px;}

/* WATO mobile: warm white surfaces, coral accent, explicit widget states. */
:root{color-scheme:light;--primary-color:#D92D4C;--text-color:#252525;--background-color:#FFFFFF;--secondary-background-color:#FFF4F5;}
[data-testid="stApp"],[data-testid="stMain"],[data-testid="stAppViewContainer"],[data-testid="stHeader"]{background:#FFFFFF !important;color:#252525 !important;}
.block-container{max-width:480px !important;padding:1rem .8rem 2rem !important;}
h1,h2,h3,p,label{color:#252525;}
h1{font-size:1.65rem !important;}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{color:#59616D !important;}
[data-testid="stAlert"],[data-testid="stAlertContainer"],
[data-testid="stAlert"] > div,[data-testid="stAlertContainer"] > div{
background:#FFF1E5 !important;color:#663C14 !important;border-radius:12px;}
[data-testid="stAlert"] p,[data-testid="stAlert"] span,[data-testid="stAlert"] svg,
[data-testid="stAlertContainer"] p,[data-testid="stAlertContainer"] span{color:#663C14 !important;}
.stButton button,.stButton button:hover,.stButton button:active,.stButton button:focus,
.stFormSubmitButton button,.stFormSubmitButton button:hover,.stFormSubmitButton button:active,
[data-testid="stDownloadButton"] button,[data-testid="stDownloadButton"] button:hover,
[data-testid="stPopover"] button,[data-testid="stPopover"] button:hover{
background:#FFFFFF !important;color:#252525 !important;border:1px solid #D7DCE1 !important;
box-shadow:none !important;transition:none !important;transform:none !important;border-radius:14px;min-height:48px;}
.stButton button p,.stButton button:hover p,.stFormSubmitButton button p,.stFormSubmitButton button:hover p{color:#252525 !important;}
.stButton button[kind="primary"],.stButton button[kind="primary"]:hover,.stButton button[kind="primary"]:active,
.stFormSubmitButton button[kind="primary"],.stFormSubmitButton button[kind="primary"]:hover{
background:#D92D4C !important;border-color:#D92D4C !important;color:#FFFFFF !important;}
.stButton button[kind="primary"] p,.stButton button[kind="primary"]:hover p,
.stFormSubmitButton button[kind="primary"] p{color:#FFFFFF !important;}
button:focus-visible{outline:2px solid #252525 !important;outline-offset:3px;}
[data-baseweb="tab"],[data-baseweb="tab"]:hover{background:transparent !important;color:#252525 !important;transition:none !important;}
[data-baseweb="tab-highlight"]{background:#D92D4C !important;}
[data-baseweb="tab-list"]{gap:12px;}
[data-baseweb="tab"]{padding-left:2px;padding-right:2px;font-size:13px;}
.card{background:#FFF4F5 !important;border-color:#F2DADF !important;border-radius:18px;color:#252525 !important;}
[data-testid="stDialog"] [role="dialog"]{background:#FFFFFF !important;color:#252525 !important;max-width:480px !important;width:calc(100vw - 24px) !important;}
[data-testid="stDialog"] [role="dialog"] p,[data-testid="stDialog"] [role="dialog"] label{color:#252525;}
@media(max-width:600px){
[data-testid="stTabs"] [data-baseweb="tab-list"]{gap:9px;}
[data-baseweb="tab"] p{font-size:12px !important;white-space:nowrap;}
h3{font-size:1.1rem !important;}}


[data-testid="stSelectbox"] [data-baseweb="select"] > div {background:#FFFFFF !important;color:#252525 !important;border-color:#D8DDE3 !important;}
[data-testid="stSelectbox"] [data-baseweb="select"] span {color:#252525 !important;}
[data-baseweb="popover"] [role="listbox"], [data-baseweb="popover"] [role="option"] {background:#FFFFFF !important;color:#252525 !important;}
[data-testid="stDialog"] [role="dialog"] {max-height:85dvh !important;overflow-y:auto !important;}

</style>''',unsafe_allow_html=True)
st.markdown("""<style>
.st-key-monthgrid [data-testid="stHorizontalBlock"]{flex-wrap:nowrap !important;gap:3px !important;}
.st-key-monthgrid [data-testid="stColumn"]{min-width:0 !important;width:0 !important;flex:1 1 0 !important;}
.st-key-monthgrid button,.st-key-monthgrid button:hover{padding:3px 0 !important;min-height:55px !important;}
.st-key-monthgrid button p{font-size:12px !important;white-space:pre-line !important;color:#252525 !important;}
.st-key-monthgrid button:disabled{opacity:.38 !important;}

[data-testid="stSelectbox"] [data-baseweb="select"] > div {background:#FFFFFF !important;color:#252525 !important;border-color:#D8DDE3 !important;}
[data-testid="stSelectbox"] [data-baseweb="select"] span {color:#252525 !important;}
[data-baseweb="popover"] [role="listbox"], [data-baseweb="popover"] [role="option"] {background:#FFFFFF !important;color:#252525 !important;}
[data-testid="stDialog"] [role="dialog"] {max-height:85dvh !important;overflow-y:auto !important;}


/* Five equal navigation cells spanning the entire phone viewport. */
.st-key-bottom_nav{left:0 !important;right:0 !important;bottom:0 !important;transform:none !important;width:100% !important;max-width:none !important;padding:8px 0 calc(8px + env(safe-area-inset-bottom)) !important;overflow:visible !important;}
.st-key-bottom_nav [data-testid="stRadio"],.st-key-bottom_nav [data-testid="stRadio"]>div{width:100% !important;max-width:none !important;}
.st-key-bottom_nav [role="radiogroup"]{display:grid !important;grid-template-columns:repeat(5,minmax(0,1fr)) !important;align-items:center !important;gap:0 !important;width:100% !important;margin:0 !important;}
.st-key-bottom_nav [role="radiogroup"] label{display:flex !important;align-items:center !important;justify-content:center !important;justify-self:stretch !important;width:100% !important;min-width:0 !important;min-height:50px !important;padding:0 !important;margin:0 !important;position:relative !important;box-sizing:border-box !important;}
.st-key-bottom_nav [role="radiogroup"] label>div:first-child{display:none !important;width:0 !important;height:0 !important;}
.st-key-bottom_nav input[type="radio"]{position:absolute !important;opacity:0 !important;width:0 !important;height:0 !important;}
.st-key-bottom_nav [role="radiogroup"] label [data-testid="stMarkdownContainer"]{width:100% !important;text-align:center !important;}
.st-key-bottom_nav [role="radiogroup"] label p{margin:0 !important;font-size:12px !important;line-height:1.7 !important;text-align:center !important;white-space:pre-line !important;}
.st-key-bottom_nav [role="radiogroup"] label:nth-child(3){justify-self:center !important;width:70px !important;height:70px !important;min-height:70px !important;border-radius:50% !important;background:#D92D4C !important;margin:-25px 0 0 !important;box-shadow:0 4px 15px #D92D4C44 !important;}
.st-key-bottom_nav [role="radiogroup"] label:nth-child(3) p{color:#FFFFFF !important;font-size:22px !important;line-height:1.1 !important;font-weight:800 !important;}
.block-container{padding-bottom:115px !important;}

</style>""",unsafe_allow_html=True)

@st.dialog('📅 날짜 확인 · 안 되는 날 표시')
def day_dialog(day):
    try: data,revision=load()
    except (sqlite3.Error,ValueError):st.error('기록을 불러오지 못했어요.');return
    st.write(f'**{day:%Y년 %m월 %d일}**')
    key=day.isoformat()
    for member in data['members']:
        unavailable=key in data.get('blocked',{}).get(member,[])
        st.write(('🔴 ' if unavailable else '🟢 ')+member+(' · 안 돼요' if unavailable else ' · 가능해요'))
    if not TODAY<=day<=LAST:return
    who=st.session_state.user
    unavailable=key in data.get('blocked',{}).get(who,[])
    if st.button('이 날 다시 가능으로 변경' if unavailable else '이 날은 안 돼요',type='primary',use_container_width=True):
        dates=set(data.setdefault('blocked',{}).get(who,[]))
        if unavailable:dates.discard(key)
        else:dates.add(key)
        data['blocked'][who]=sorted(dates)
        if data['current']:data['current']['votes']={}
        commit(data,revision,'날짜를 변경했어요.')
    st.caption('기본은 모두 가능이에요. 내 안 되는 날짜만 제외하세요.')

st.markdown("""<style>
[data-testid="stDialog"] [data-baseweb="modal"]{background-color:rgba(12,18,28,.65) !important;}
[data-testid="stDialog"] [role="dialog"]{width:calc(100vw - 28px) !important;max-width:390px !important;min-width:0 !important;max-height:92dvh !important;margin:auto !important;overflow-x:hidden !important;overflow-y:auto !important;border-radius:22px !important;}
[data-testid="stDialog"] [role="dialog"] iframe{width:100% !important;max-width:100% !important;display:block;}
[data-testid="stDialog"] [role="dialog"] h2{font-size:1.15rem !important;}

[data-testid="stSelectbox"] [data-baseweb="select"] > div {background:#FFFFFF !important;color:#252525 !important;border-color:#D8DDE3 !important;}
[data-testid="stSelectbox"] [data-baseweb="select"] span {color:#252525 !important;}
[data-baseweb="popover"] [role="listbox"], [data-baseweb="popover"] [role="option"] {background:#FFFFFF !important;color:#252525 !important;}
[data-testid="stDialog"] [role="dialog"] {max-height:85dvh !important;overflow-y:auto !important;}

</style>""",unsafe_allow_html=True)
st.markdown("""<style>
.block-container{padding-top:max(1rem,env(safe-area-inset-top)) !important;padding-bottom:.3rem !important;}
[data-testid="stHeader"]{display:none !important;}
[data-testid="stMain"]{padding-top:0 !important;}
[data-testid="stVerticalBlock"]{gap:.3rem;}
h1{font-size:1.4rem !important;padding:.2rem 0 !important;margin:0 !important;}
[data-testid="stTabs"] [role="tabpanel"]{height:calc(100dvh - 205px);overflow-y:auto;overflow-x:hidden;padding:4px 2px 12px;box-sizing:border-box;}
.st-key-monthgrid button,.st-key-monthgrid button:hover{min-height:38px !important;}
.st-key-monthgrid button p{font-size:11px !important;line-height:1.15 !important;}
.weekdays{line-height:20px !important;padding:0 !important;}
@media(max-height:700px){.st-key-monthgrid button,.st-key-monthgrid button:hover{min-height:32px !important;}}

[data-testid="stSelectbox"] [data-baseweb="select"] > div {background:#FFFFFF !important;color:#252525 !important;border-color:#D8DDE3 !important;}
[data-testid="stSelectbox"] [data-baseweb="select"] span {color:#252525 !important;}
[data-baseweb="popover"] [role="listbox"], [data-baseweb="popover"] [role="option"] {background:#FFFFFF !important;color:#252525 !important;}
[data-testid="stDialog"] [role="dialog"] {max-height:85dvh !important;overflow-y:auto !important;}

</style>""",unsafe_allow_html=True)

@st.dialog('행사를 진행하기 어려워요')
def cancel_event_dialog(state,rev):
    current=state['current']
    st.caption('행사 수행은 안전보다 우선하지 않습니다. 중단해도 같은 휴식 기간이 적용되며 기록이 남습니다.')
    reason=st.text_input('불가피한 중단 사유',max_chars=500)
    agreed_cancel=st.checkbox('가족 모두와 중단을 합의했습니다.')
    if st.button('사유를 기록하고 중단',disabled=not agreed_cancel):
        if not reason.strip():st.warning('사유를 적어 주세요.')
        else:
            item=copy.deepcopy(current);item.update(completed=TODAY.isoformat(),review=reason,outcome='중단')
            state['history'].append(item);state['next_draw']=add_months(TODAY,COOLDOWN[current['category']]).isoformat();state['current']=None
            commit(state,rev,'중단 사유와 휴식 기간을 기록했습니다.')

@st.dialog('모두 초기화')
def reset_all_dialog(revision):
    st.warning('모든 가족의 일정, 추첨 결과, 행사 기록, 쿨타임과 이름 설정이 삭제됩니다. 되돌릴 수 없어요.')
    confirmation=st.checkbox('가족 전체 데이터가 삭제되는 것을 확인했습니다.')
    if st.button('모두 삭제하고 처음부터 시작',type='primary',disabled=not confirmation,use_container_width=True):
        try:
            save(initial(),revision)
        except (sqlite3.Error,ValueError):
            st.error('초기화하지 못했습니다. 새로고침 후 다시 시도해 주세요.')
            return
        for key in list(st.session_state):
            del st.session_state[key]
        st.session_state.flash='모두 초기화했어요.'
        st.rerun()

def drag_calendar(y,m,selected):
    import tempfile
    from pathlib import Path
    import streamlit.components.v1 as components
    folder=Path(tempfile.gettempdir())/'wato_drag_calendar'
    folder.mkdir(exist_ok=True)
    html=r"""<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;font:14px sans-serif;color:#252525;background:white}#grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;touch-action:none;user-select:none}.day{border:1px solid #ddd;border-radius:9px;min-height:36px;display:flex;align-items:center;justify-content:center}.sel{background:#D92D4C;color:white}.disabled{opacity:.3}.head{text-align:center;padding:5px}</style><div id="grid"></div>
<script>
const send=(type,data={})=>parent.postMessage({isStreamlitMessage:true,type,...data},'*');
let picked=new Set(),drag=false,mode=true,last='',args={};
function paint(){document.querySelectorAll('[data-date]').forEach(e=>e.classList.toggle('sel',picked.has(e.dataset.date)))}
function mark(e){if(!e||!e.dataset.date||e.classList.contains('disabled')||last===e.dataset.date)return;last=e.dataset.date;if(mode)picked.add(last);else picked.delete(last);paint()}
window.addEventListener('message',e=>{if(e.data.type!=='streamlit:render')return;args=e.data.args;picked=new Set(args.selected);let g=document.getElementById('grid');g.innerHTML='';for(let v of '月火水木金土日'){let x=document.createElement('div');x.className='head';x.textContent=v;g.appendChild(x)};Array.from(g.children).forEach((x,i)=>x.textContent=['월','화','수','목','금','토','일'][i]);for(let item of args.cells){let x=document.createElement('div');if(item.date){x.className='day'+(item.disabled?' disabled':'');x.dataset.date=item.date;x.textContent=item.day}else x.className='blank';g.appendChild(x)}paint();send('streamlit:setFrameHeight',{height:g.offsetHeight+8})});
let g=document.getElementById('grid');
g.addEventListener('pointerdown',e=>{let el=e.target.closest('[data-date]');if(!el||el.classList.contains('disabled'))return;e.preventDefault();drag=true;last='';mode=!picked.has(el.dataset.date);g.setPointerCapture(e.pointerId);mark(el)});
g.addEventListener('pointermove',e=>{if(drag){e.preventDefault();mark(document.elementFromPoint(e.clientX,e.clientY))}});
function finish(){if(!drag)return;drag=false;send('streamlit:setComponentValue',{value:[...picked].sort()})}
g.addEventListener('pointerup',finish);g.addEventListener('pointercancel',finish);
send('streamlit:componentReady',{apiVersion:1});send('streamlit:setFrameHeight',{height:300});
</script>"""
    (folder/'index.html').write_text(html,encoding='utf-8')
    component=components.declare_component('wato_drag_dates',path=str(folder))
    cells=[{'date':d.isoformat(),'day':d.day,'disabled':not TODAY<=d<=LAST} if d.month==m else {} for w in calendar.Calendar(0).monthdatescalendar(y,m) for d in w]
    return component(cells=cells,selected=selected,key=f'drag_{user}_{y}_{m}',default=None)

def memory_pdf(records,members):
    import io,base64
    from xml.sax.saxutils import escape
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Image as PDFImage,PageBreak,KeepTogether
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))
    font='HYSMyeongJo-Medium'
    title=ParagraphStyle('title',fontName=font,fontSize=25,leading=35,textColor=HexColor('#D92D4C'),spaceAfter=18,wordWrap='CJK')
    body=ParagraphStyle('body',fontName=font,fontSize=11,leading=19,wordWrap='CJK',spaceAfter=12)
    small=ParagraphStyle('small',parent=body,fontSize=9,textColor=HexColor('#777777'))
    out=io.BytesIO();doc=SimpleDocTemplate(out,rightMargin=45,leftMargin=45,topMargin=48,bottomMargin=45)
    story=[]
    for i,h in enumerate(records):
        if i:story.append(PageBreak())
        story.extend([Paragraph('WATO · FAMILY MEMORIES',small),Paragraph(escape(h['title']),title),Paragraph(escape(h.get('completed',''))+' · '+escape(h.get('category','')),body),Paragraph('함께한 가족 · '+escape(', '.join(members)),small)])
        if h.get('scheduled'):story.append(Paragraph('예정 일정 · '+escape(' ~ '.join(h['scheduled'])),small))
        story.append(Paragraph(escape(h.get('review') or '함께한 하루를 추억으로 남깁니다.').replace('\n','<br/>'),body))
        if h.get('image'):
            image=PDFImage(io.BytesIO(base64.b64decode(h['image'])))
            ratio=min(1,doc.width/image.imageWidth,390/image.imageHeight)
            image.drawWidth=image.imageWidth*ratio;image.drawHeight=image.imageHeight*ratio
            story.extend([Spacer(1,12),image])
    def footer(canvas,doc):
        canvas.setStrokeColor(HexColor('#F1DCE2'));canvas.line(45,35,550,35)
        canvas.setFont(font,9);canvas.setFillColor(HexColor('#777777'));canvas.drawString(45,22,'WE ARE THE ONE');canvas.drawRightString(550,22,str(doc.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()

@st.dialog('행사 완료 기록')
def finish_dialog(state,rev,valid,agreed):
    import io,base64
    from PIL import Image,ImageOps
    current=state['current']
    with st.form('finish'):
        finished=st.date_input('실제로 마친 날짜',value=TODAY)
        note=st.text_area('후기 (선택)',max_chars=1000,height=80)
        upload=st.file_uploader('행사 사진 (선택 · 10MB 이하)',type=['jpg','jpeg','png','webp'])
        confirm=st.checkbox('가족 모두 실제 진행을 확인했습니다.')
        if st.form_submit_button('완료하고 추억 저장'):
            if not confirm:st.warning('실제 진행 여부를 확인해 주세요.');return
            encoded=None
            if upload is not None:
                if upload.size>10*1024*1024:st.error('오류: 사진 크기가 10MB를 넘습니다. 더 작은 사진을 선택해 주세요.');return
                try:
                    image=ImageOps.exif_transpose(Image.open(upload));image.thumbnail((1600,1600));out=io.BytesIO();image.convert('RGB').save(out,format='JPEG',quality=85);encoded=base64.b64encode(out.getvalue()).decode()
                except Exception:st.error('오류: 사진을 읽지 못했어요. JPG·PNG·WEBP 사진으로 다시 선택해 주세요.');return
            item=copy.deepcopy(current);item.update(completed=finished.isoformat(),review=note,outcome='완료',image=encoded)
            state['history'].append(item);state['next_draw']=add_months(finished,COOLDOWN[current['category']]).isoformat();state['current']=None
            commit(state,rev,'추억을 저장했어요.')

st.markdown("""<style>
.block-container{padding-top:1rem !important;padding-bottom:1rem !important;}
[data-testid="stVerticalBlock"]{gap:.65rem !important;}
h1,h2,h3{line-height:1.4 !important;}
p,label{line-height:1.5 !important;}
.st-key-monthgrid button,.st-key-monthgrid button:hover{min-height:44px !important;padding:4px 0 !important;}
.st-key-monthgrid button p{font-size:12px !important;line-height:1.35 !important;}
</style>""",unsafe_allow_html=True)
st.markdown("""<style>
[data-testid="stDialog"] [role="dialog"]{background:#FFFFFF !important;color:#252525 !important;}
[data-testid="stDialog"] [data-testid="stDateInput"] input{background:#FFFFFF !important;color:#252525 !important;-webkit-text-fill-color:#252525 !important;}
[data-testid="stDialog"] [data-testid="stDateInput"] [data-baseweb="input"]{background:#FFFFFF !important;}
[data-testid="stDialog"] [data-testid="stFileUploaderDropzone"],
[data-testid="stDialog"] [data-testid="stFileUploaderFile"]{background:#F7F7F8 !important;color:#252525 !important;}
[data-testid="stDialog"] [data-testid="stFileUploader"] small{color:#555555 !important;}
</style>""",unsafe_allow_html=True)
st.markdown("""<style>
/* Neutral outlines including focus states: red is reserved for written errors. */
[data-testid="stTextArea"] [data-baseweb="textarea"],
[data-testid="stTextInput"] [data-baseweb="input"],
[data-testid="stDateInput"] [data-baseweb="input"]{background:#FFFFFF !important;border:1px solid #333333 !important;box-shadow:none !important;outline:none !important;}
[data-testid="stTextArea"] [data-baseweb="textarea"]:focus-within,
[data-testid="stTextInput"] [data-baseweb="input"]:focus-within,
[data-testid="stDateInput"] [data-baseweb="input"]:focus-within{border-color:#333333 !important;box-shadow:none !important;outline:none !important;}
[data-testid="stTextArea"] textarea,[data-testid="stTextInput"] input,[data-testid="stDateInput"] input{background:#FFFFFF !important;color:#252525 !important;-webkit-text-fill-color:#252525 !important;border-color:#333333 !important;outline:none !important;box-shadow:none !important;}
[data-testid="stFileUploaderDropzone"]{background:#F5F5F5 !important;color:#252525 !important;border:1px solid #333333 !important;}
[data-testid="stFileUploaderDropzone"] button,[data-testid="stFileUploaderDropzone"] button:hover{background:#FFFFFF !important;border:1px solid #333333 !important;color:#252525 !important;opacity:1 !important;}
[data-testid="stFileUploaderDropzone"] button *,[data-testid="stFileUploaderDropzone"] p,[data-testid="stFileUploaderDropzone"] span,[data-testid="stFileUploaderDropzone"] small{color:#333333 !important;-webkit-text-fill-color:#333333 !important;opacity:1 !important;}
[data-testid="stFileUploaderDropzone"] svg{color:#333333 !important;fill:currentColor !important;}
</style>""",unsafe_allow_html=True)
@st.dialog('쿨타임 초기화')
def reset_cooldown_dialog(state,rev):
    st.write('다음 추첨까지의 대기 기간만 해제합니다. 행사·사진·후기·달력은 유지돼요.')
    if state.get('current'):
        st.info('진행 중인 행사는 유지되므로 새 추첨은 해당 행사 종료 후 가능합니다.')
    if st.button('쿨타임만 초기화',type='primary',use_container_width=True):
        state['next_draw']=None
        commit(state,rev,'쿨타임을 초기화했어요.')

st.title('🍀 WATO')

try:state,rev=load()
except (sqlite3.Error,ValueError,KeyError,IndexError):
    st.error('가족 기록을 불러오지 못했어요. 다시 로그인하거나 잠시 후 시도해 주세요.');st.stop()
if st.session_state.get('flash'):st.success(st.session_state.pop('flash'))
if st.session_state.get('user') not in state['members']:
    st.subheader('누가 들어오셨나요?')
    for m in state['members']:
        if st.button(m,use_container_width=True):st.session_state.user=m;st.rerun()
    st.caption('이름 변경은 더보기에서 할 수 있어요. 링크를 아는 사람은 접속할 수 있으니 가족끼리만 공유하세요.')
    st.stop()
user=st.session_state.user
c1,c2,c3=st.columns([3,1,1]);c1.write(f'**{user}님**, 함께할 날을 찾아봐요.')
if c2.button('사용자 변경'):
    st.session_state.pop('user',None)
    st.session_state.date_selection=[]
    st.session_state.date_select_mode=False
    st.rerun()
if c3.button('새로고침'):st.rerun()
st.markdown("""<style>
.block-container{padding-bottom:100px !important;}
.st-key-bottom_nav{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:min(100%,480px);background:#FFFFFF;z-index:999;padding:10px 6px calc(10px + env(safe-area-inset-bottom));border-top:1px solid #EEEEEE;box-shadow:0 -3px 18px #0000000D;box-sizing:border-box;}
.st-key-bottom_nav [role="radiogroup"]{display:flex !important;flex-wrap:nowrap !important;gap:0 !important;justify-content:space-around;align-items:center;}
.st-key-bottom_nav [data-testid="stRadio"]>label{display:none;}
.st-key-bottom_nav [role="radiogroup"] label{margin:0 !important;flex:1;justify-content:center;min-width:0;}
.st-key-bottom_nav [role="radiogroup"] label>div:first-child{display:none !important;}
.st-key-bottom_nav [role="radiogroup"] label p{font-size:11px !important;text-align:center;white-space:pre-line;line-height:1.5 !important;}
.st-key-bottom_nav [role="radiogroup"] label:nth-child(3){flex:none;width:64px;height:64px;border-radius:50%;background:#D92D4C !important;margin-top:-28px !important;box-shadow:0 4px 14px #D92D4C44;}
.st-key-bottom_nav [role="radiogroup"] label:nth-child(3) p{color:white !important;font-size:20px !important;font-weight:800;}
.countdown-card{text-align:center;border-radius:24px;background:#FFF3F5;padding:40px 16px;margin:24px 0;color:#252525;}
.countdown-card .dday{font-size:64px;font-weight:900;line-height:1.4;color:#D92D4C;}
</style>""",unsafe_allow_html=True)
st.markdown("""<style>
.block-container{padding-bottom:1rem !important;}
.st-key-top_nav{position:static !important;width:100% !important;margin:8px 0 14px;}
.st-key-top_nav [role="radiogroup"]{display:grid !important;grid-template-columns:repeat(5,minmax(0,1fr));gap:3px !important;width:100%;}
.st-key-top_nav [role="radiogroup"] label{display:flex;justify-content:center;align-items:center;min-width:0;margin:0 !important;padding:9px 0 !important;border:1px solid #E7E7E7;border-radius:10px;background:#FFF4F6;}
.st-key-top_nav [role="radiogroup"] label>div:first-child{display:none !important;}
.st-key-top_nav [role="radiogroup"] label p{text-align:center;white-space:pre-line;font-size:12px !important;line-height:1.5 !important;margin:0;}
.st-key-top_nav input[type="radio"]{position:absolute;opacity:0;width:0;height:0;}
.st-key-top_nav label:has(input:checked){border-color:#D92D4C;background:#FFE4EA;}
</style>""",unsafe_allow_html=True)
home,cal,mem,extra=st.tabs(['🎲 다음 행사','📅 가족 달력','📸 추억','⚙️ 더보기'])
with home:
    with st.container(border=False):
        current=state['current'];next_date=date.fromisoformat(state['next_draw']) if state['next_draw'] else TODAY
        if not current:
            st.markdown('<div class="card"><b>우리 가족의 다음 행사는?</b><br>소목 80% · 중목 15% · 대목 5%<br>분류 추첨 → 행사 추첨, 두 단계로 진행해요.</div>',unsafe_allow_html=True)
            if TODAY<next_date:
                st.info(f'휴식 중이에요. 다음 추첨 {next_date:%Y년 %m월 %d일} · {(next_date-TODAY).days}일 남음')
            if st.button('🎲 1단계 · 친목 유형 뽑기',type='primary',disabled=TODAY<next_date,use_container_width=True):
                ticket_number=secrets.randbelow(100)
                category='소목' if ticket_number<80 else '중목' if ticket_number<95 else '대목'
                state['current']={'id':str(uuid.uuid4()),'category':category,'title':None,'duration':None,'minimum':None,'note':'','drawn':TODAY.isoformat(),'scheduled':None,'votes':{},'draw_ticket':ticket_number+1}
                commit(state,rev,f'{category} 당첨! 이제 행사를 뽑아보세요.',animation={'category':category})
        elif not current['title']:
            category=current['category'];st.subheader(f'🎉 {category} 당첨!')
            if 'draw_ticket' in current: st.caption(f"추첨 번호 {current['draw_ticket']}/100 · 1~80 소목 / 81~95 중목 / 96~100 대목")
            st.caption(f'이 유형의 후보 {len(EVENTS[category])}개에서 하나를 같은 확률로 뽑습니다. 결과는 다시 뽑을 수 없어요.')
            if st.button('🎰 2단계 · 행사 확정하기',type='primary',use_container_width=True):
                event_index=secrets.randbelow(len(EVENTS[category]))
                title,duration,minimum,note=EVENTS[category][event_index]
                current['event_index']=event_index+1
                current.update(title=title,duration=duration,minimum=minimum,note=note)
                commit(state,rev,'행사가 정해졌어요! 가족 달력에 안 되는 날을 제외해 주세요.',animation={'category':category,'title':title})
        else:
            st.markdown(f'<div class="card"><small>{current["category"]} · 다음 가족 행사</small><h3>{html.escape(current["title"])}</h3>완료 후 {COOLDOWN[current["category"]]}개월 휴식</div>',unsafe_allow_html=True)
            if 'draw_ticket' in current:st.caption(f"유형 추첨 번호 {current['draw_ticket']}/100 · 행사 번호 {current.get('event_index','—')}/{len(EVENTS[current['category']])}")
            if current['note']:st.warning(current['note'])
            st.caption('행사·축제 운영일, 요금, 예약, 날씨는 공식 안내로 확인하세요. 추첨은 예약을 보장하지 않습니다.')
            if not current['scheduled']:
                with st.form('duration'):
                    duration=st.number_input('이동·휴식까지 포함한 연속 필요 시간',min_value=int(current['minimum']),max_value=240,value=int(current['duration']),step=1)
                    if st.form_submit_button('필요 시간 적용'):
                        current['duration']=duration;current['votes']={};commit(state,rev,'필요 시간을 변경했습니다.')
                candidates=slots(state,current['duration'])
                missing=[m for m in state['members'] if not intervals(state,m)]
                if missing:st.info('가능 시간 미등록: '+', '.join(missing))
                if not candidates:
                    st.info('모두 가능한 연속 날짜가 없어요. 필요한 시간이나 제외 날짜를 확인해 주세요.')
                else:
                    st.caption('교집합에서 이른 순으로 최대 200개 후보를 표시합니다. 모두 같은 장소에서 만날 수 있는지 별도로 확인하세요.')
                    months=sorted({(a.year,a.month) for a,b in candidates})
                    selected_month=st.selectbox('월 선택',months,format_func=lambda x:f'{x[0]}년 {x[1]}월')
                    month_slots=[i for i,(a,b) in enumerate(candidates) if (a.year,a.month)==selected_month]
                    days=sorted({candidates[i][0].date() for i in month_slots})
                    selected_day=st.selectbox('날짜 선택',days,format_func=lambda d:f'{d.day}일 ({"월화수목금토일"[d.weekday()]})')
                    day_slots=[i for i in month_slots if candidates[i][0].date()==selected_day]
                    def slot_label(i):
                        a,b=candidates[i]
                        return f'{a:%H:%M} ~ {b:%H:%M}' if a.date()==b.date() else f'{a:%H:%M} 출발 · {b.month}월 {b.day}일 {b:%H:%M} 종료'
                    choice=st.selectbox('시간 선택',day_slots,format_func=slot_label)
                    if st.button('이 시간으로 일정 제안',type='primary'):
                        a,b=candidates[choice];current['scheduled']=[a.isoformat(),b.isoformat()];current['votes']={}
                        commit(state,rev,'일정을 제안했어요. 가족 모두 확인해 주세요.')
            else:
                a,b=map(datetime.fromisoformat,current['scheduled'])
                # Revalidate against current availability so later edits cannot silently invalidate a plan.
                valid=all(any(lo<=a and hi>=b for lo,hi in intervals(state,m)) for m in state['members'])
                st.subheader(f'📍 {a:%Y.%m.%d %H:%M} → {b:%m.%d %H:%M}')
                if not valid:st.warning('안 되는 날짜가 변경되어 일정이 맞지 않습니다. 일정 제안을 취소하고 다시 잡아 주세요.')
                votes=current.get('votes',{})
                st.write(' · '.join(m+(' ✓' if votes.get(m)==current['scheduled'] else ' 대기') for m in state['members']))
                if st.button('이 일정 확인했어요',disabled=not valid):
                    current['votes'][user]=current['scheduled'];commit(state,rev,'일정을 확인했습니다.')
                if st.button('일정 제안 취소 · 다시 날짜 찾기'):
                    current['scheduled']=None;current['votes']={};commit(state,rev,'행사는 유지하고 날짜만 다시 정합니다.')
                agreed=all(votes.get(m)==current['scheduled'] for m in state['members'])
                if st.button('📷 행사 완료 기록',use_container_width=True):
                    finish_dialog(state,rev,valid,agreed)
            if st.button('행사 진행이 어려워요',use_container_width=True):
                cancel_event_dialog(state,rev)

with cal:
    with st.container(border=False):
        st.session_state.setdefault('date_selection',[])
        st.session_state.setdefault('date_select_mode',False)
        st.caption('선택 → 날짜 여러 개 누르기 → 한 번에 안 되는 날로 저장')
        if st.button('선택 취소' if st.session_state.date_select_mode else '☑ 날짜 여러 개 선택',use_container_width=True):
            st.session_state.date_select_mode=not st.session_state.date_select_mode
            st.session_state.date_selection=[]
            st.rerun()
        if st.session_state.date_select_mode:
            selected_dates=st.session_state.date_selection
            st.caption(f'{len(selected_dates)}일 선택됨 · 다시 누르면 선택 해제')
            action=st.radio('선택한 날짜 처리',['안 되는 날로 설정','다시 가능한 날로 설정'],horizontal=True,label_visibility='collapsed')
            if st.button('선택한 날짜 저장',type='primary',disabled=not selected_dates,use_container_width=True):
                blocked=set(state.setdefault('blocked',{}).get(user,[]))
                if action=='안 되는 날로 설정':blocked.update(selected_dates)
                else:blocked.difference_update(selected_dates)
                state['blocked'][user]=sorted(blocked)
                if state['current']:state['current']['votes']={}
                st.session_state.date_selection=[]
                st.session_state.date_select_mode=False
                commit(state,rev,'선택한 날짜를 저장했어요.')
    
        st.session_state.setdefault('month',(TODAY.year,TODAY.month))
        y,m=st.session_state.month
        with st.popover(f'📅 {y}년 {m}월 ▾'):
            yy=st.selectbox('연도',list(range(TODAY.year,LAST.year+1)),index=y-TODAY.year)
            mm=st.selectbox('월',range(1,13),index=m-1)
            if st.button('이 달로 이동'):st.session_state.month=(yy,mm);st.rerun()
        prev,today_button,nxt=st.columns(3)
        if prev.button('◀ 지난달',use_container_width=True):
            d=add_months(date(y,m,1),-1);st.session_state.month=(d.year,d.month);st.rerun()
        if today_button.button('오늘 있는 달로',use_container_width=True):st.session_state.month=(TODAY.year,TODAY.month);st.rerun()
        if nxt.button('다음달 ▶',use_container_width=True):
            d=add_months(date(y,m,1),1);st.session_state.month=(d.year,d.month);st.rerun()
        if st.session_state.date_select_mode:
            st.caption('날짜를 손가락으로 쓸어서 여러 날을 선택하세요. 선택한 날짜에서 시작하면 선택이 해제돼요.')
            value=drag_calendar(y,m,st.session_state.date_selection)
            if value is not None:
                other=[d for d in st.session_state.date_selection if not d.startswith(f'{y:04d}-{m:02d}-')]
                merged=sorted(set(other+value))
                if merged!=st.session_state.date_selection:
                    st.session_state.date_selection=merged
                    st.rerun()
        else:
            with st.container(key='monthgrid'):
                st.markdown('<div class="weekdays">'+''.join('<span>'+v+'</span>' for v in '월화수목금토일')+'</div>',unsafe_allow_html=True)
                for week in calendar.Calendar(0).monthdatescalendar(y,m):
                    columns=st.columns(7)
                    for col,d in zip(columns,week):
                        if d.month != m:
                            col.empty()
                            continue
                        count=sum(d.isoformat() not in state.get('blocked',{}).get(n,[]) for n in state['members'])
                        label=f'{d.day}\n{"✓ 모두" if count==len(state["members"]) else str(count)+"명"}'
                        selected=d.isoformat() in st.session_state.date_selection
                        if selected:label=f'☑ {d.day}\n선택됨'
                        elif d.isoformat() in state.get('blocked',{}).get(user,[]):label=f'{d.day}\n내 일정 ✕'
                        if col.button(label,key='day'+d.isoformat(),type='primary' if selected else 'secondary',disabled=d.month!=m or not TODAY<=d<=LAST,use_container_width=True):
                            if st.session_state.date_select_mode:
                                values=set(st.session_state.date_selection)
                                if d.isoformat() in values:values.remove(d.isoformat())
                                else:values.add(d.isoformat())
                                st.session_state.date_selection=sorted(values)
                                st.rerun()
                            else:day_dialog(d)
with mem:
    with st.container(border=False):
        st.subheader('우리 가족의 추억')
        import base64
        completed=[h for h in reversed(state['history']) if h['outcome']=='완료']
        if not completed:st.info('행사 완료 기록에서 사진과 후기를 남겨 주세요.')
        else:
            index=st.selectbox('행사 선택',range(len(completed)),format_func=lambda i:f"{completed[i]['completed']} · {completed[i]['title']}")
            h=completed[index]
            with st.container(height=225,border=False):
                st.write(h.get('review') or '함께한 하루를 기억해요.')
                if h.get('image'):
                    raw=base64.b64decode(h['image']);st.image(raw,width=240)
                    st.download_button('사진 다운로드',raw,'wato_memory.jpg','image/jpeg')
            st.download_button('이 행사 기록 PDF',memory_pdf([h],state['members']),'WATO_memory.pdf','application/pdf',use_container_width=True)
            st.download_button('모든 완료 기록 PDF',memory_pdf(completed,state['members']),'WATO_memories.pdf','application/pdf',use_container_width=True)
        if state.get('photos'):
            with st.popover('이전에 올린 사진'):
                photos=state['photos'];idx=st.selectbox('사진 선택',range(len(photos)),format_func=lambda i:photos[i].get('description') or f'사진 {i+1}')
                raw=base64.b64decode(photos[idx]['image']);st.image(raw,width=200);st.download_button('기존 사진 다운로드',raw,'wato_legacy.jpg','image/jpeg')
with extra:
    with st.container(border=False):
        if st.button('⏱ 쿨타임 초기화',use_container_width=True):
            reset_cooldown_dialog(state,rev)
        if st.button('🗑 모두 초기화',use_container_width=True):
            reset_all_dialog(rev)
        with st.expander('전체 행사 후보 · 각 유형 14개'):
            for category,items in EVENTS.items():
                st.markdown('**'+category+'**')
                for title,duration,minimum,note in items:st.write('• '+title+((' — '+note) if note else ''))
        with st.expander('가족 이름 설정'):
            st.caption('이름은 쉼표로 구분하세요. 변경하면 이전 이름의 가능 시간은 삭제되고 제안 일정의 확인도 초기화됩니다. 진행 중 행사는 유지됩니다.')
            with st.form('members'):
                names=st.text_input('가족 이름',value=', '.join(state['members']))
                acknowledge=st.checkbox('가족과 이름 변경을 합의했습니다.')
                if st.form_submit_button('가족 이름 저장'):
                    members=list(dict.fromkeys(n.strip() for n in names.split(',') if n.strip()))
                    if not acknowledge:st.warning('변경에 동의해 주세요.')
                    elif not 2<=len(members)<=12 or any(len(n)>20 for n in members):st.error('가족은 2~12명, 이름은 20자 이하로 입력하세요.')
                    else:
                        state['members']=members;state['availability']={n:v for n,v in state['availability'].items() if n in members};state['blocked']={n:v for n,v in state.get('blocked',{}).items() if n in members}
                        if state['current']:state['current']['votes']={}
                        commit(state,rev,'가족 이름을 저장했습니다.')
        st.info('규칙: 소목 80% / 중목 15% / 대목 5%. 완료일부터 2 / 4 / 8개월 후 다음 추첨. 재추첨 없이 날짜를 조율하되, 안전과 건강은 언제나 우선입니다.')

# Open the animation only after a successful, committed draw.
if st.session_state.get('roulette_pending'):
    roulette_dialog(**st.session_state.pop('roulette_pending'))
