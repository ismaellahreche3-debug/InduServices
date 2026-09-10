import os, sqlite3, json, re
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

BASE=os.path.dirname(os.path.abspath(__file__)); DB=os.path.join(BASE,'induservices.db')
app=Flask(__name__); app.secret_key=os.getenv('SESSION_SECRET','induservices-demo-secret-change-me')

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE,password TEXT,company TEXT);
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,name TEXT,sector TEXT,contact TEXT,email TEXT,phone TEXT);
    CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,client TEXT,subject TEXT,raw_email TEXT,category TEXT,priority TEXT,equipment TEXT,location TEXT,requested_date TEXT,quote_required INTEGER,intervention_required INTEGER,status TEXT,tags TEXT,missing_info TEXT,explanation TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_id INTEGER,client TEXT,title TEXT,amount REAL,status TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS interventions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_id INTEGER,client TEXT,title TEXT,date TEXT,status TEXT,description TEXT,checklist TEXT,report TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_id INTEGER,title TEXT,status TEXT,priority TEXT);
    CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,request_id INTEGER,name TEXT,type TEXT,status TEXT);
    ''')
    if not c.execute('SELECT id FROM users LIMIT 1').fetchone():
        u=c.execute('INSERT INTO users(email,password,company) VALUES(?,?,?)',('demo@induservices.fr',generate_password_hash('demo1234'),'INDU SERVICES DEMO')).lastrowid
        c.executemany('INSERT INTO clients(user_id,name,sector,contact,email,phone) VALUES(?,?,?,?,?,?)',[(u,'Norgal','Logistique industrielle','Service achats','achats@norgal.fr','02 00 00 00 00'),(u,'Chevron','Énergie','Maintenance','maintenance@chevron.fr','02 00 00 00 01'),(u,'Lubrizol','Chimie','Exploitation','contact@lubrizol.fr','02 00 00 00 02')])
        c.execute('INSERT INTO requests(user_id,client,subject,raw_email,category,priority,equipment,location,requested_date,quote_required,intervention_required,status,tags,missing_info,explanation,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(u,'Norgal','Remplacement Pompe 24','Bonjour, nous aimerions que vous puissiez nous changer la pompe 24 dans l’unité détergeant demain s’il vous plaît. Serait-il possible d’avoir un devis s’il vous plaît?','Maintenance / remplacement','Haute','Pompe 24','Unité Détergent','Demain',1,1,'À traiter','#DEMANDE_CLIENT #DEVIS #INTERVENTION #MAINTENANCE #POMPE #NORGAL #PRIORITÉ_HAUTE','Référence exacte de la pompe; prix de la pompe; disponibilité; temps de main-d’œuvre','Analyse fondée sur le contenu reçu. Les informations absentes ne sont pas inventées. Une validation humaine est requise avant envoi ou engagement. ',datetime.now().isoformat(timespec='minutes')))
        rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        for title,pri in [('Préparer le devis', 'Haute'),('Vérifier référence/prix/disponibilité de la pompe','Haute'),('Préparer l’intervention terrain','Haute')]: c.execute('INSERT INTO tasks(user_id,request_id,title,status,priority) VALUES(?,?,?,?,?)',(u,rid,title,'À faire',pri))
    c.commit(); c.close()

def uid(): return session.get('uid')
def auth(): return bool(uid())
def rows(q,args=()):
    c=db(); r=[dict(x) for x in c.execute(q,args).fetchall()]; c.close(); return r

def analyze(text):
    t=text.lower(); client='Norgal' if 'norgal' in t else 'À confirmer'; equipment='Pompe 24' if 'pompe 24' in t else ''; location='Unité Détergent' if ('détergent' in t or 'detergent' in t) else ''
    quote=any(x in t for x in ['devis','prix','tarif','chiffrage']); intervention=any(x in t for x in ['changer','changez','remplacer','remplacement','intervention','maintenance','réparer','reparer']); tomorrow='demain' in t; urgent=tomorrow or any(x in t for x in ['urgent','urgence','prioritaire'])
    category='Maintenance / remplacement' if intervention else 'Demande client'; priority='Haute' if urgent else 'Normale'; date='Demain' if tomorrow else 'À confirmer'
    tags=['#DEMANDE_CLIENT'];
    if quote: tags+=['#DEVIS']
    if intervention: tags+=['#INTERVENTION','#MAINTENANCE']
    if equipment: tags+=['#POMPE']
    if client!='À confirmer': tags+=['#NORGAL']
    if urgent: tags+=['#PRIORITÉ_HAUTE']
    missing=[]
    if not equipment: missing.append('Référence exacte de l’équipement')
    if quote: missing += ['Prix de la pièce / matériel','Disponibilité','Temps de main-d’œuvre']
    if date=='À confirmer': missing.append('Date/heure souhaitée')
    return dict(client=client,category=category,priority=priority,equipment=equipment,location=location,requested_date=date,quote_required=int(quote),intervention_required=int(intervention),tags=' '.join(tags),missing_info='; '.join(missing),explanation='Analyse fondée uniquement sur le contenu reçu. Les données absentes ne sont pas inventées. Validation humaine avant envoi au client ou engagement de dépenses.')

@app.get('/')
def home(): return send_from_directory(BASE,'index.html')
@app.get('/<path:p>')
def static(p):
    f=os.path.join(BASE,p); return send_from_directory(BASE,p) if os.path.isfile(f) else send_from_directory(BASE,'index.html')
@app.post('/api/login')
def login():
    d=request.get_json() or {}; c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(d.get('email','').strip(),)).fetchone(); c.close()
    if not u or not check_password_hash(u['password'],d.get('password','')): return jsonify(error='Identifiants incorrects.'),401
    session['uid']=u['id']; session['company']=u['company']; return jsonify(ok=True,company=u['company'])
@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)
@app.get('/api/me')
def me(): return jsonify(authenticated=auth(),company=session.get('company',''))
@app.get('/api/dashboard')
def dashboard():
    if not auth(): return jsonify(error='Non connecté'),401
    c=db(); q=lambda s:c.execute(s,(uid(),)).fetchone()[0]
    data={'clients':q('SELECT count(*) FROM clients WHERE user_id=?'),'requests':q('SELECT count(*) FROM requests WHERE user_id=?'),'pending':q("SELECT count(*) FROM requests WHERE user_id=? AND status IN ('À traiter','À valider')"),'quotes':q('SELECT count(*) FROM quotes WHERE user_id=?'),'interventions':q('SELECT count(*) FROM interventions WHERE user_id=?'),'tasks':q("SELECT count(*) FROM tasks WHERE user_id=? AND status!='Terminée'"),'revenue':c.execute("SELECT coalesce(sum(amount),0) FROM quotes WHERE user_id=? AND status IN ('Envoyé','Accepté')",(uid(),)).fetchone()[0]}
    data['next_interventions']=[dict(x) for x in c.execute('SELECT * FROM interventions WHERE user_id=? ORDER BY date LIMIT 6',(uid(),)).fetchall()]; c.close(); return jsonify(**data)

@app.get('/api/requests')
def get_requests():
    if not auth(): return jsonify(error='Non connecté'),401
    return jsonify(rows('SELECT * FROM requests WHERE user_id=? ORDER BY id DESC',(uid(),)))
@app.post('/api/requests/analyze')
def create_request():
    if not auth(): return jsonify(error='Non connecté'),401
    d=request.get_json() or {}; text=(d.get('email') or d.get('text') or '').strip()
    if not text: return jsonify(error='Colle un e-mail.'),400
    a=analyze(text); subject=d.get('subject') or ('Remplacement '+a['equipment'] if a['equipment'] else 'Nouvelle demande client')
    c=db(); cur=c.execute('INSERT INTO requests(user_id,client,subject,raw_email,category,priority,equipment,location,requested_date,quote_required,intervention_required,status,tags,missing_info,explanation,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid(),a['client'],subject,text,a['category'],a['priority'],a['equipment'],a['location'],a['requested_date'],a['quote_required'],a['intervention_required'],'À traiter',a['tags'],a['missing_info'],a['explanation'],datetime.now().isoformat(timespec='minutes'))); rid=cur.lastrowid
    tasks=[]
    if a['quote_required']: tasks.append(('Préparer le devis','Haute'))
    if a['missing_info']: tasks.append(('Compléter les informations manquantes','Haute'))
    if a['intervention_required']: tasks.append(('Préparer l’intervention terrain','Haute' if a['priority']=='Haute' else 'Normale'))
    for title,pri in tasks:c.execute('INSERT INTO tasks(user_id,request_id,title,status,priority) VALUES(?,?,?,?,?)',(uid(),rid,title,'À faire',pri))
    c.execute('INSERT INTO documents(user_id,request_id,name,type,status) VALUES(?,?,?,?,?)',(uid(),rid,'E-mail client — '+subject,'Demande client','Classé'))
    c.commit(); r=dict(c.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()); c.close(); return jsonify(request=r)
@app.post('/api/requests/<int:rid>/validate')
def validate(rid):
    if not auth(): return jsonify(error='Non connecté'),401
    c=db(); r=c.execute('SELECT * FROM requests WHERE id=? AND user_id=?',(rid,uid())).fetchone()
    if not r:return jsonify(error='Dossier introuvable'),404
    if r['quote_required'] and not c.execute('SELECT id FROM quotes WHERE request_id=?',(rid,)).fetchone(): c.execute('INSERT INTO quotes(user_id,request_id,client,title,amount,status,created_at) VALUES(?,?,?,?,?,?,?)',(uid(),rid,r['client'],r['subject'],0,'À compléter',datetime.now().isoformat(timespec='minutes')))
    if r['intervention_required'] and not c.execute('SELECT id FROM interventions WHERE request_id=?',(rid,)).fetchone(): c.execute('INSERT INTO interventions(user_id,request_id,client,title,date,status,description,checklist,report,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(),rid,r['client'],r['subject'],r['requested_date'],'À confirmer','Créée depuis la demande client. Aucune date définitive sans validation.','[]','',datetime.now().isoformat(timespec='minutes')))
    c.execute("UPDATE requests SET status='Actions créées' WHERE id=?",(rid,)); c.execute("UPDATE tasks SET status='Créée' WHERE request_id=? AND user_id=?",(rid,uid())); c.commit(); c.close(); return jsonify(ok=True)

def simple(table,order='id DESC'):
    if not auth(): return jsonify(error='Non connecté'),401
    return jsonify(rows(f'SELECT * FROM {table} WHERE user_id=? ORDER BY {order}',(uid(),)))
@app.get('/api/clients')
def clients(): return simple('clients')
@app.get('/api/quotes')
def quotes(): return simple('quotes')
@app.get('/api/interventions')
def interventions(): return simple('interventions','date,id')
@app.get('/api/tasks')
def tasks(): return simple('tasks')
@app.get('/api/documents')
def documents(): return simple('documents')
@app.post('/api/tasks/<int:tid>/done')
def task_done(tid):
    if not auth(): return jsonify(error='Non connecté'),401
    c=db(); c.execute("UPDATE tasks SET status='Terminée' WHERE id=? AND user_id=?",(tid,uid())); c.commit(); c.close(); return jsonify(ok=True)
@app.post('/api/interventions/<int:iid>/complete')
def complete_intervention(iid):
    if not auth(): return jsonify(error='Non connecté'),401
    d=request.get_json() or {}; c=db(); c.execute("UPDATE interventions SET status='Terminée',report=? WHERE id=? AND user_id=?",(d.get('report','Rapport généré après intervention.'),iid,uid())); c.commit(); c.close(); return jsonify(ok=True)

@app.post('/api/ai')
def ai():
    if not auth(): return jsonify(error='Non connecté'),401
    d=request.get_json() or {}; text=d.get('text','').strip();
    if not text:return jsonify(error='Texte requis'),400
    return jsonify(analysis=analyze(text),message='Mode démo déterministe : aucune donnée absente n’est inventée.')

init()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')))
