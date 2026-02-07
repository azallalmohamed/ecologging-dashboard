import os
import requests
import sqlite3
import time
import threading
import pandas as pd
import plotly.express as px
from flask import Flask

# ===== CONFIG =====
DEVICE = "278910"
CLS_USER = os.environ.get("CLS_USER")
CLS_PASS = os.environ.get("CLS_PASS")

AUTH_URL = "https://account.groupcls.com/auth/realms/cls/protocol/openid-connect/token"
# API_URL  = "https://api.groupcls.com/telemetry/api/v1/retrieve-realtime"
API_URL  = "https://api.groupcls.com/telemetry/api/v1/retrieve-bulk"

CLS_TOKEN = None
CHECKPOINT = 0

# ===== DB =====
def db():
    return sqlite3.connect("database.db")

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

# ===== DECODE =====
def decode(hexdata):
    # garder seulement payload Arduino 16 bytes
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

        # filtre valeurs impossibles
        if temp>80 or hum>100 or pres<800 or pres>1200:
            return None

        return temp,hum,pres,lux
    except:
        return None

# ===== LOGIN CLS =====
def login_cls():
    global CLS_TOKEN

    data = {
        "grant_type":"password",
        "client_id":"api-telemetry",
        "username":CLS_USER,
        "password":CLS_PASS
    }

    r = requests.post(AUTH_URL,data=data)
    if r.status_code == 200:
        CLS_TOKEN = r.json()["access_token"]
        print("CLS connecté")
    else:
        print("Erreur login CLS")

# ===== GET DATA =====
def get_data():
    global CLS_TOKEN

    if not CLS_TOKEN:
        login_cls()
        return

    headers = {"Authorization":"Bearer "+CLS_TOKEN}

    body = {
        "pagination":{"first":50},
        "retrieveRawData":True,
        "retrieveMetadata":True,
        "deviceRefs":[DEVICE],

        # HISTORIQUE 30 JOURS
        "fromDatetime":"2026-01-01T00:00:00.000Z",
        "toDatetime":"2030-01-01T00:00:00.000Z",
        "datetimeFormat":"DATETIME"
    }

    r = requests.post(API_URL,json=body,headers=headers)

    if r.status_code != 200:
        print("API error", r.text)
        return

    data = r.json()

    if "contents" not in data:
        print("no data")
        return

    for m in data["contents"]:
        hexdata = m.get("rawData","")
        d = m.get("msgDatetime","")

        dec = decode(hexdata)
        if not dec:
            continue

        t,h,p,l = dec
        print("HISTORIQUE:",d,t,h,p,l)

        try:
            conn = db()
            cur = conn.cursor()
            cur.execute(
            "INSERT OR IGNORE INTO data(date,temp,hum,press,lux) VALUES(?,?,?,?,?)",
            (d,t,h,p,l))
            conn.commit()
            conn.close()
        except:
            pass


# ===== LOOP =====
def loop():
    while True:
        get_data()
        time.sleep(20)

threading.Thread(target=loop,daemon=True).start()

# ===== FLASK =====
app = Flask(__name__)

@app.route("/")
def home():

    conn = db()
    df = pd.read_sql_query("SELECT * FROM data ORDER BY date DESC LIMIT 500", conn)
    conn.close()

    if len(df)==0:
        return "<h1>🛰️ ECOLOGGING</h1><h2>En attente données satellite...</h2>"

    df = df.sort_values("date")

    fig = px.line(df,x="date",y=["temp","hum","press","lux"],
                  title="ECOLOGGING Satellite Station",
                  template="plotly_dark")

    graph = fig.to_html(full_html=False)

    html = f"""
    <html>
    <head>
    <meta http-equiv='refresh' content='30'>
    <style>
    body{{background:#020617;color:white;text-align:center;font-family:Arial}}
    h1{{color:#00ffe1}}
    </style>
    </head>
    <body>
    <h1>🛰️ ECOLOGGING Satellite Station</h1>
    <h3>Données satellite temps réel</h3>
    {graph}
    </body>
    </html>
    """
    return html

app.run(host="0.0.0.0", port=10000)
