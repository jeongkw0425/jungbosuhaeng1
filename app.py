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
COOLDOWN={'소목':1,'중목':4,'대목':8}
# title, suggested duration(hours), minimum duration(hours), note
EVENTS={
'소목':[
('벌곡 바베큐 나들이',6,1,'캠핑장 대여 2만원은 사용자 제보입니다. 실제 요금·당일 이용·장비 확인 필수.'),
('영화관에서 영화 보기',4,1,''),('윷놀이 용돈 따기',2,1,'실제 돈 대신 가족이 합의한 소액 상한 또는 간식 쿠폰으로 진행하세요.'),
('가족 외식',3,1,''),('양촌 곶감축제 체험',6,1,'개최 기간 확인 필수'),('가족 나들이',5,1,'가족이 원하는 장소로 가볍게 다녀오세요.'),
('가족 볼링',3,1,''),('동네 카페와 산책',3,1,''),('전통시장 먹거리 탐방',4,1,''),('가족 보드게임',3,1,''),
('공원 피크닉',4,1,'기상 확인'),('가족 사진 찍기',3,1,''),('도자기 원데이 클래스',4,1,'예약 확인'),('미술관 나들이',4,1,'휴관일 확인')],
'중목':[
('배낚시 체험',10,1,'운항·기상·멀미·구명조끼 확인'),('겨울 빙어낚시',10,1,'공식 운영장·개최 기간·얼음 안전 확인'),
('가족 등산',8,1,'가족 체력에 맞는 낮은 코스'),('뮤지컬 관람',7,1,'공연 일정·예매 확인'),('공연 관람',7,1,'공연 일정·예매 확인'),
('지역 축제',10,1,'가족이 원하는 지역 축제 선택 · 공식 개최 일정 확인'),
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
      const chars=Array.from(cfg.labels[i].replace(/ /g,''));
      // Vertical glyphs along each sector's radial centreline, within the wheel.
      ctx.rotate(-Math.PI/2);
      ctx.translate(-185,0);
      const fontSize=Math.min(cfg.labels.length>8?22:30,205/Math.max(chars.length,1));
      ctx.font='bold '+fontSize+'px sans-serif';ctx.textBaseline='middle';
      chars.forEach((ch,j)=>{ctx.save();ctx.translate(262-j*(fontSize+2),0);ctx.rotate(Math.PI/2);ctx.fillText(ch,0,0);ctx.restore();});ctx.restore();});
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
<style>body{margin:0;font:14px sans-serif;color:#252525;background:white}#grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;touch-action:none;user-select:none}.day{border:1px solid #ddd;border-radius:9px;min-height:36px;display:flex;align-items:center;justify-content:center}.sel{background:#D92D4C;color:white}.disabled{opacity:.3}.saved{background:#FFF0F2;border:2px solid #D92D4C}.saved::after{content:'저장됨';font-size:9px;color:#A51E38}.day{flex-direction:column}.sel.saved{background:#D92D4C;color:white}.sel.saved::after{color:white}.head{text-align:center;padding:5px}</style><div id="grid"></div>
<script>
const send=(type,data={})=>parent.postMessage({isStreamlitMessage:true,type,...data},'*');
let picked=new Set(),drag=false,mode=true,last='',args={};
function paint(){document.querySelectorAll('[data-date]').forEach(e=>e.classList.toggle('sel',picked.has(e.dataset.date)))}
function mark(e){if(!e||!e.dataset.date||e.classList.contains('disabled')||last===e.dataset.date)return;last=e.dataset.date;if(mode)picked.add(last);else picked.delete(last);paint()}
window.addEventListener('message',e=>{if(e.data.type!=='streamlit:render')return;args=e.data.args;picked=new Set(args.selected);let g=document.getElementById('grid');g.innerHTML='';for(let v of '月火水木金土日'){let x=document.createElement('div');x.className='head';x.textContent=v;g.appendChild(x)};Array.from(g.children).forEach((x,i)=>x.textContent=['월','화','수','목','금','토','일'][i]);for(let item of args.cells){let x=document.createElement('div');if(item.date){x.className='day'+(item.disabled?' disabled':'')+(item.blocked?' saved':'');x.dataset.date=item.date;x.textContent=item.day}else x.className='blank';g.appendChild(x)}paint();send('streamlit:setFrameHeight',{height:g.offsetHeight+8})});
let g=document.getElementById('grid');
g.addEventListener('pointerdown',e=>{let el=e.target.closest('[data-date]');if(!el||el.classList.contains('disabled'))return;e.preventDefault();drag=true;last='';mode=!picked.has(el.dataset.date);g.setPointerCapture(e.pointerId);mark(el)});
g.addEventListener('pointermove',e=>{if(drag){e.preventDefault();mark(document.elementFromPoint(e.clientX,e.clientY))}});
function finish(){if(!drag)return;drag=false;send('streamlit:setComponentValue',{value:[...picked].sort()})}
g.addEventListener('pointerup',finish);g.addEventListener('pointercancel',finish);
send('streamlit:componentReady',{apiVersion:1});send('streamlit:setFrameHeight',{height:300});
</script>"""
    (folder/'index.html').write_text(html,encoding='utf-8')
    component=components.declare_component('wato_drag_dates',path=str(folder))
    cells=[{'date':d.isoformat(),'day':d.day,'blocked':d.isoformat() in state.get('blocked',{}).get(user,[]),'disabled':not TODAY<=d<=LAST} if d.month==m else {} for w in calendar.Calendar(0).monthdatescalendar(y,m) for d in w]
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

DEFAULT_FAMILY_IMAGE='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'
try:
    header_state,_=load()
    header_image=DEFAULT_FAMILY_IMAGE
except (sqlite3.Error,ValueError):
    header_image=DEFAULT_FAMILY_IMAGE
st.markdown(f'<div style="display:flex;align-items:center;gap:12px"><img alt="가족" src="data:image/png;base64,{header_image}" style="width:64px;height:64px;object-fit:contain;background:white;border-radius:12px"><span style="font-size:2.15rem;font-weight:800;color:#252525">WATO</span></div>',unsafe_allow_html=True)

try:state,rev=load()
except (sqlite3.Error,ValueError,KeyError,IndexError):
    st.error('가족 기록을 불러오지 못했어요. 다시 로그인하거나 잠시 후 시도해 주세요.');st.stop()
background_image=state.get('family_background_image')
if background_image:
    st.markdown(f"""<style>
    [data-testid="stAppViewContainer"] {{
      background-image:linear-gradient(rgba(255,255,255,.62),rgba(255,255,255,.62)),url("data:image/jpeg;base64,{background_image}") !important;
      background-size:cover !important;background-position:center center !important;
      background-repeat:no-repeat !important;background-attachment:fixed !important;
      min-height:100dvh;
    }}
    [data-testid="stMain"],section.main {{background:transparent !important;}}
    </style>""",unsafe_allow_html=True)
if st.session_state.get('flash'):st.success(st.session_state.pop('flash'))
if st.session_state.get('user') not in state['members']:
    st.subheader('누가 들어오셨나요?')
    for m in state['members']:
        if st.button(m,use_container_width=True):st.session_state.user=m;st.rerun()
    st.caption('이름 변경은 더보기에서 할 수 있어요. 링크를 아는 사람은 접속할 수 있으니 가족끼리만 공유하세요.')
    st.stop()
user=st.session_state.user
st.markdown(f'<div class="wato-user-heading"><strong>{html.escape(user)}님</strong>, 함께할 날을 찾아봐요.</div>',unsafe_allow_html=True)
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
.st-key-top_nav [role="radiogroup"]{display:grid !important;grid-template-columns:repeat(4,minmax(0,1fr));gap:3px !important;width:100%;}
.st-key-top_nav [role="radiogroup"] label{display:flex;justify-content:center;align-items:center;min-width:0;margin:0 !important;padding:9px 0 !important;border:1px solid #E7E7E7;border-radius:10px;background:#FFF4F6;}
.st-key-top_nav [role="radiogroup"] label>div:first-child{display:none !important;}
.st-key-top_nav [role="radiogroup"] label p{text-align:center;white-space:pre-line;font-size:12px !important;line-height:1.5 !important;margin:0;}
.st-key-top_nav input[type="radio"]{position:absolute;opacity:0;width:0;height:0;}
.st-key-top_nav label:has(input:checked){border-color:#D92D4C;background:#FFE4EA;}
</style>""",unsafe_allow_html=True)
@st.dialog('📅 행사 일정 정하기',width='small')
def schedule_dialog(state,rev):
    # Dialog interactions rerun independently: always use the latest revision.
    try:
        state,rev=load()
    except (sqlite3.Error,ValueError):
        st.error('오류: 일정을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.')
        return
    current=state.get('current')
    if not current or not current.get('title') or current.get('scheduled'):
        st.info('행사 상태가 변경됐어요. 창을 닫고 현재 일정을 확인해 주세요.')
        return
    with st.form('duration'):
        duration=st.number_input('이동·휴식까지 포함한 연속 필요 시간',min_value=int(current['minimum']),max_value=240,value=int(current['duration']),step=1)
        if st.form_submit_button('필요 시간 적용'):
            previous_duration=current['duration']
            previous_votes=current.get('votes',{}).copy()
            current['duration']=duration
            current['votes']={}
            try:
                save(state,rev)
            except (sqlite3.Error,ValueError):
                current['duration']=previous_duration
                current['votes']=previous_votes
                st.error('오류: 필요 시간을 저장하지 못했어요. 다른 가족의 수정이 있었을 수 있으니 다시 적용해 주세요.')
                return
            else:
                rev+=1
                st.success('필요 시간을 적용했어요. 아래에서 바로 일정을 선택하세요.')
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


# Keep navigation in session state across every widget-triggered rerun.
NAV_PAGES=['🎲 다음 행사','📅 가족 달력','📸 추억','⚙️ 더보기']
# Separate durable navigation state from the former radio widget key.
NAV_IDS=['event','calendar','memories','settings']
if st.session_state.get('wato_navigation_page') not in NAV_PAGES:
    saved_page=st.query_params.get('page','event')
    st.session_state['wato_navigation_page']=NAV_PAGES[NAV_IDS.index(saved_page)] if saved_page in NAV_IDS else NAV_PAGES[0]
def select_nav_page(page):
    st.session_state['wato_navigation_page']=page
    st.query_params['page']=NAV_IDS[NAV_PAGES.index(page)]
with st.container(key='top_nav'):
    nav_columns=st.columns(4,gap='small')
    for nav_column,page in zip(nav_columns,NAV_PAGES):
        selected=st.session_state['wato_navigation_page']==page
        nav_column.button(('🔴 ' if selected else '')+page,
            key='nav_button_'+str(NAV_PAGES.index(page)),
            on_click=select_nav_page,args=(page,),use_container_width=True)
active_page=st.session_state['wato_navigation_page']
if active_page=='🎲 다음 행사':
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
            schedule_html=''
            if current.get('scheduled'):
                start_at,end_at=map(datetime.fromisoformat,current['scheduled'])
                schedule_html=f'<div style="margin-top:8px;font-size:16px;font-weight:700;line-height:1.5;overflow-wrap:anywhere">📍 {start_at:%Y.%m.%d %H:%M} → {end_at:%Y.%m.%d %H:%M}</div>'
            st.markdown(f'<div class="card"><small>{current["category"]} · 다음 가족 행사</small><h3>{html.escape(current["title"])}</h3>완료 후 {COOLDOWN[current["category"]]}개월 휴식{schedule_html}</div>',unsafe_allow_html=True)
            with st.popover('행사 상세 · 추첨 정보',use_container_width=True):
                if 'draw_ticket' in current:st.caption(f"유형 추첨 번호 {current['draw_ticket']}/100 · 행사 번호 {current.get('event_index','—')}/{len(EVENTS[current['category']])}")
                if current['note']:st.warning(current['note'])
                st.caption('행사·축제 운영일, 요금, 예약, 날씨는 공식 안내로 확인하세요. 추첨은 예약을 보장하지 않습니다.')
            if not current['scheduled']:
                st.write('가족 모두 가능한 날짜에서 일정을 정해 주세요.')
                if st.button('📅 일정 정하기',type='primary',use_container_width=True):
                    schedule_dialog(state,rev)
            else:
                a,b=map(datetime.fromisoformat,current['scheduled'])
                # Revalidate against current availability so later edits cannot silently invalidate a plan.
                valid=all(any(lo<=a and hi>=b for lo,hi in intervals(state,m)) for m in state['members'])
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

@st.fragment
def render_family_calendar():
    state,rev=load()
    user=st.session_state.user
    with st.container(border=False):
        st.session_state.setdefault('date_selection',[])
        st.session_state.setdefault('date_select_mode',False)
        st.caption('선택 → 날짜 여러 개 누르기 → 한 번에 안 되는 날로 저장')
        if st.button('선택 취소' if st.session_state.date_select_mode else '☑ 날짜 여러 개 선택',use_container_width=True):
            st.session_state.date_select_mode=not st.session_state.date_select_mode
            st.session_state.date_selection=[]
            st.rerun(scope='fragment')
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
            if st.button('이 달로 이동'):st.session_state.month=(yy,mm);st.rerun(scope='fragment')
        prev,today_button,nxt=st.columns(3)
        if prev.button('◀ 지난달',use_container_width=True):
            d=add_months(date(y,m,1),-1);st.session_state.month=(d.year,d.month);st.rerun(scope='fragment')
        if today_button.button('오늘 있는 달로',use_container_width=True):st.session_state.month=(TODAY.year,TODAY.month);st.rerun(scope='fragment')
        if nxt.button('다음달 ▶',use_container_width=True):
            d=add_months(date(y,m,1),1);st.session_state.month=(d.year,d.month);st.rerun(scope='fragment')
        if st.session_state.date_select_mode:
            st.caption('연분홍·저장됨: 이미 안 되는 날 / 진한 빨강: 지금 선택한 날짜. 손가락으로 쓸어서 선택하세요.')
            value=drag_calendar(y,m,st.session_state.date_selection)
            if value is not None:
                other=[d for d in st.session_state.date_selection if not d.startswith(f'{y:04d}-{m:02d}-')]
                merged=sorted(set(other+value))
                if merged!=st.session_state.date_selection:
                    st.session_state.date_selection=merged
                    st.rerun(scope='fragment')
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
                        available_names=[n for n in state['members'] if d.isoformat() not in state.get('blocked',{}).get(n,[])]
                        if len(available_names)==len(state['members']):
                            availability_label='모두 가능'
                        elif not available_names:
                            availability_label='모두 불가'
                        else:
                            availability_label=' · '.join(available_names)+' 가능'
                        label=f'{d.day}\n{availability_label}'
                        selected=d.isoformat() in st.session_state.date_selection
                        if selected:label=f'☑ {d.day}\n선택됨'
                        if col.button(label,key='day'+d.isoformat(),type='primary' if selected else 'secondary',disabled=d.month!=m or not TODAY<=d<=LAST,use_container_width=True):
                            if st.session_state.date_select_mode:
                                values=set(st.session_state.date_selection)
                                if d.isoformat() in values:values.remove(d.isoformat())
                                else:values.add(d.isoformat())
                                st.session_state.date_selection=sorted(values)
                                st.rerun(scope='fragment')
                            else:day_dialog(d)

if active_page=='📅 가족 달력':
    render_family_calendar()
if active_page=='📸 추억':
    with st.container(border=False):
        st.subheader('우리 가족의 추억')
        import base64
        completed=[h for h in reversed(state['history']) if h['outcome']=='완료']
        if not completed:st.info('행사 완료 기록에서 사진과 후기를 남겨 주세요.')
        else:
            index=st.selectbox('행사 선택',range(len(completed)),format_func=lambda i:f"{completed[i]['completed']} · {completed[i]['title']}")
            h=completed[index]
            import re
            record_filename=re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', str(h['completed'])+'_'+str(h['title'])).strip(' .')[:150] or '행사기록'
            with st.container(height=225,border=False):
                st.write(h.get('review') or '함께한 하루를 기억해요.')
                if h.get('image'):
                    raw=base64.b64decode(h['image']);st.image(raw,width=240)
                    st.download_button('사진 다운로드',raw,record_filename+'.jpg','image/jpeg')
            st.download_button('이 행사 기록 PDF',memory_pdf([h],state['members']),record_filename+'.pdf','application/pdf',use_container_width=True)
            st.download_button('모든 완료 기록 PDF',memory_pdf(completed,state['members']),min(str(item['completed']) for item in completed)+'_'+max(str(item['completed']) for item in completed)+'_전체행사기록.pdf','application/pdf',use_container_width=True)
        if state.get('photos'):
            with st.popover('이전에 올린 사진'):
                photos=state['photos'];idx=st.selectbox('사진 선택',range(len(photos)),format_func=lambda i:photos[i].get('description') or f'사진 {i+1}')
                raw=base64.b64decode(photos[idx]['image']);st.image(raw,width=200);st.download_button('기존 사진 다운로드',raw,'wato_legacy.jpg','image/jpeg')
if active_page=='⚙️ 더보기':
    with st.container(border=False):
        with st.popover('🖼 WATO 배경사진 변경',use_container_width=True):
            st.caption('가족 모두에게 적용돼요. 세로 사진을 권장해요. 화면에 맞춰 채우므로 가장자리가 일부 잘릴 수 있어요.')
            header_upload=st.file_uploader('사진 선택',type=['jpg','jpeg','png','webp'],key='family_header_upload')
            if st.button('사진 적용',key='apply_family_header',disabled=header_upload is None,use_container_width=True):
                try:
                    import io,base64
                    from PIL import Image,ImageOps
                    if header_upload.size>10*1024*1024:
                        raise ValueError('사진은 10MB 이하로 선택해 주세요.')
                    with Image.open(header_upload) as source:
                        image=ImageOps.exif_transpose(source).convert('RGBA')
                        image.thumbnail((1440,2560))
                        canvas=Image.new('RGB',image.size,'white')
                        canvas.paste(image,(0,0),image)
                        buffer=io.BytesIO()
                        canvas.save(buffer,format='JPEG',quality=85)
                    state['family_background_image']=base64.b64encode(buffer.getvalue()).decode('ascii')
                except Exception as error:
                    st.error('오류: '+(str(error) if isinstance(error,ValueError) else '사진을 읽지 못했어요. 다른 사진을 선택해 주세요.'))
                else:
                    commit(state,rev,'WATO 배경사진을 변경했어요.')
            if st.button('기본 배경으로 복원',key='restore_family_header',use_container_width=True):
                state.pop('family_background_image',None)
                commit(state,rev,'기본 배경으로 복원했어요.')

        if st.button('사용자 변경',key='user_switch',use_container_width=True):
            st.session_state.pop('user',None)
            st.session_state.date_selection=[]
            st.session_state.date_select_mode=False
            st.rerun()
        if st.button('⏱ 쿨타임 초기화',use_container_width=True):
            reset_cooldown_dialog(state,rev)
        if st.button('🗑 모두 초기화',use_container_width=True):
            reset_all_dialog(rev)
        with st.popover('전체 행사 후보',use_container_width=True):
            for category,items in EVENTS.items():
                st.markdown('**'+category+'**')
                for title,duration,minimum,note in items:st.write('• '+title+((' — '+note) if note else ''))
        with st.popover('가족 설정',use_container_width=True):
            st.caption('이름은 쉼표로 구분하세요. 변경하면 이전 이름의 가능 시간은 삭제되고 제안 일정의 확인도 초기화됩니다. 진행 중 행사는 유지됩니다.')
            with st.form('members'):
                names=st.text_input('가족 이름',value=', '.join(state['members']))
                acknowledge=st.checkbox('가족과 이름 추가 및 변경을 합의했습니다.')
                if st.form_submit_button('가족 추가·변경 저장'):
                    members=list(dict.fromkeys(n.strip() for n in names.split(',') if n.strip()))
                    if not acknowledge:st.warning('변경에 동의해 주세요.')
                    elif not 2<=len(members)<=12 or any(len(n)>20 for n in members):st.error('가족은 2~12명, 이름은 20자 이하로 입력하세요.')
                    else:
                        state['members']=members;state['availability']={n:v for n,v in state['availability'].items() if n in members};state['blocked']={n:v for n,v in state.get('blocked',{}).items() if n in members}
                        if state['current']:state['current']['votes']={}
                        commit(state,rev,'가족 이름을 저장했습니다.')
        with st.popover('이용 규칙',use_container_width=True):
            st.info('소목 80% / 중목 15% / 대목 5%. 완료일부터 1 / 4 / 8개월 후 다음 추첨. 재추첨 없이 날짜를 조율하되, 안전과 건강은 언제나 우선입니다.')

# Open the animation only after a successful, committed draw.
if st.session_state.get('roulette_pending'):
    roulette_dialog(**st.session_state.pop('roulette_pending'))

# Mobile-only spacing adjustment; preserve content, order, and accessible overflow.
st.markdown("""<style>
@media (max-width: 640px) {
  .block-container {padding-top:.45rem !important;padding-bottom:.45rem !important;}
  [data-testid="stHeader"] {height:0 !important;min-height:0 !important;background:transparent !important;}
  [data-testid="stVerticalBlock"] {gap:.38rem !important;}
  h1 {font-size:1.65rem !important;padding-top:0 !important;padding-bottom:.2rem !important;}
  h2,h3 {padding-top:.15rem !important;padding-bottom:.15rem !important;}
  p {margin-bottom:.25rem !important;}
  .st-key-top_nav {margin:3px 0 6px !important;}
  .st-key-top_nav [role="radiogroup"] label {padding:7px 0 !important;}
  .card {padding:12px !important;margin:5px 0 !important;}
  .st-key-monthgrid [data-testid="stHorizontalBlock"] {gap:3px !important;flex-wrap:nowrap !important;}
  .st-key-monthgrid [data-testid="stColumn"] {min-width:0 !important;flex:1 1 0 !important;}
  .st-key-monthgrid [data-testid="stVerticalBlock"] {gap:3px !important;}
  .st-key-monthgrid button {min-height:44px !important;}
  [data-testid="stDialog"] [role="dialog"] {max-height:90dvh !important;overflow-y:auto !important;}
}
</style>""",unsafe_allow_html=True)

# Suppress browser scroll chaining/pull-to-refresh where supported.
# Keep ordinary content scrolling and calendar pointer gestures intact.
st.markdown("""<style>
@media (max-width: 640px) {
  html, body, [data-testid="stApp"],
  [data-testid="stAppViewContainer"],
  [data-testid="stMain"], section.main {
    overscroll-behavior-y: none !important;
  }
  [data-testid="stDialog"] [role="dialog"],
  [data-testid="stPopoverBody"] {
    overscroll-behavior-y: contain !important;
    -webkit-overflow-scrolling: touch;
  }
}
</style>""",unsafe_allow_html=True)

# Navigation: target the native radio marker, never the text wrapper.
st.markdown("""<style>
.st-key-top_nav {width:100% !important;}
.st-key-top_nav [data-testid="stRadio"] {width:100% !important;}
.st-key-top_nav [role="radiogroup"] {
 display:grid !important;grid-template-columns:repeat(4,minmax(0,1fr)) !important;
 width:100% !important;gap:4px !important;align-items:stretch !important;
}
.st-key-top_nav [role="radiogroup"] label {
 display:flex !important;justify-content:center !important;align-items:center !important;
 box-sizing:border-box !important;position:relative !important;
 width:100% !important;min-width:0 !important;height:52px !important;
 margin:0 !important;padding:14px 2px 4px !important;gap:0 !important;
}
/* Restore label content hidden by the previous overly broad rule. */
.st-key-top_nav [role="radiogroup"] label > div:first-child {display:flex !important;}
.st-key-top_nav [role="radiogroup"] label > div {min-width:0 !important;}
.st-key-top_nav [role="radiogroup"] label [data-testid="stMarkdownContainer"] {display:block !important;min-width:0 !important;}
.st-key-top_nav [role="radiogroup"] label [data-baseweb="radio"] > div:first-child {display:none !important;}
.st-key-top_nav [role="radiogroup"] label > div:first-child:not(:has([data-testid="stMarkdownContainer"])):not([data-testid="stMarkdownContainer"]) {display:none !important;}
.st-key-top_nav [role="radiogroup"] label p {
 white-space:nowrap !important;word-break:keep-all !important;
 font-size:12px !important;line-height:20px !important;margin:0 !important;color:#252525 !important;
}
.st-key-top_nav [role="radiogroup"] label:has(input:checked)::after {
 content:"";position:absolute;top:5px;left:calc(50% - 3px);
 width:6px;height:6px;border-radius:50%;background:#D92D4C;
}
.weekdays {height:auto !important;min-height:28px !important;line-height:24px !important;padding:2px 0 !important;overflow:visible !important;}
.weekdays span {display:block;line-height:24px !important;min-height:24px !important;overflow:visible !important;}
</style>""",unsafe_allow_html=True)

st.markdown("""<style>
.st-key-top_nav > div {width:100% !important;}
.st-key-top_nav [data-testid="stElementContainer"] {width:100% !important;min-width:0 !important;}
</style>""",unsafe_allow_html=True)

st.markdown("""<style>
.st-key-top_nav label[data-baseweb="radio"] > div:first-of-type {
 display:none !important;
}
.st-key-top_nav label[data-baseweb="radio"] > input[type="radio"] {
 position:absolute !important;opacity:0 !important;width:1px !important;height:1px !important;
}
.st-key-top_nav label[data-baseweb="radio"] > div:has([data-testid="stMarkdownContainer"]),
.st-key-top_nav label[data-baseweb="radio"] > div[data-testid="stMarkdownContainer"] {
 display:block !important;
}
</style>""",unsafe_allow_html=True)

# Navigation uses plain buttons: no native radio control exists anymore.
st.markdown("""<style>
.st-key-top_nav [data-testid="stHorizontalBlock"] {
 display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;gap:4px !important;
}
.st-key-top_nav [data-testid="stColumn"] {
 flex:1 1 0 !important;min-width:0 !important;width:0 !important;
}
.st-key-top_nav button,.st-key-top_nav button:hover,.st-key-top_nav button:active {
 width:100% !important;min-height:48px !important;height:48px !important;
 padding:4px 1px !important;background:#FFF4F6 !important;
 color:#252525 !important;border:1px solid #E7E7E7 !important;border-radius:10px !important;
}
.st-key-top_nav button p {white-space:nowrap !important;font-size:11px !important;line-height:20px !important;margin:0 !important;}
</style>""",unsafe_allow_html=True)

st.markdown("""<style>
.st-key-user_switch button p {white-space:nowrap !important;word-break:keep-all !important;}
</style>""",unsafe_allow_html=True)

st.markdown("""<style>
[data-testid="stHeadingWithActionElements"] h1 {font-size:2.15rem !important;line-height:1.3 !important;}
.wato-user-heading {font-size:1.25rem;line-height:1.5;margin:2px 0 10px;color:#252525;overflow-wrap:anywhere;}
.wato-user-heading strong {font-size:1.45rem;}
@media (max-width:640px) {
 h1 {font-size:2.05rem !important;}
 .wato-user-heading {font-size:1.05rem;}
 .wato-user-heading strong {font-size:1.3rem;}
}
</style>""",unsafe_allow_html=True)
