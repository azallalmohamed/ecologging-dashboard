from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "<h1>🛰️ ECOLOGGING Satellite Station</h1><h2>Serveur actif</h2>"

app.run(host="0.0.0.0", port=10000)
