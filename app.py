"""WATO — 별도 서비스 가입 없이 실행
app.py와 requirements.txt를 GitHub에 올리고 Streamlit Community Cloud에서 app.py 실행.
Python 내장 SQLite로 가족코드와 기록을 서버의 wato.sqlite3에 저장합니다.
앱에서 6자리 코드 발급 → 같은 코드로 가족 로그인 → 사용자 선택.
서버 재생성/재배포 시 로컬 데이터는 사라질 수 있습니다. 장기 보관 보장 없음.
같은 서버 인스턴스의 사용자끼리 공유합니다. 외부 데이터베이스/API 키 불필요.
코드는 공유 비밀번호이며 개인 인증이 아닙니다. 민감한 일정 정보는 넣지 마세요.
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
ROOM=st.session_state.get('room','')
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
    return {'members':['엄마','아빠','나'],'availability':{},'current':None,'history':[], 'next_draw':None,'dart':None}


def load():
    with connection() as db:
        row=db.execute('SELECT data,revision FROM rooms WHERE id=?',(ROOM,)).fetchone()
    if row is None:raise ValueError('가족 공간을 찾지 못했습니다. 다시 로그인해 주세요.')
    return json.loads(row[0]),row[1]


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
    result=[]
    for day,blocks in state['availability'].get(member,{}).items():
        for start,end in blocks:
            d=date.fromisoformat(day)
            a=datetime.combine(d,time())+timedelta(minutes=start)
            b=datetime.combine(d,time())+timedelta(minutes=end)
            if b>a: result.append((a,b))
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
    .wrap{width:min(100%,420px);margin:0 auto;position:relative;padding-top:12px;}
    canvas{display:block;width:min(100%,330px);height:auto;margin:auto;}
    #result{font-size:19px;font-weight:750;min-height:52px;margin:10px 8px;overflow-wrap:anywhere;}
    button{border:0;background:#D92D4C;color:white;padding:10px 18px;border-radius:12px;font-size:15px;}
    </style></head><body><div class="wrap"><canvas id="wheel" width="660" height="660" aria-label="행사 추첨 룰렛"></canvas>
    <div id="result" role="status" aria-live="polite">두근두근… 룰렛이 돌아갑니다!</div><button id="replay" hidden>회전 다시 보기 · 재추첨 아님</button></div>
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
    function run(){document.getElementById('replay').hidden=true;document.getElementById('result').textContent='두근두근… 룰렛이 돌아갑니다!';
      const b=boundaries[cfg.selected],mid=(b[0]+b[1])/2,target=6*tau+(tau-mid),start=performance.now();
      const duration=matchMedia('(prefers-reduced-motion: reduce)').matches?100:4600;
      function frame(now){const t=Math.min(1,(now-start)/duration),ease=1-Math.pow(1-t,4);paint(target*ease);
      if(t<1)requestAnimationFrame(frame);else{document.getElementById('result').textContent='🎉 '+cfg.labels[cfg.selected]+' 당첨!';document.getElementById('replay').hidden=false;}}
      requestAnimationFrame(frame);}
    document.getElementById('replay').onclick=run;run();</script></body></html>"""
    components.html(template.replace('__PAYLOAD__',payload),height=465,scrolling=False)


@st.dialog('🎡 WATO 행운의 룰렛',width='large')
def roulette_dialog(category, title=None):
    st.caption('이번 추첨 결과를 보여주는 룰렛입니다. 다시 보기는 재추첨이 아니므로 같은 결과가 나옵니다.')
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

</style>''',unsafe_allow_html=True)
st.markdown("""<style>
.st-key-monthgrid [data-testid="stHorizontalBlock"]{flex-wrap:nowrap !important;gap:3px !important;}
.st-key-monthgrid [data-testid="stColumn"]{min-width:0 !important;width:0 !important;flex:1 1 0 !important;}
.st-key-monthgrid button,.st-key-monthgrid button:hover{padding:3px 0 !important;min-height:55px !important;}
.st-key-monthgrid button p{font-size:12px !important;white-space:pre-line !important;color:#252525 !important;}
.st-key-monthgrid button:disabled{opacity:.38 !important;}
</style>""",unsafe_allow_html=True)

@st.dialog('📅 이 날의 가족 가능 시간')
def day_dialog(day):
    try: data,revision=load()
    except (sqlite3.Error,ValueError,KeyError):
        st.error('날짜 정보를 불러오지 못했어요.');return
    st.subheader(day.strftime('%Y년 %m월 %d일'))
    for member in data['members']:
        blocks=data['availability'].get(member,{}).get(day.isoformat(),[])
        st.write('**'+member+'** · '+(' / '.join(time_label(a)+'~'+time_label(b) for a,b in blocks) if blocks else '아직 등록하지 않았어요'))
    if not TODAY<=day<=LAST:
        st.caption('가능 시간은 오늘부터 1년 범위에서 등록할 수 있어요.');return
    who=st.session_state.user
    with st.form('day_availability'):
        st.write('**'+who+'님의 가능 시간 등록**')
        full=st.checkbox('하루 종일 가능',value=False)
        start=st.time_input('시작 시간',value=time(9))
        end=st.time_input('종료 시간',value=time(18))
        mode=st.radio('등록 방법',['시간 추가','이 날 시간 교체','이 날 등록 삭제'])
        if st.form_submit_button('저장하기',type='primary',use_container_width=True):
            if not full and start>=end and mode!='이 날 등록 삭제':st.error('종료 시간을 시작보다 늦게 선택하세요.')
            else:
                available=data['availability'].setdefault(who,{})
                key=day.isoformat()
                if mode=='이 날 등록 삭제':available.pop(key,None)
                else:
                    block=[0,1440] if full else [start.hour*60+start.minute,end.hour*60+end.minute]
                    old=available.get(key,[]) if mode=='시간 추가' else []
                    available[key]=[list(x) for x in merge_intervals(old+[block])]
                if data['current']:data['current']['votes']={}
                commit(data,revision,'가능 시간을 저장했어요.')

st.title('🍀 WATO')
st.caption('WE ARE THE ONE · 다음 추억은 어디로?')
st.caption('기록은 현재 서버에 저장돼요. 서버 초기화 시 사라질 수 있으니 추억 탭에서 백업해 주세요.')
if not st.session_state.get('room'):
    st.subheader('우리 가족 공간에 들어가기')
    st.caption('가족에게 받은 숫자 6자리 코드를 입력하세요. 코드를 아는 사람은 가족 일정에 접근할 수 있어요.')
    with st.form('family_login'):
        code=st.text_input('가족코드',max_chars=6,type='password',placeholder='숫자 6자리')
        if st.form_submit_button('로그인',type='primary',use_container_width=True):
            if len(code)!=6 or not code.isascii() or not code.isdigit(): st.error('숫자 6자리를 입력해 주세요.')
            else:
                if clock.time()<st.session_state.get('login_after',0): st.warning('잠시 후 다시 시도해 주세요.')
                else:
                    st.session_state.login_after=clock.time()+3
                    room=hashlib.sha256(('wato:'+code).encode()).hexdigest()
                    try:
                        exists=room_exists(room)
                        if exists: st.session_state.room=room;st.rerun()
                        else: st.error('가입된 코드가 없습니다. 아래에서 가족 공간을 만들어 주세요.')
                    except sqlite3.Error: st.error('연결에 실패했어요. 잠시 후 다시 시도해 주세요.')
    with st.expander('가족코드가 없나요? 가족 가입하기'):
        with st.form('family_register'):
            names=st.text_input('가족 이름',placeholder='엄마, 아빠, 나')
            consent=st.checkbox('발급 코드를 가족에게만 공유하겠습니다.')
            if st.form_submit_button('6자리 코드 발급받기',use_container_width=True):
                members=list(dict.fromkeys(x.strip() for x in names.split(',') if x.strip()))
                if not consent or not 2<=len(members)<=12 or any(len(x)>20 for x in members):
                    st.error('2~12명의 이름을 쉼표로 입력하고 공유 안내를 확인해 주세요.')
                else:
                    try:
                        for attempt in range(10):
                            generated=f'{secrets.randbelow(1000000):06d}'
                            room=hashlib.sha256(('wato:'+generated).encode()).hexdigest()
                            data=initial();data['members']=members
                            created=register_room(room,data)
                            if created:
                                st.session_state.new_code=generated
                                st.session_state.room=room
                                st.rerun()
                        st.error('코드를 발급하지 못했어요. 다시 시도해 주세요.')
                    except sqlite3.Error: st.error('가입 결과를 확인하지 못했어요. 연결을 확인해 주세요.')
    st.stop()
ROOM=st.session_state.room
if st.session_state.get('new_code'):
    st.success('가입 완료! 가족코드: '+st.session_state.new_code)
    st.caption('코드를 먼저 적어두세요. 가족에게 알려주면 같은 공간에 접속할 수 있습니다.')
    if st.button('코드를 저장했어요'): st.session_state.pop('new_code',None);st.rerun()
if st.button('가족 로그아웃'):
    for key in ['room','user','new_code','month','selected','roulette_pending']:st.session_state.pop(key,None)
    st.rerun()
try:state,rev=load()
except (sqlite3.Error,ValueError,KeyError,IndexError):
    st.error('가족 기록을 불러오지 못했어요. 다시 로그인하거나 잠시 후 시도해 주세요.');st.stop()
if st.session_state.get('flash'):st.success(st.session_state.pop('flash'))
if st.session_state.get('user') not in state['members']:
    st.subheader('누가 들어오셨나요?')
    for m in state['members']:
        if st.button(m,use_container_width=True):st.session_state.user=m;st.rerun()
    st.caption('가족 이름은 입장 후 가족 설정에서 변경할 수 있습니다. 사용자 선택은 개인 인증이 아닙니다.')
    st.stop()
user=st.session_state.user
c1,c2,c3=st.columns([3,1,1]);c1.write(f'**{user}님**, 함께할 날을 찾아봐요.')
if c2.button('사용자 변경'):st.session_state.pop('user',None);st.rerun()
if c3.button('새로고침'):st.rerun()
home,cal,mem,extra=st.tabs(['🎲 다음 행사','📅 가족 달력','📸 추억','⚙️ 더보기'])
with home:
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
            commit(state,rev,'행사가 정해졌어요! 가족 달력에 가능 시간을 등록해 주세요.',animation={'category':category,'title':title})
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
                st.info('모두 가능한 연속 시간이 아직 없어요. 달력에서 등록 범위를 넓혀 주세요. 숙박은 밤 시간도 가능으로 등록해야 합니다.')
            else:
                st.caption('교집합에서 이른 순으로 최대 200개 후보를 표시합니다. 모두 같은 장소에서 만날 수 있는지 별도로 확인하세요.')
                choice=st.selectbox('가족 모두 가능한 행사 시간',range(len(candidates)),format_func=lambda i:f'{candidates[i][0]:%Y/%m/%d %H:%M} → {candidates[i][1]:%m/%d %H:%M}')
                if st.button('이 시간으로 일정 제안',type='primary'):
                    a,b=candidates[choice];current['scheduled']=[a.isoformat(),b.isoformat()];current['votes']={}
                    commit(state,rev,'일정을 제안했어요. 가족 모두 확인해 주세요.')
        else:
            a,b=map(datetime.fromisoformat,current['scheduled'])
            # Revalidate against current availability so later edits cannot silently invalidate a plan.
            valid=all(any(lo<=a and hi>=b for lo,hi in intervals(state,m)) for m in state['members'])
            st.subheader(f'📍 {a:%Y.%m.%d %H:%M} → {b:%m.%d %H:%M}')
            if not valid:st.warning('가능 시간이 변경되어 교집합이 깨졌습니다. 일정 제안을 취소하고 다시 잡아 주세요.')
            votes=current.get('votes',{})
            st.write(' · '.join(m+(' ✓' if votes.get(m)==current['scheduled'] else ' 대기') for m in state['members']))
            if st.button('이 일정 확인했어요',disabled=not valid):
                current['votes'][user]=current['scheduled'];commit(state,rev,'일정을 확인했습니다.')
            if st.button('일정 제안 취소 · 다시 날짜 찾기'):
                current['scheduled']=None;current['votes']={};commit(state,rev,'행사는 유지하고 날짜만 다시 정합니다.')
            agreed=all(votes.get(m)==current['scheduled'] for m in state['members'])
            with st.expander('행사 완료 기록'):
                with st.form('finish'):
                    finished=st.date_input('실제로 마친 날짜',value=TODAY,max_value=TODAY)
                    note=st.text_area('한 줄 후기',max_chars=1000,placeholder='기억에 남은 순간을 적어주세요.')
                    confirm=st.checkbox('가족 모두 실제 진행을 확인했습니다.')
                    if st.form_submit_button('완료하고 휴식 시작',disabled=not (valid and agreed)):
                        if not confirm:st.warning('실제 진행 여부를 확인해 주세요.')
                        elif finished<b.date():st.error('예정 종료일보다 이른 완료일은 기록할 수 없습니다.')
                        else:
                            item=copy.deepcopy(current);item.update(completed=finished.isoformat(),review=note,outcome='완료')
                            state['history'].append(item);state['next_draw']=add_months(finished,COOLDOWN[current['category']]).isoformat();state['current']=None
                            commit(state,rev,'추억을 저장했어요. 이제 충분히 쉬어요!')
        with st.expander('안전·건강·운영 중단으로 진행 불가능한 경우'):
            st.caption('행사 수행은 안전보다 우선하지 않습니다. 중단해도 같은 휴식 기간이 적용되며 기록이 남습니다.')
            reason=st.text_input('불가피한 중단 사유',max_chars=500)
            agreed_cancel=st.checkbox('가족 모두와 중단을 합의했습니다.')
            if st.button('사유를 기록하고 중단',disabled=not agreed_cancel):
                if not reason.strip():st.warning('사유를 적어 주세요.')
                else:
                    item=copy.deepcopy(current);item.update(completed=TODAY.isoformat(),review=reason,outcome='중단')
                    state['history'].append(item);state['next_draw']=add_months(TODAY,COOLDOWN[current['category']]).isoformat();state['current']=None
                    commit(state,rev,'중단 사유와 휴식 기간을 기록했습니다.')
with cal:
    st.subheader('날짜를 눌러 가능 시간을 등록하세요')
    st.caption(f'{TODAY:%Y.%m.%d} ~ {LAST:%Y.%m.%d} · 미입력 시간은 불가능으로 처리합니다. 개인정보가 담긴 일정 제목 대신 가능 시간만 등록해요.')
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
    with st.container(key='monthgrid'):
        st.markdown('<div class="weekdays">'+''.join('<span>'+v+'</span>' for v in '월화수목금토일')+'</div>',unsafe_allow_html=True)
        for week in calendar.Calendar(0).monthdatescalendar(y,m):
            columns=st.columns(7)
            for col,d in zip(columns,week):
                count=sum(bool(state['availability'].get(n,{}).get(d.isoformat())) for n in state['members'])
                label=f'{d.day}\n{count}/{len(state["members"])}'
                if col.button(label,key='day'+d.isoformat(),disabled=d.month!=m,use_container_width=True):
                    day_dialog(d)
with mem:
    st.subheader('우리 가족의 추억')
    completed=[h for h in state['history'] if h['outcome']=='완료']
    st.metric('함께한 행사',len(completed))
    if not state['history']:st.info('첫 행사를 마치면 여기에 기록돼요.')
    for h in reversed(state['history']):
        with st.expander(f"{h['completed']} · {h['category']} · {h['title']} · {h['outcome']}"):
            st.write(h.get('review') or '작성된 후기가 없어요.')
            if h.get('scheduled'):st.caption(' ~ '.join(h['scheduled']))
    st.download_button('우리 가족 기록 내려받기',json.dumps(state,ensure_ascii=False,indent=2),'wato_backup.json','application/json')
with extra:
    st.subheader('🎯 국내 지역 다트 뽑기')
    st.caption('지도가 아닌 지역 랜덤 게임입니다. 당첨 행사를 바꾸지 않는 장소 아이디어 도구이며, 해외·지정 축제에는 적용하지 마세요.')
    if st.button('지역 다트 던지기'):
        state['dart']=secrets.choice(REGIONS);commit(state,rev,'장소 아이디어를 뽑았어요!')
    if state.get('dart'):st.success('🎯 '+state['dart'])
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
                    state['members']=members;state['availability']={n:v for n,v in state['availability'].items() if n in members}
                    if state['current']:state['current']['votes']={}
                    commit(state,rev,'가족 이름을 저장했습니다.')
    st.info('규칙: 소목 80% / 중목 15% / 대목 5%. 완료일부터 2 / 4 / 8개월 후 다음 추첨. 재추첨 없이 날짜를 조율하되, 안전과 건강은 언제나 우선입니다.')

# Open the animation only after a successful, committed draw.
if st.session_state.get('roulette_pending'):
    roulette_dialog(**st.session_state.pop('roulette_pending'))
