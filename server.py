import os, re, sqlite3, json
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'induservices.db')
app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'induservices-demo-secret-change-me')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

DEMO_MAIL = """Objet : Demande de remplacement pompe 24

Bonjour,

Nous aimerions que vous puissiez nous changer la pompe 24 dans l’unité détergent demain s’il vous plaît.

Serait-il possible d’avoir un devis s’il vous plaît ?

Merci d’avance.

Cordialement,

Service maintenance
Norgal"""


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE,password TEXT,company TEXT);
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,name TEXT,sector TEXT,contact TEXT,phone TEXT,email TEXT);
    CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,client TEXT,subject TEXT,raw_email TEXT,category TEXT,priority TEXT,equipment TEXT,location TEXT,requested_date TEXT,quote_required INTEGER,intervention_required INTEGER,status TEXT,tags TEXT,missing_info TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_id INTEGER,title TEXT,status TEXT,priority TEXT);
    CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_id INTEGER,client TEXT,title TEXT,amount REAL,status TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS interventions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_id INTEGER,client TEXT,title TEXT,date TEXT,status TEXT,description TEXT,checklist TEXT,report TEXT);
    CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_id INTEGER,name TEXT,type TEXT,status TEXT);
    CREATE TABLE IF NOT EXISTS activities(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_id INTEGER,label TEXT,detail TEXT,created_at TEXT);
    ''')
    u = c.execute('SELECT id FROM users LIMIT 1').fetchone()
    if not u:
        cur = c.execute('INSERT INTO users(email,password,company) VALUES(?,?,?)', ('demo@induservices.fr', generate_password_hash('demo1234'), 'INDU SERVICES DEMO'))
        uid = cur.lastrowid
        c.executemany('INSERT INTO clients(user_id,name,sector,contact,phone,email) VALUES(?,?,?,?,?,?)', [
            (uid,'Norgal','Logistique industrielle','Service maintenance','02 00 00 00 00','maintenance@norgal.fr'),
            (uid,'Chevron','Énergie','Service maintenance','02 00 00 00 01','maintenance@chevron.fr'),
            (uid,'Lubrizol','Chimie','Exploitation','02 00 00 00 02','exploitation@lubrizol.fr')
        ])
        # A small realistic demo dataset for a presentation.
        a = classify(DEMO_MAIL)
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        cur = c.execute('''INSERT INTO requests(user_id,client,subject,raw_email,category,priority,equipment,location,requested_date,quote_required,intervention_required,status,tags,missing_info,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (uid,a['client'],a['subject'],DEMO_MAIL,a['category'],a['priority'],a['equipment'],a['location'],a['requested_date'],1,1,'À traiter',json.dumps(a['tags'],ensure_ascii=False),json.dumps(a['missing_info'],ensure_ascii=False),now))
        rid = cur.lastrowid
        for action in a['actions']:
            c.execute('INSERT INTO tasks(user_id,request_id,title,status,priority) VALUES(?,?,?,?,?)',(uid,rid,action,'À faire',a['priority']))
        c.execute('INSERT INTO documents(user_id,request_id,name,type,status) VALUES(?,?,?,?,?)',(uid,rid,f'Demande_Norgal_{rid}.eml','Demande client','Analysé'))
        c.execute('INSERT INTO activities(user_id,request_id,label,detail,created_at) VALUES(?,?,?,?,?)',(uid,rid,'Mail reçu','Demande Norgal détectée et classée automatiquement.',now))
        c.execute('INSERT INTO quotes(user_id,request_id,client,title,amount,status,created_at) VALUES(?,?,?,?,?,?,?)',(uid,rid,'Norgal','Remplacement Pompe 24',0,'À compléter',now))
        c.execute('INSERT INTO interventions(user_id,request_id,client,title,date,status,description,checklist,report) VALUES(?,?,?,?,?,?,?,?,?)',(uid,rid,'Norgal','Remplacement Pompe 24',a['requested_date'],'À confirmer','Intervention issue de la demande client.',json.dumps(['Sécurité / EPI','Vérifier référence et disponibilité','Consignation si nécessaire','Dépose / remplacement','Essai et contrôle','Photos avant / après','Validation client'],ensure_ascii=False),''))
    c.commit(); c.close()


def uid(): return session.get('uid')
def auth(): return bool(uid())

def safe_json(s, default):
    try: return json.loads(s) if s else default
    except Exception: return default

def tomorrow_label():
    return (datetime.now() + timedelta(days=1)).strftime('%d/%m/%Y')

def classify(text):
    raw = text.strip(); low = raw.lower()
    client = 'Norgal' if 'norgal' in low else ('Chevron' if 'chevron' in low else ('Lubrizol' if 'lubrizol' in low else 'À confirmer'))
    equipment = 'Pompe 24' if re.search(r'pompe\s*24', low) else 'À identifier'
    location = 'Unité Détergent' if ('détergent' in low or 'detergent' in low) else 'À préciser'
    quote = any(x in low for x in ['devis','prix','tarif','chiffrage'])
    intervention = any(x in low for x in ['changer','change','remplacer','remplacement','intervention','maintenance','réparer','reparer','dépannage','depannage'])
    tomorrow = 'demain' in low
    urgent = tomorrow or any(x in low for x in ['urgent','urgence','au plus vite','asap','prioritaire'])
    category = 'Maintenance / remplacement' if intervention else 'Demande client'
    priority = 'Haute' if urgent else 'Normale'
    subject = f'{client} — {"Remplacement " + equipment if equipment != "À identifier" else "Demande client"}'
    missing = []
    if equipment == 'À identifier': missing.append('Référence exacte du matériel')
    if quote: missing += ['Prix / disponibilité du matériel','Temps de main-d’œuvre']
    if not tomorrow and not re.search(r'\b\d{1,2}[/-]\d{1,2}\b', low): missing.append('Date souhaitée')
    tags = ['DEMANDE_CLIENT']
    if quote: tags.append('DEVIS')
    if intervention: tags.append('INTERVENTION')
    if intervention: tags.append('MAINTENANCE')
    if equipment != 'À identifier': tags.append('POMPE')
    if client != 'À confirmer': tags.append(client.upper())
    if urgent: tags.append('PRIORITÉ_HAUTE')
    actions = []
    if quote: actions.append('Préparer un devis brouillon sans inventer le prix')
    if intervention: actions.append('Créer une intervention provisoire à confirmer')
    if missing: actions.append('Compléter les informations manquantes avant validation')
    if not actions: actions.append('Qualifier la demande et décider de la suite')
    explanation = 'Classification basée uniquement sur le contenu reçu. Les informations absentes ne sont pas inventées.'
    if tomorrow: explanation += ' La mention « demain » déclenche une priorité haute et une intervention à confirmer.'
    return dict(client=client, subject=subject, category=category, priority=priority, equipment=equipment, location=location,
                requested_date=tomorrow_label() if tomorrow else '', quote_required=quote, intervention_required=intervention,
                status='À traiter', tags=tags, missing_info=missing, actions=actions, explanation=explanation)

def get_request(rid):
    c = db(); r = c.execute('SELECT * FROM requests WHERE id=? AND user_id=?',(rid,uid())).fetchone(); c.close(); return r

def activity(label, detail='', request_id=None):
    c=db(); c.execute('INSERT INTO activities(user_id,request_id,label,detail,created_at) VALUES(?,?,?,?,?)',(uid(),request_id,label,detail,datetime.now().strftime('%Y-%m-%d %H:%M'))); c.commit(); c.close()

@app.get('/')
def home(): return send_from_directory(BASE,'index.html')
@app.get('/<path:path>')
def serve_static(path):
    full=os.path.join(BASE,path)
    if os.path.isfile(full): return send_from_directory(BASE,path)
    return send_from_directory(BASE,'index.html')

@app.post('/api/login')
def login():
    d=request.get_json(silent=True) or {}; email=d.get('email','').strip(); password=d.get('password','')
    c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone(); c.close()
    if not u or not check_password_hash(u['password'],password): return jsonify(error='Adresse e-mail ou mot de passe incorrect.'),401
    session['uid']=u['id']; session['company']=u['company']; return jsonify(ok=True,company=u['company'])
@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)
@app.get('/api/me')
def me(): return jsonify(authenticated=auth(),company=session.get('company',''))

@app.get('/api/dashboard')
def dashboard():
    if not auth(): return jsonify(error='Non connecté'),401
    c=db(); U=uid()
    vals={
        'clients':c.execute('SELECT COUNT(*) n FROM clients WHERE user_id=?',(U,)).fetchone()['n'],
        'requests':c.execute('SELECT COUNT(*) n FROM requests WHERE user_id=?',(U,)).fetchone()['n'],
        'pending':c.execute("SELECT COUNT(*) n FROM requests WHERE user_id=? AND status IN ('À traiter','À valider')",(U,)).fetchone()['n'],
        'interventions':c.execute('SELECT COUNT(*) n FROM interventions WHERE user_id=?',(U,)).fetchone()['n'],
        'quotes':c.execute('SELECT COUNT(*) n FROM quotes WHERE user_id=?',(U,)).fetchone()['n'],
        'tasks':c.execute("SELECT COUNT(*) n FROM tasks WHERE user_id=? AND status!='Terminée'",(U,)).fetchone()['n'],
        'revenue':round(c.execute("SELECT COALESCE(SUM(amount),0) n FROM quotes WHERE user_id=? AND status IN ('Envoyé','Accepté')",(U,)).fetchone()['n'],2),
        'recent':[dict(x) for x in c.execute('SELECT id,client,subject,priority,status,created_at FROM requests WHERE user_id=? ORDER BY id DESC LIMIT 6',(U,)).fetchall()],
        'activities':[dict(x) for x in c.execute('SELECT * FROM activities WHERE user_id=? ORDER BY id DESC LIMIT 8',(U,)).fetchall()]
    }
    c.close(); return jsonify(**vals)

@app.get('/api/requests')
def requests_list():
    if not auth(): return jsonify(error='Non connecté'),401
    c=db(); rows=c.execute('SELECT * FROM requests WHERE user_id=? ORDER BY id DESC',(uid(),)).fetchall(); c.close(); out=[]
    for r in rows:
        d=dict(r); d['tags']=safe_json(d['tags'],[]); d['missing_info']=safe_json(d['missing_info'],[]); out.append(d)
    return jsonify(out)

@app.post('/api/requests/analyze')
def analyze():
    if not auth(): return jsonify(error='Non connecté'),401
    text=((request.get_json(silent=True) or {}).get('text') or '').strip()
    if not text:return jsonify(error='Colle un mail à analyser.'),400
    a=classify(text); now=datetime.now().strftime('%Y-%m-%d %H:%M'); c=db()
    cur=c.execute('''INSERT INTO requests(user_id,client,subject,raw_email,category,priority,equipment,location,requested_date,quote_required,intervention_required,status,tags,missing_info,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (uid(),a['client'],a['subject'],text,a['category'],a['priority'],a['equipment'],a['location'],a['requested_date'],int(a['quote_required']),int(a['intervention_required']),'À traiter',json.dumps(a['tags'],ensure_ascii=False),json.dumps(a['missing_info'],ensure_ascii=False),now))
    rid=cur.lastrowid
    for action in a['actions']: c.execute('INSERT INTO tasks(user_id,request_id,title,status,priority) VALUES(?,?,?,?,?)',(uid(),rid,action,'À faire',a['priority']))
    c.execute('INSERT INTO documents(user_id,request_id,name,type,status) VALUES(?,?,?,?,?)',(uid(),rid,f'Demande_{a["client"]}_{rid}.eml','Demande client','Analysé'))
    c.execute('INSERT INTO activities(user_id,request_id,label,detail,created_at) VALUES(?,?,?,?,?)',(uid(),rid,'Demande classée','Le mail a été analysé et les actions proposées ont été générées.',now))
    c.commit(); c.close(); return jsonify(id=rid,analysis=a)

@app.post('/api/demo/incoming')
def demo_incoming():
    if not auth(): return jsonify(error='Non connecté'),401
    # Demo action: simulate the arrival of a new email in the company inbox.
    text=DEMO_MAIL
    a=classify(text); now=datetime.now().strftime('%Y-%m-%d %H:%M'); c=db()
    cur=c.execute('''INSERT INTO requests(user_id,client,subject,raw_email,category,priority,equipment,location,requested_date,quote_required,intervention_required,status,tags,missing_info,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (uid(),a['client'],a['subject'],text,a['category'],a['priority'],a['equipment'],a['location'],a['requested_date'],1,1,'À traiter',json.dumps(a['tags'],ensure_ascii=False),json.dumps(a['missing_info'],ensure_ascii=False),now))
    rid=cur.lastrowid
    for action in a['actions']: c.execute('INSERT INTO tasks(user_id,request_id,title,status,priority) VALUES(?,?,?,?,?)',(uid(),rid,action,'À faire',a['priority']))
    c.execute('INSERT INTO documents(user_id,request_id,name,type,status) VALUES(?,?,?,?,?)',(uid(),rid,f'Demande_{a["client"]}_{rid}.eml','Demande client','Analysé'))
    c.execute('INSERT INTO activities(user_id,request_id,label,detail,created_at) VALUES(?,?,?,?,?)',(uid(),rid,'Nouveau mail reçu','Le connecteur e-mail est simulé pour la démo : le mail a été classé automatiquement.',now))
    c.commit(); c.close(); return jsonify(id=rid,analysis=a)

@app.get('/api/requests/<int:rid>')
def request_detail(rid):
    if not auth(): return jsonify(error='Non connecté'),401
    r=get_request(rid)
    if not r:return jsonify(error='Dossier introuvable'),404
    c=db(); tasks=[dict(x) for x in c.execute('SELECT * FROM tasks WHERE request_id=? AND user_id=? ORDER BY id',(rid,uid())).fetchall()]; quotes=[dict(x) for x in c.execute('SELECT * FROM quotes WHERE request_id=? AND user_id=?',(rid,uid())).fetchall()]; ints=[dict(x) for x in c.execute('SELECT * FROM interventions WHERE request_id=? AND user_id=?',(rid,uid())).fetchall()]; acts=[dict(x) for x in c.execute('SELECT * FROM activities WHERE request_id=? AND user_id=? ORDER BY id DESC',(rid,uid())).fetchall()]; c.close()
    d=dict(r); d['tags']=safe_json(d['tags'],[]); d['missing_info']=safe_json(d['missing_info'],[]); d['tasks']=tasks; d['quotes']=quotes; d['interventions']=ints; d['activities']=acts; a=classify(d['raw_email']); d['actions']=a['actions']; d['explanation']=a['explanation']; return jsonify(d)

@app.post('/api/requests/<int:rid>/execute')
def execute(rid):
    if not auth(): return jsonify(error='Non connecté'),401
    r=get_request(rid)
    if not r:return jsonify(error='Dossier introuvable'),404
    c=db(); U=uid(); created=[]; now=datetime.now().strftime('%Y-%m-%d %H:%M')
    if r['quote_required'] and not c.execute('SELECT id FROM quotes WHERE request_id=? AND user_id=?',(rid,U)).fetchone():
        c.execute('INSERT INTO quotes(user_id,request_id,client,title,amount,status,created_at) VALUES(?,?,?,?,?,?,?)',(U,rid,r['client'],r['subject'],0,'À compléter',now)); created.append('devis')
    if r['intervention_required'] and not c.execute('SELECT id FROM interventions WHERE request_id=? AND user_id=?',(rid,U)).fetchone():
        checklist=json.dumps(['Sécurité / EPI','Vérifier référence et disponibilité du matériel','Consignation si nécessaire','Dépose / remplacement','Essai et contrôle','Photos avant / après','Signature / validation client'],ensure_ascii=False)
        c.execute('INSERT INTO interventions(user_id,request_id,client,title,date,status,description,checklist,report) VALUES(?,?,?,?,?,?,?,?,?)',(U,rid,r['client'],r['subject'],r['requested_date'],'À confirmer',f'Intervention issue de la demande #{rid}.',checklist,'')); created.append('intervention')
    c.execute("UPDATE requests SET status='Actions créées' WHERE id=? AND user_id=?",(rid,U)); c.execute("UPDATE tasks SET status='Créée' WHERE request_id=? AND user_id=? AND status='À faire'",(rid,U)); c.execute('INSERT INTO activities(user_id,request_id,label,detail,created_at) VALUES(?,?,?,?,?)',(U,rid,'Actions créées','Devis et intervention préparés pour validation humaine.',now)); c.commit(); c.close(); return jsonify(ok=True,created=created)

@app.post('/api/requests/<int:rid>/reply')
def reply(rid):
    if not auth(): return jsonify(error='Non connecté'),401
    r=get_request(rid)
    if not r:return jsonify(error='Dossier introuvable'),404
    text=f"Bonjour,\n\nNous avons bien reçu votre demande concernant {r['equipment']} dans {r['location']}.\n\nNous préparons le chiffrage. Afin de finaliser le devis, nous devons confirmer les informations techniques et la disponibilité du matériel.\n\nNous revenons vers vous dès validation.\n\nCordialement,\nINDU SERVICES"
    return jsonify(draft=text,warning='Brouillon uniquement : aucun mail n’est envoyé automatiquement.')

@app.get('/api/clients')
def clients():
    if not auth():return jsonify(error='Non connecté'),401
    c=db(); x=[dict(r) for r in c.execute('SELECT * FROM clients WHERE user_id=? ORDER BY name',(uid(),)).fetchall()]; c.close(); return jsonify(x)
@app.get('/api/quotes')
def quotes():
    if not auth():return jsonify(error='Non connecté'),401
    c=db(); x=[dict(r) for r in c.execute('SELECT * FROM quotes WHERE user_id=? ORDER BY id DESC',(uid(),)).fetchall()]; c.close(); return jsonify(x)
@app.get('/api/interventions')
def interventions():
    if not auth():return jsonify(error='Non connecté'),401
    c=db(); x=[dict(r) for r in c.execute('SELECT * FROM interventions WHERE user_id=? ORDER BY CASE WHEN date IS NULL OR date="" THEN 1 ELSE 0 END,date,id DESC',(uid(),)).fetchall()]; c.close()
    for r in x:r['checklist']=safe_json(r['checklist'],[])
    return jsonify(x)
@app.get('/api/tasks')
def tasks():
    if not auth():return jsonify(error='Non connecté'),401
    c=db(); x=[dict(r) for r in c.execute('SELECT * FROM tasks WHERE user_id=? ORDER BY CASE status WHEN "À faire" THEN 0 ELSE 1 END,id DESC',(uid(),)).fetchall()]; c.close(); return jsonify(x)
@app.get('/api/documents')
def documents():
    if not auth():return jsonify(error='Non connecté'),401
    c=db(); x=[dict(r) for r in c.execute('SELECT * FROM documents WHERE user_id=? ORDER BY id DESC',(uid(),)).fetchall()]; c.close(); return jsonify(x)
@app.get('/api/activities')
def activities():
    if not auth():return jsonify(error='Non connecté'),401
    c=db(); x=[dict(r) for r in c.execute('SELECT * FROM activities WHERE user_id=? ORDER BY id DESC LIMIT 30',(uid(),)).fetchall()]; c.close(); return jsonify(x)

@app.post('/api/interventions/<int:iid>/complete')
def complete_intervention(iid):
    if not auth():return jsonify(error='Non connecté'),401
    d=request.get_json(silent=True) or {}; report=d.get('report','').strip(); c=db(); row=c.execute('SELECT * FROM interventions WHERE id=? AND user_id=?',(iid,uid())).fetchone()
    if not row:c.close(); return jsonify(error='Intervention introuvable'),404
    c.execute("UPDATE interventions SET status='Terminée',report=? WHERE id=? AND user_id=?",(report,iid,uid())); c.execute("UPDATE tasks SET status='Terminée' WHERE user_id=? AND request_id=?",(uid(),row['request_id'])); c.execute('INSERT INTO activities(user_id,request_id,label,detail,created_at) VALUES(?,?,?,?,?)',(uid(),row['request_id'],'Intervention clôturée','Compte-rendu enregistré et tâches associées clôturées.',datetime.now().strftime('%Y-%m-%d %H:%M'))); c.commit(); c.close(); return jsonify(ok=True)

@app.post('/api/reset-demo')
def reset_demo():
    if not auth():return jsonify(error='Non connecté'),401
    c=db(); U=uid()
    for t in ['tasks','quotes','interventions','requests','documents','activities']: c.execute(f'DELETE FROM {t} WHERE user_id=?',(U,))
    c.commit(); c.close(); return jsonify(ok=True)

init_db()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
