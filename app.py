import os
import requests
import sqlite3
import time
import threading
import pandas as pd
import plotly.express as px
from flask import Flask

# ================= CONFIG =================
DEVICE = "278910"
CLS_USER = os.environ.get("CLS_USER")
CLS_PASS = os.environ.get("CLS_PASS")

AUTH_URL = "https://account.groupcls.com/auth/realms/cls/protocol/openid-connect/token"
API_URL  = "https://api.groupcls.com/telemetry/api/v1/retrieve-bulk"

CLS_TOKEN = None
LAST_FETCH = None   # pour récupérer seulement nouvelles data

# ================= DATABASE =================
def db():
    return sqlite3.connect("database.db", check_same_thread=False)

conn = db()
cur = conn.cursor()
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

# ================= DECODE PAYLOAD ARDUINO =================
def decode(hexdata):

    # payload Arduino = 32 hex (16 bytes)
    if len(hexdata) != 32:
        return None

    try:
        temp_raw = int(hexdata[0:4],16)
        hum_raw  = int(hexdata[4:8],16)
        pres_raw = int(hexdata[8:12],16)
        lux_raw  = int(hexdata[12:20],16)

        temp = temp_raw/100
        hum  = hum_raw/100
        pres = pres_raw/10
        lux  = lux_raw

        # filtre valeurs parasites
        if temp < -40 or temp > 80: return None
        if hum < 0 or hum > 100: return None
        if pres < 800 or pres > 1200: return None
        if lux > 200000: return None

        return temp,hum,pres,lux
    except:
        return None

# ================= LOGIN CLS =================
def login_cls():
    global CLS_TOKEN

    if not CLS_USER or not CLS_PASS:
        print("❌ CLS_USER ou CLS_PASS manquant dans Render")
        return

    data = {
        "grant_type":"password",
        "client_id":"api-telemetry",
        "username":CLS_USER,
        "password":CLS_PASS
    }

    r = requests.post(AUTH_URL,data=data)

    if r.status_code == 200:
        CLS_TOKEN = r.json()["access_token"]
        print("🟢 CLS connecté")
    else:
        print("❌ Erreur login CLS :", r.text)
        CLS_TOKEN = None

# ================= GET DATA CLS =================
def get_data():
    global CLS_TOKEN, LAST_FETCH

    if not CLS_TOKEN:
        login_cls()
        return

    headers = {"Authorization":"Bearer "+CLS_TOKEN}

    # récupérer seulement nouvelles données
    if LAST_FETCH:
        from_date = LAST_FETCH
    else:
        from_date = "2026-01-01T00:00:00.000Z"

    body = {
        "pagination":{"first":50},
        "retrieveRawData":True,
        "retrieveMetadata":True,
        "deviceRefs":[DEVICE],
        "fromDatetime":from_date,
        "toDatetime":"2030-01-01T00:00:00.000Z",
        "datetimeFormat":"DATETIME"
    }

    try:
        r = requests.post(API_URL,json=body,headers=headers,timeout=20)
    except:
        print("⚠️ réseau CLS off")
        return

    if r.status_code == 401:
        print("🔄 Token expiré → relogin")
        CLS_TOKEN = None
        return

    if r.status_code != 200:
        print("❌ API CLS:", r.text)
        return

    data = r.json()

    if "contents" not in data:
        print("...pas nouvelles data")
        return

    for m in data["contents"]:
        hexdata = m.get("rawData","")
        d = m.get("msgDatetime","")

        decoded = decode(hexdata)
        if not decoded:
            continue

        t,h,p,l = decoded
        print("📡",d,"T:",t,"H:",h,"P:",p,"L:",l)

        try:
            conn = db()
            cur = conn.cursor()
            cur.execute("""
            INSERT OR IGNORE INTO data(date,temp,hum,press,lux)
            VALUES(?,?,?,?,?)
            """,(d,t,h,p,l))
            conn.commit()
            conn.close()
        except:
            pass

        LAST_FETCH = d  # mémorise dernière data

# ================= THREAD LOOP =================
def loop():
    while True:
        get_data()
        time.sleep(60)   # CLS recommande ≥60s

threading.Thread(target=loop,daemon=True).start()

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def home():

    conn = db()
    df = pd.read_sql_query("SELECT * FROM data ORDER BY date DESC LIMIT 2000", conn)
    conn.close()

    if len(df)==0:
        return """
        <html>
        <body style="background:black;color:white;text-align:center;font-family:Arial">
        <h1>🛰️ ECOLOGGING</h1>
        <h2>Connexion satellite en cours...</h2>
        </body></html>
        """

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    # graphique pro
    fig = px.line(
        df,
        x="date",
        y=["temp","hum","press","lux"],
        title="ECOLOGGING Satellite Station — 30 jours",
        template="plotly_dark"
    )

    graph = fig.to_html(full_html=False)

    last = df.iloc[-1]

    html = f"""
    <html>
    <head>
    <meta http-equiv='refresh' content='30'>
    <title>ECOLOGGING Satellite</title>
    <style>
    body{{background:#020617;color:white;text-align:center;font-family:Arial}}
    h1{{color:#00ffe1}}
    .card{{display:inline-block;background:#111;padding:20px;margin:10px;border-radius:14px}}
    </style>
    </head>

    <body>

    <h1>🛰️ ECOLOGGING Satellite Station</h1>

    <div class="card">🌡 Temp<br><h2>{last.temp:.2f} °C</h2></div>
    <div class="card">💧 Humidité<br><h2>{last.hum:.2f} %</h2></div>
    <div class="card">📊 Pression<br><h2>{last.press:.1f} hPa</h2></div>
    <div class="card">☀️ Lux<br><h2>{last.lux}</h2></div>

    {graph}

    </body>
    </html>
    """
    return html

# Render port
port = int(os.environ.get("PORT",10000))
app.run(host="0.0.0.0",port=port)
