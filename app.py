from flask import Flask, request, jsonify, render_template, Response, send_from_directory
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import urllib.parse
import requests
import urllib3
import re

# Désactiver les warnings SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__, static_folder="static", template_folder="templates")

DATABASE_URL = os.environ.get('DATABASE_URL')
BASE_API = "https://rca.cnc.fr"

def get_db_connection():
    if not DATABASE_URL: return None
    return psycopg2.connect(DATABASE_URL)

def normalize_pdf_path(path):
    if not path or str(path).lower() in ['nan', 'null', 'none', '']: return ""
    path = str(path).strip()
    if path.startswith('http'): return path
    if path and not path.startswith('/'): path = '/' + path
    return path

_rca_session = None
def get_rca_session():
    global _rca_session
    if _rca_session is None:
        _rca_session = requests.Session()
        _rca_session.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://rca.cnc.fr/'})
        try: _rca_session.get(BASE_API, verify=False, timeout=5)
        except: pass
    return _rca_session

@app.route("/")
def home(): return render_template("index.html")
@app.route("/database")
def database(): return render_template("database.html")
@app.route("/presentation")
def presentation(): return render_template("presentation.html")
@app.route("/about")
def about(): return render_template("about.html")
@app.route("/download_cv")
def download_cv():
    try: return send_from_directory(directory='static', path='Titien Bernard CV.pdf', as_attachment=True)
    except: return "CV introuvable", 404

# =============================
# RECHERCHE ULTIME (HYBRIDE)
# =============================
@app.route("/search", methods=["GET"])
def search():
    if not DATABASE_URL: return jsonify([])

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. INTELLIGENCE : On regarde quelles colonnes existent vraiment
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'films'")
        existing_columns = [row['column_name'] for row in cur.fetchall()]
        
        def col_exists(name): return name in existing_columns

        # Params
        title = request.args.get("title", "").strip()
        year = request.args.get("year", "").strip()
        intervenant = request.args.get("intervenant", "").strip()
        production = request.args.get("production", "").strip()
        keywords = request.args.get("keywords", "").strip()
        type_metrage = request.args.get("type", "").strip()
        genre = request.args.get("genre", "").strip()
        budget_min = request.args.get("budget", "").strip()
        role_filter = request.args.get("role", "").strip()

        # 2. REQUÊTE (Sans DISTINCT pour éviter le crash ORDER BY)
        query = "SELECT * FROM films WHERE 1=1"
        params = []

        # A. TITRE
        if title:
            # On vérifie si la colonne titre existe (normalement oui)
            t_col = 'titre' if col_exists('titre') else ('nom' if col_exists('nom') else None)
            if t_col:
                query += f" AND ({t_col} ILIKE %s OR similarity({t_col}, %s) > 0.3)"
                params.extend([f"%{title}%", title])

        # B. ANNÉE (Cherche 'dateimmatriculation', 'date_immatriculation', etc.)
        if year:
            possible_cols = ['dateimmatriculation', 'date_immatriculation', 'annee', 'date']
            valid = [c for c in possible_cols if col_exists(c)]
            if valid:
                or_clause = " OR ".join([f"{c} ILIKE %s" for c in valid])
                query += f" AND ({or_clause})"
                params.extend([f"%{year}%"] * len(valid))

        # C. PRODUCTION
        if production:
            possible_cols = ['production', 'producteur_delegue', 'nationalite', 'origine']
            valid = [c for c in possible_cols if col_exists(c)]
            if valid:
                or_clause = " OR ".join([f"{c} ILIKE %s" for c in valid])
                query += f" AND ({or_clause})"
                params.extend([f"%{production}%"] * len(valid))

        # D. SYNOPSIS
        if keywords:
            possible_cols = ['synopsis_tmdb', 'synopsis', 'resume']
            valid = [c for c in possible_cols if col_exists(c)]
            if valid:
                or_clause = " OR ".join([f"{c} ILIKE %s" for c in valid])
                query += f" AND ({or_clause})"
                params.extend([f"%{keywords}%"] * len(valid))

        # E. TYPE DE MÉTRAGE
        if type_metrage:
            possible_cols = ['typemetrage', 'type_de_metrage', 'categorie', 'type']
            valid = [c for c in possible_cols if col_exists(c)]
            if valid:
                or_clause = " OR ".join([f"{c} ILIKE %s" for c in valid])
                query += f" AND ({or_clause})"
                params.extend([f"%{type_metrage}%"] * len(valid))

        # F. GENRE
        if genre and col_exists('genre'):
            query += " AND genre ILIKE %s"
            params.append(f"%{genre}%")

        # G. BUDGET (Le plus important : détecte 'budget' OU 'devis')
        if budget_min:
            b_col = None
            if col_exists('budget'): b_col = 'budget'
            elif col_exists('devis'): b_col = 'devis'
            elif col_exists('devis_global'): b_col = 'devis_global'
            
            if b_col:
                query += f" AND CAST(NULLIF(REGEXP_REPLACE({b_col}, '[^0-9]', '', 'g'), '') AS BIGINT) >= %s"
                params.append(budget_min)

        # H. INTERVENANT
        if intervenant:
            target_cols = []
            if role_filter:
                r = role_filter.lower()
                keyword = ""
                if "realisat" in r: keyword = "realisat"
                elif "product" in r: keyword = "product" # Attrape producteur et production
                elif "scenar" in r: keyword = "scenariste"
                elif "acteu" in r: keyword = "acteur"
                elif "diffus" in r: keyword = "diffuseur"
                
                # Cherche les colonnes correspondantes
                target_cols = [c for c in existing_columns if keyword in c]
            
            if not target_cols:
                # Cherche partout
                keywords_roles = ['realisat', 'producteur', 'scenariste', 'acteur', 'diffuseur']
                target_cols = [c for c in existing_columns if any(k in c for k in keywords_roles)]

            if target_cols:
                or_clause = " OR ".join([f"{c} ILIKE %s" for c in target_cols])
                query += f" AND ({or_clause})"
                params.extend([f"%{intervenant}%"] * len(target_cols))

        # TRI
        if title and col_exists('titre'):
            query += " ORDER BY similarity(titre, %s) DESC"
            params.append(title)
        else:
            # Tri par date si possible
            d_col = 'dateimmatriculation' if col_exists('dateimmatriculation') else ('date_immatriculation' if col_exists('date_immatriculation') else None)
            if d_col:
                query += f" ORDER BY {d_col} DESC"

        query += " LIMIT 100"

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # 3. DÉDUPLICATION EN PYTHON
        seen = set()
        results = []
        for row in rows:
            film = dict(row)
            
            # Normalisation pour le JS (si la base a des noms bizarres)
            if 'type_de_metrage' in film: film['typemetrage'] = film['type_de_metrage']
            if 'date_immatriculation' in film: film['dateimmatriculation'] = film['date_immatriculation']
            
            # Clé unique pour dédoublonner
            key = (film.get('titre', '').lower(), film.get('dateimmatriculation', ''))
            if key in seen: continue
            seen.add(key)

            # PDF
            p_path = film.get('path_plan_financement_simple') or film.get('plan_financement') or film.get('plan')
            d_path = film.get('path_devis_simple') or film.get('devis')
            film["plan_financement"] = normalize_pdf_path(p_path)
            film["devis"] = normalize_pdf_path(d_path)
            
            results.append(film)

        return jsonify(results)

    except Exception as e:
        print(f"❌ ERREUR SQL : {e}")
        return jsonify({"error": str(e)})

@app.route("/get_pdf")
def get_pdf():
    path = request.args.get("path")
    if not path: return "Erreur chemin", 400
    path = urllib.parse.unquote(path)
    
    if path.startswith('http'): target_url = path
    else:
        base = BASE_API.rstrip('/')
        clean_path = path if path.startswith('/') else '/' + path
        target_url = f"{base}{clean_path}"

    if "/documentActe/" in target_url and "/api/" not in target_url:
        target_url = target_url.replace("/rca.frontoffice", "/rca.frontoffice/api")
    if "api" not in target_url and "rca.frontoffice" in target_url:
         target_url = target_url.replace("/rca.frontoffice/", "/rca.frontoffice/api/")

    try:
        session = get_rca_session()
        response = session.get(target_url, stream=True, verify=False, timeout=30)
        filename = "document.pdf"
        if "idDocument=" in target_url:
            match = re.search(r'idDocument=([a-f0-9\-]+)', target_url)
            if match: filename = f"RCA_{match.group(1)[:8]}.pdf"
        return Response(response.iter_content(chunk_size=8192), content_type='application/pdf', headers={'Content-Disposition': f'inline; filename="{filename}"'})
    except Exception as e:
        return f"Erreur : {e}", 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
