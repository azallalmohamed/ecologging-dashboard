import os
import requests
import sqlite3
import time
import threading
import traceback
import pandas as pd
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

    try:
        r=requests.post(API_URL,json=body,headers=headers,timeout=20)
    except:
        print("CLS offline")
        return

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
        except:
            pass

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

        ok=login_cls(email,pwd)

        if ok:
            session["login"]=True
            return redirect("/dashboard")
        else:
            error="Email ou mot de passe incorrect"

    return f"""
    <html>
    <body style="background:#020617;color:white;text-align:center;font-family:Arial">
    <h1>🛰️ ECOLOGGING LOGIN</h1>
    <form method="post">
    <input name="email" placeholder="CLS Email"><br><br>
    <input name="pwd" type="password" placeholder="CLS Password"><br><br>
    <button>Connexion</button>
    </form>
    <div style="color:red">{error}</div>
    </body>
    </html>
    """

# ================= API DATA LIVE =================
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
<!DOCTYPE html>
<html>
<head>
<title>ECOLOGGING PRO</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>

<style>
body{{background:#020617;color:white;text-align:center;font-family:Arial}}
.card{{display:inline-block;background:#111;padding:20px;margin:10px;border-radius:14px}}
button{{padding:10px 25px;background:red;color:white;border:none;border-radius:8px}}
</style>
</head>

<body>

<h1>🛰️ ECOLOGGING PRO LIVE</h1>
<h3>Device {DEVICE}</h3>

<button onclick="window.location='/logout'">Déconnexion</button>

<div id="graph" style="width:95%;height:75vh;margin:auto"></div>

<script>

let layout={{
    template:"plotly_dark",
    title:"Station Live",
    xaxis:{{title:"Date"}},
    yaxis:{{title:"Valeurs"}}
}};

let config={{responsive:true}};

function load(){{
fetch("/api/data")
.then(r=>r.json())
.then(data=>{{

let x=data.map(d=>d.date);

let temp=data.map(d=>d.temp);
let hum=data.map(d=>d.hum);
let press=data.map(d=>d.press);
let lux=data.map(d=>d.lux);

let traces=[
{{x:x,y:temp,name:"Temp °C"}},
{{x:x,y:hum,name:"Hum %"}},
{{x:x,y:press,name:"Press"}},
{{x:x,y:lux,name:"Lux"}}
];

Plotly.react("graph",traces,layout,config);

}});
}}

load();
setInterval(load,15000);

</script>

</body>
</html>
"""

# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= RUN =================
port=int(os.environ.get("PORT",10000))
app.run(host="0.0.0.0",port=port)
