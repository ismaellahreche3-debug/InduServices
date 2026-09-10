
import os, sqlite3, secrets
from flask import Flask, request, jsonify, session, send_from_directory, render_template
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "industria.db")
app = Flask(__name__, static_folder=".", static_url_path="")
app.secret_key = os.environ.get("SESSION_SECRET", secrets.token_hex(32))

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
      company TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS clients(
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
      email TEXT, phone TEXT, sector TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS quotes(
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, client TEXT NOT NULL,
      title TEXT NOT NULL, amount REAL DEFAULT 0, status TEXT DEFAULT 'Brouillon',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS interventions(
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, client TEXT NOT NULL,
      title TEXT NOT NULL, date TEXT, status TEXT DEFAULT 'À planifier'
    );
    CREATE TABLE IF NOT EXISTS documents(
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
      type TEXT, status TEXT DEFAULT 'À traiter'
    );
    """)
    if not c.execute("SELECT id FROM users LIMIT 1").fetchone():
        c.execute("INSERT INTO users(email,password,company) VALUES(?,?,?)",
                  ("demo@industria-services.fr", generate_password_hash("demo1234"), "INDUSTRIA DEMO"))
        uid=c.lastrowid
        c.executemany("INSERT INTO clients(user_id,name,email,phone,sector) VALUES(?,?,?,?,?)", [
            (uid,"Norgal","contact@norgal.fr","02 00 00 00 00","Logistique industrielle"),
            (uid,"Chevron","achats@chevron.fr","02 00 00 00 01","Énergie"),
            (uid,"Client Industrie","contact@client.fr","02 00 00 00 02","Maintenance")
        ])
        c.executemany("INSERT INTO quotes(user_id,client,title,amount,status) VALUES(?,?,?,?,?)", [
            (uid,"Norgal","Intervention quai — septembre",4850,"À valider"),
            (uid,"Chevron","Maintenance équipements",2300,"Envoyé")
        ])
        c.executemany("INSERT INTO interventions(user_id,client,title,date,status) VALUES(?,?,?,?,?)", [
            (uid,"Norgal","Opération de quai","2026-09-14","Planifiée"),
            (uid,"Chevron","Contrôle installation","2026-09-16","À planifier")
        ])
        c.executemany("INSERT INTO documents(user_id,name,type,status) VALUES(?,?,?,?)", [
            (uid,"Demande_Norgal.pdf","PDF","À traiter"),
            (uid,"Rapport_intervention_041.pdf","Rapport","Traité")
        ])
    c.commit(); c.close()

def auth():
    return session.get("uid")

@app.route("/")
def index(): return app.send_static_file("index.html")

@app.post("/api/login")
def login():
    data=request.json or {}
    c=db(); u=c.execute("SELECT * FROM users WHERE email=?", (data.get("email",""),)).fetchone(); c.close()
    if not u or not check_password_hash(u["password"], data.get("password","")):
        return jsonify(error="Identifiants incorrects"),401
    session["uid"]=u["id"]; session["company"]=u["company"]
    return jsonify(ok=True, company=u["company"])

@app.post("/api/logout")
def logout():
    session.clear(); return jsonify(ok=True)

@app.get("/api/me")
def me():
    if not auth(): return jsonify(authenticated=False)
    return jsonify(authenticated=True, company=session["company"])

@app.get("/api/dashboard")
def dashboard():
    uid=auth()
    if not uid:return jsonify(error="Non connecté"),401
    c=db()
    out={
      "clients":c.execute("SELECT COUNT(*) n FROM clients WHERE user_id=?",(uid,)).fetchone()["n"],
      "quotes":c.execute("SELECT COUNT(*) n FROM quotes WHERE user_id=?",(uid,)).fetchone()["n"],
      "pending_quotes":c.execute("SELECT COUNT(*) n FROM quotes WHERE user_id=? AND status='À valider'",(uid,)).fetchone()["n"],
      "interventions":c.execute("SELECT COUNT(*) n FROM interventions WHERE user_id=?",(uid,)).fetchone()["n"],
      "documents":c.execute("SELECT COUNT(*) n FROM documents WHERE user_id=? AND status!='Traité'",(uid,)).fetchone()["n"]
    }
    c.close(); return jsonify(out)

def list_rows(table):
    uid=auth()
    if not uid:return jsonify(error="Non connecté"),401
    c=db(); rows=c.execute(f"SELECT * FROM {table} WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall(); c.close()
    return jsonify([dict(r) for r in rows])

@app.get("/api/clients")
def clients(): return list_rows("clients")
@app.get("/api/quotes")
def quotes(): return list_rows("quotes")
@app.get("/api/interventions")
def interventions(): return list_rows("interventions")
@app.get("/api/documents")
def documents(): return list_rows("documents")

@app.post("/api/clients")
def add_client():
    uid=auth(); d=request.json or {}
    if not uid:return jsonify(error="Non connecté"),401
    if not d.get("name"):return jsonify(error="Nom requis"),400
    c=db(); c.execute("INSERT INTO clients(user_id,name,email,phone,sector) VALUES(?,?,?,?,?)",
      (uid,d["name"],d.get("email"),d.get("phone"),d.get("sector"))); c.commit(); c.close()
    return jsonify(ok=True)

@app.post("/api/quotes")
def add_quote():
    uid=auth(); d=request.json or {}
    if not uid:return jsonify(error="Non connecté"),401
    c=db(); c.execute("INSERT INTO quotes(user_id,client,title,amount,status) VALUES(?,?,?,?,?)",
      (uid,d.get("client",""),d.get("title","Nouveau devis"),float(d.get("amount",0)),d.get("status","Brouillon")))
    c.commit(); c.close(); return jsonify(ok=True)

@app.post("/api/interventions")
def add_intervention():
    uid=auth(); d=request.json or {}
    if not uid:return jsonify(error="Non connecté"),401
    c=db(); c.execute("INSERT INTO interventions(user_id,client,title,date,status) VALUES(?,?,?,?,?)",
      (uid,d.get("client",""),d.get("title","Nouvelle intervention"),d.get("date"),d.get("status","À planifier")))
    c.commit(); c.close(); return jsonify(ok=True)

@app.post("/api/ai")
def ai():
    uid=auth()
    if not uid:return jsonify(error="Non connecté"),401
    text=(request.json or {}).get("text","").strip()
    if not text:return jsonify(error="Texte requis"),400
    # Le branchement OpenAI est volontairement isolé côté serveur.
    # Ajoute OPENAI_API_KEY pour activer l'agent en production.
    if not os.environ.get("OPENAI_API_KEY"):
        return jsonify(answer="Mode démo : j'ai analysé la demande. Je peux préparer le client, le devis, les tâches et les prochaines actions dès que la clé IA est configurée.")
    try:
        from openai import OpenAI
        client=OpenAI()
        r=client.responses.create(
          model=os.environ.get("OPENAI_MODEL","gpt-6-astra"),
          instructions="Tu es l'agent administratif d'INDUSTRIA SERVICES, spécialisé dans les PME industrielles. Analyse les demandes clients, extrais les informations utiles, propose les actions et signale ce qui doit être validé par un humain.",
          input=text,
          reasoning={"effort":"low"}
        )
        return jsonify(answer=r.output_text)
    except Exception as e:
        return jsonify(answer="L'agent IA est temporairement indisponible. Vérifie la configuration API.", detail=str(e)),200

if __name__=="__main__":
    init()
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=True)
