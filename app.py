import os
import requests
import sqlite3
import time
import threading
import pandas as pd
import plotly.express as px
from flask import Flask, request, redirect, session

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

# ================= LOGIN CLS DIRECT =================
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
        print("pas connecté CLS")
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
        print("token expiré")
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
        except:
            pass

        LAST_FETCH=d

# ================= THREAD =================
def loop():
    while True:
        get_data()
        time.sleep(60)

threading.Thread(target=loop,daemon=True).start()

# ================= PAGE LOGIN CLS =================
@app.route("/", methods=["GET","POST"])
def login():

    error = ""

    if request.method=="POST":
        email=request.form.get("email")
        pwd=request.form.get("pwd")

        if not email or not pwd:
            error = "Veuillez entrer email et mot de passe"

        else:
            ok = login_cls(email,pwd)

            if ok:
                session["login"]=True
                return redirect("/dashboard")
            else:
                error = "Email ou mot de passe CLS incorrect"

    return f"""
    <html>
    <head>
    <title>ECOLOGGING Secure</title>
    <style>
    body{{background:#020617;color:white;text-align:center;font-family:Arial}}
    .box{{margin-top:120px}}
    input{{padding:14px;margin:10px;width:280px;border-radius:10px;border:none}}
    button{{padding:14px 40px;background:#00ffe1;border:none;border-radius:12px;font-size:16px}}
    .error{{color:#ff4d4d;font-size:18px;margin-top:10px}}
    </style>
    </head>

    <body>
    <div class="box">
    <h1>🛰️ ECOLOGGING SECURE ACCESS</h1>
    <h3>Connexion satellite CLS</h3>

    <form method="post">
    <input name="email" placeholder="CLS Email"><br>
    <input name="pwd" type="password" placeholder="CLS Password"><br>
    <button>Connexion</button>
    </form>

    <div class="error">{error}</div>
    </div>
    </body>
    </html>
    """


# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():

    if not session.get("login"):
        return redirect("/")

    conn=db()
    df=pd.read_sql_query("SELECT * FROM data ORDER BY date DESC LIMIT 2000",conn)
    conn.close()

    if len(df)==0:
        return "<h1 style='color:white'>Connexion satellite...</h1>"

    df["date"]=pd.to_datetime(df["date"])
    df=df.sort_values("date")

    fig=px.line(df,x="date",y=["temp","hum","press","lux"],
                title=f"ECOLOGGING Station — Device {DEVICE}",
                template="plotly_dark")

    graph=fig.to_html(full_html=False)
    last=df.iloc[-1]

    html=f"""
    <html>
    <head>
    <meta http-equiv='refresh' content='30'>
    <style>
    body{{background:#020617;color:white;text-align:center;font-family:Arial}}
    .card{{display:inline-block;background:#111;padding:20px;margin:10px;border-radius:14px}}
    h1{{color:#00ffe1}}
    </style>
    </head>

    <body>

    <h1>🛰️ ECOLOGGING PRO</h1>
    <h3>Device : {DEVICE}</h3>

    <div class="card">🌡 {last.temp:.2f} °C</div>
    <div class="card">💧 {last.hum:.2f} %</div>
    <div class="card">📊 {last.press:.1f} hPa</div>
    <div class="card">☀️ {last.lux}</div>

    {graph}

    </body>
    </html>
    """
    return html

# ================= RUN =================
port=int(os.environ.get("PORT",10000))
app.run(host="0.0.0.0",port=port)
