import os
import sqlite3
from datetime import datetime
from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "induservices.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "induservices-demo-secret")

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        company TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        sector TEXT,
        contact TEXT,
        phone TEXT,
        email TEXT
    );
    CREATE TABLE IF NOT EXISTS quotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        client TEXT NOT NULL,
        title TEXT NOT NULL,
        amount REAL DEFAULT 0,
        status TEXT DEFAULT 'Brouillon',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS interventions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        client TEXT NOT NULL,
        title TEXT NOT NULL,
        date TEXT,
        status TEXT DEFAULT 'À planifier',
        description TEXT
    );
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        type TEXT,
        status TEXT DEFAULT 'À traiter'
    );
    """)

    user = db.execute("SELECT id FROM users LIMIT 1").fetchone()
    if not user:
        cur = db.execute(
            "INSERT INTO users(email,password,company) VALUES(?,?,?)",
            ("demo@induservices.fr", generate_password_hash("demo1234"), "INDU SERVICES DEMO")
        )
        uid = cur.lastrowid

        db.executemany(
            "INSERT INTO clients(user_id,name,sector,contact,phone,email) VALUES(?,?,?,?,?,?)",
            [
                (uid, "Norgal", "Logistique industrielle", "Service achats", "02 00 00 00 00", "achats@norgal.fr"),
                (uid, "Chevron", "Énergie", "Service maintenance", "02 00 00 00 01", "maintenance@chevron.fr"),
                (uid, "Lubrizol", "Chimie", "Exploitation", "02 00 00 00 02", "contact@lubrizol.fr"),
            ]
        )
        db.executemany(
            "INSERT INTO quotes(user_id,client,title,amount,status) VALUES(?,?,?,?,?)",
            [
                (uid, "Norgal", "Intervention quai — maintenance", 4850, "À valider"),
                (uid, "Chevron", "Contrôle et maintenance équipements", 2300, "Envoyé"),
                (uid, "Lubrizol", "Inspection installation", 7200, "Brouillon"),
            ]
        )
        db.executemany(
            "INSERT INTO interventions(user_id,client,title,date,status,description) VALUES(?,?,?,?,?,?)",
            [
                (uid, "Norgal", "Opération de quai", "2026-09-14", "Planifiée", "Préparation et contrôle avant intervention."),
                (uid, "Chevron", "Contrôle installation", "2026-09-16", "À planifier", "Contrôle terrain et rapport."),
                (uid, "Lubrizol", "Inspection équipements", "2026-09-18", "Planifiée", "Inspection préventive."),
            ]
        )
        db.executemany(
            "INSERT INTO documents(user_id,name,type,status) VALUES(?,?,?,?)",
            [
                (uid, "Demande_Norgal.pdf", "Demande client", "À traiter"),
                (uid, "Rapport_intervention_041.pdf", "Rapport", "Traité"),
                (uid, "Bon_commande_Chevron.pdf", "Bon de commande", "À traiter"),
            ]
        )
    db.commit()
    db.close()

def uid():
    return session.get("uid")

@app.get("/")
def home():
    return send_from_directory(BASE, "index.html")

@app.get("/<path:path>")
def static_files(path):
    if path == "index.html":
        return send_from_directory(BASE, path)
    full = os.path.join(BASE, path)
    if os.path.isfile(full):
        return send_from_directory(BASE, path)
    return send_from_directory(BASE, "index.html")

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    db.close()
    if not user or not check_password_hash(user["password"], password):
        return jsonify(error="Adresse e-mail ou mot de passe incorrect."), 401
    session["uid"] = user["id"]
    session["company"] = user["company"]
    return jsonify(ok=True, company=user["company"])

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/me")
def me():
    if not uid():
        return jsonify(authenticated=False)
    return jsonify(authenticated=True, company=session.get("company"))

@app.get("/api/dashboard")
def dashboard():
    if not uid():
        return jsonify(error="Non connecté"), 401
    db = get_db()
    clients = db.execute("SELECT COUNT(*) n FROM clients WHERE user_id=?", (uid(),)).fetchone()["n"]
    quotes = db.execute("SELECT COUNT(*) n FROM quotes WHERE user_id=?", (uid(),)).fetchone()["n"]
    pending = db.execute("SELECT COUNT(*) n FROM quotes WHERE user_id=? AND status='À valider'", (uid(),)).fetchone()["n"]
    interventions = db.execute("SELECT COUNT(*) n FROM interventions WHERE user_id=?", (uid(),)).fetchone()["n"]
    docs = db.execute("SELECT COUNT(*) n FROM documents WHERE user_id=? AND status!='Traité'", (uid(),)).fetchone()["n"]
    revenue = db.execute("SELECT COALESCE(SUM(amount),0) total FROM quotes WHERE user_id=? AND status IN ('Envoyé','Accepté')", (uid(),)).fetchone()["total"]
    next_interventions = db.execute(
        "SELECT * FROM interventions WHERE user_id=? ORDER BY date LIMIT 5", (uid(),)
    ).fetchall()
    db.close()
    return jsonify(
        clients=clients, quotes=quotes, pending=pending, interventions=interventions,
        docs=docs, revenue=round(revenue, 2),
        next_interventions=[dict(x) for x in next_interventions]
    )

def rows(table):
    if not uid():
        return jsonify(error="Non connecté"), 401
    db = get_db()
    data = db.execute(f"SELECT * FROM {table} WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall()
    db.close()
    return jsonify([dict(x) for x in data])

@app.get("/api/clients")
def clients(): return rows("clients")

@app.get("/api/quotes")
def quotes(): return rows("quotes")

@app.get("/api/interventions")
def interventions(): return rows("interventions")

@app.get("/api/documents")
def documents(): return rows("documents")

@app.post("/api/clients")
def add_client():
    if not uid(): return jsonify(error="Non connecté"), 401
    d = request.get_json(silent=True) or {}
    if not d.get("name"): return jsonify(error="Nom du client requis."), 400
    db = get_db()
    db.execute(
        "INSERT INTO clients(user_id,name,sector,contact,phone,email) VALUES(?,?,?,?,?,?)",
        (uid(), d["name"], d.get("sector",""), d.get("contact",""), d.get("phone",""), d.get("email",""))
    )
    db.commit(); db.close()
    return jsonify(ok=True)

@app.post("/api/quotes")
def add_quote():
    if not uid(): return jsonify(error="Non connecté"), 401
    d = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        "INSERT INTO quotes(user_id,client,title,amount,status) VALUES(?,?,?,?,?)",
        (uid(), d.get("client",""), d.get("title","Nouveau devis"), float(d.get("amount",0) or 0), d.get("status","Brouillon"))
    )
    db.commit(); db.close()
    return jsonify(ok=True)

@app.post("/api/interventions")
def add_intervention():
    if not uid(): return jsonify(error="Non connecté"), 401
    d = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        "INSERT INTO interventions(user_id,client,title,date,status,description) VALUES(?,?,?,?,?,?)",
        (uid(), d.get("client",""), d.get("title","Nouvelle intervention"), d.get("date",""), d.get("status","À planifier"), d.get("description",""))
    )
    db.commit(); db.close()
    return jsonify(ok=True)

@app.post("/api/ai")
def ai():
    if not uid(): return jsonify(error="Non connecté"), 401
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text: return jsonify(error="Écris une demande."), 400

    # Démo immédiatement exploitable. L'API OpenAI pourra être branchée ensuite.
    answer = (
        "Analyse terminée.\n\n"
        "• Type détecté : demande industrielle\n"
        "• Client : à confirmer\n"
        "• Priorité : normale\n"
        "• Action proposée : préparer un devis puis planifier l'intervention\n"
        "• Validation humaine : requise avant envoi au client\n\n"
        "Demande reçue : " + text[:500]
    )
    return jsonify(answer=answer)

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
