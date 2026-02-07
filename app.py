import os
import requests
import sqlite3
import time
import threading
import traceback
import pandas as pd
import plotly.express as px
from flask import Flask, request, redirect, session, jsonify

# ================= CONFIG =================
DEVICE = "278910"

AUTH_URL = "https://account.groupcls.com/auth/realms/cls/protocol/openid-connect/token"
API_URL  = "https://api.groupcls.com/telemetry/api/v1/retrieve-bulk"

CLS_TOKEN = None
LAST_FETCH = None

app = Flask(__name__)
app.secret_key = "eco_super_secret"

# ================= DATABASE =================
def db():
    return sqlite3.connect("database.db", check_same_thread=False)

conn=db()
cur=conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS data(
id INTEGER PRIMARY KEY AUTOINCREMENT,
date TEXT UNIQUE,
temp REAL,
hum REAL,
press REAL,
lux REAL
)
""")
conn.commit()
conn.close()

# ================= DECODE =================
def decode(hexdata):

    if len(hexdata)!=32:
        return None

    try:
        temp=int(hexdata[0:4],16)/100
        hum=int(hexdata[4:8],16)/100
        pres=int(hexdata[8:12],16)/10
        lux=int(hexdata[12:20],16)

        if temp<-40 or temp>80: return None
        if hum<0 or hum>100: return None
        if pres<800 or pres>1200: return None

        return temp,hum,pres,lux
    except:
        return None

# ================= LOGIN CLS =================
def login_cls(username,password):
    global CLS_TOKEN

    data={
        "grant_type":"password",
        "client_id":"api-telemetry",
        "username":username,
        "password":password
    }

    r=requests.post(AUTH_URL,data=data)

    if r.status_code==200:
        CLS_TOKEN=r.json()["access_token"]
        print("🟢 CLS connecté")
        return True
    else:
        print("❌ CLS login fail")
        return False

# ================= GET DATA =================
def get_data():
    global CLS_TOKEN, LAST_FETCH

    if not CLS_TOKEN:
        return

    headers={"Authorization":"Bearer "+CLS_TOKEN}

    from_date = LAST_FETCH if LAST_FETCH else "2026-01-01T00:00:00.000Z"

    body={
        "pagination":{"first":50},
        "retrieveRawData":True,
        "retrieveMetadata":True,
        "deviceRefs":[DEVICE],
        "fromDatetime":from_date,
        "toDatetime":"2030-01-01T00:00:00.000Z",
        "datetimeFormat":"DATETIME"
    }

    r=requests.post(API_URL,json=body,headers=headers)

    if r.status_code==401:
        CLS_TOKEN=None
        return

    if r.status_code!=200:
        print("API error",r.text)
        return

    data=r.json()
    if "contents" not in data:
        return

    for m in data["contents"]:
        hexdata=m.get("rawData","")
        d=m.get("msgDatetime","")

        dec=decode(hexdata)
        if not dec: continue

        t,h,p,l=dec
        print("📡",d,t,h,p,l)

        try:
            conn=db()
            cur=conn.cursor()
            cur.execute("""
            INSERT OR IGNORE INTO data(date,temp,hum,press,lux)
            VALUES(?,?,?,?,?)
            """,(d,t,h,p,l))
            conn.commit()
            conn.close()
        except Exception as e:
            print("DB error:", e)
            traceback.print_exc()

        LAST_FETCH=d

# ================= THREAD =================
def loop():
    while True:
        get_data()
        time.sleep(60)

threading.Thread(target=loop,daemon=True).start()

# ================= LOGIN PAGE =================
@app.route("/", methods=["GET","POST"])
def login():

    error=""

    if request.method=="POST":
        email=request.form.get("email")
        pwd=request.form.get("pwd")

        if not email or not pwd:
            error="Enter email and password"
        else:
            ok=login_cls(email,pwd)

            if ok:
                session["login"]=True
                return redirect("/dashboard")
            else:
                error="❌ CLS login incorrect"

    return f"""
    <html>
    <head>
    <title>ECOLOGGING LOGIN</title>
    <style>
    body{{background:#020617;color:white;text-align:center;font-family:Arial}}
    .box{{margin-top:120px}}
    input{{padding:14px;margin:10px;width:280px;border-radius:10px;border:none}}
    button{{padding:14px 40px;background:#00ffe1;border:none;border-radius:12px}}
    .error{{color:red;font-size:18px}}
    </style>
    </head>
    <body>
    <div class="box">
    <h1>🛰️ ECOLOGGING SECURE</h1>
    <form method="post">
    <input name="email" placeholder="CLS email"><br>
    <input name="pwd" type="password" placeholder="CLS password"><br>
    <button>Connexion</button>
    </form>
    <div class="error">{error}</div>
    </div>
    </body>
    </html>
    """

# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= API DATA (AJAX) =================
@app.route("/api/data")
def api_data():

    conn=db()
    df=pd.read_sql_query("SELECT * FROM data ORDER BY date ASC",conn)
    conn.close()

    return df.to_json(orient="records")

# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():

    if not session.get("login"):
        return redirect("/")

    return f"""
    <html>
    <head>
    <title>ECOLOGGING - INRAe</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>

    <style>
    body{{background:#020617;color:white;text-align:center;font-family:Arial}}
    .top{{position:absolute;right:20px;top:20px}}
    button{{padding:10px 20px;background:red;border:none;border-radius:8px;color:white}}
    </style>
    </head>

    <body>

    <div class="top">
    <a href="/logout"><button>Logout</button></a>
    </div>

    <h1>🛰️ ECOLOGGING - INRAe</h1>
    <h3>Device ID : {DEVICE}</h3>

    <div id="graph" style="width:95%;margin:auto;"></div>

<script>

let firstLoad=true;
let layoutSaved=null;

async function loadData(){{

    let r = await fetch('/api/data');
    let data = await r.json();

    if(data.length==0) return;

    let dates=data.map(d=>d.date);

    let temp=data.map(d=>d.temp);
    let hum=data.map(d=>d.hum);
    let press=data.map(d=>d.press);
    let lux=data.map(d=>d.lux);

    let traces=[
        {{x:dates,y:temp,name:'Temp',type:'scatter'}},
        {{x:dates,y:hum,name:'Hum',type:'scatter'}},
        {{x:dates,y:press,name:'Press',type:'scatter'}},
        {{x:dates,y:lux,name:'Lux',type:'scatter'}}
    ];

    if(firstLoad){{
        Plotly.newPlot('graph',traces,{{template:'plotly_dark'}});
        firstLoad=false;
    }}else{{
        Plotly.react('graph',traces,layoutSaved||{{template:'plotly_dark'}});
    }}
}}

setInterval(loadData,15000);

document.getElementById('graph')?.on('plotly_relayout', function(e){{
    layoutSaved=e;
}});

loadData();

</script>

    </body>
    </html>
    """
    
# ================= RUN =================
port=int(os.environ.get("PORT",10000))
app.run(host="0.0.0.0",port=port)
