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

# Récupération de l'URL de la base (définie automatiquement par Render)
DATABASE_URL = os.environ.get('DATABASE_URL')
BASE_API = "https://rca.cnc.fr"

# =============================
# CONNEXION DB
# =============================
def get_db_connection():
    if not DATABASE_URL:
        return None
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# =============================
# UTILS
# =============================
def normalize_pdf_path(path):
    if not path or str(path).lower() in ['nan', 'null', 'none', '']: return ""
    path = str(path).strip()
    if path.startswith('http'): return path
    if path and not path.startswith('/'): path = '/' + path
    return path

# =============================
# GESTION SESSION (REQUESTS)
# =============================
_rca_session = None
def get_rca_session():
    global _rca_session
    if _rca_session is None:
        _rca_session = requests.Session()
        _rca_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://rca.cnc.fr/recherche/simple'
        })
        try: _rca_session.get(BASE_API, verify=False, timeout=5)
        except: pass
    return _rca_session

# =============================
# ROUTES HTML
# =============================
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
# RECHERCHE (FILTRES SQL CORRIGÉS)
# =============================
@app.route("/search", methods=["GET"])
def search():
    if not DATABASE_URL:
        return jsonify([])

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Récupération des paramètres
        title = request.args.get("title", "").strip()
        year = request.args.get("year", "").strip()
        intervenant = request.args.get("intervenant", "").strip()
        production = request.args.get("production", "").strip()
        keywords = request.args.get("keywords", "").strip()
        
        type_metrage = request.args.get("type", "").strip()
        genre = request.args.get("genre", "").strip()
        budget_min = request.args.get("budget", "").strip()
        role_filter = request.args.get("role", "").strip()

        # 2. Construction de la requête
        # On utilise "DISTINCT" pour éviter les doublons si le CSV en contient
        query = "SELECT DISTINCT * FROM films WHERE 1=1"
        params = []

        # --- A. TITRE ---
        if title:
            query += " AND (titre ILIKE %s OR similarity(titre, %s) > 0.3)"
            params.append(f"%{title}%") 
            params.append(title) 
        
        # --- B. ANNÉE ---
        # Correction : le nom probable est 'date_immatriculation' ou 'dateimmatriculation'
        if year:
            # On essaie de matcher l'année n'importe où dans la date (ex: '2020' dans '12/05/2020')
            query += " AND date_immatriculation ILIKE %s"
            params.append(f"%{year}%")
            
        # --- C. PRODUCTION ---
        if production:
            # Correction : noms de colonnes probables avec underscores
            query += " AND (production ILIKE %s OR nationalite ILIKE %s OR origine ILIKE %s)"
            val = f"%{production}%"
            params.extend([val, val, val])

        # --- D. SYNOPSIS (Keywords) ---
        if keywords:
            # Correction : nom probable 'synopsis_tmdb' ou 'synopsis'
            # On teste sur la colonne synopsis_tmdb (si elle existe)
            query += " AND synopsis_tmdb ILIKE %s" 
            params.append(f"%{keywords}%")

        # --- E. TYPE DE MÉTRAGE ---
        if type_metrage:
            # Correction : 'Type de métrage' -> 'type_de_metrage'
            query += " AND type_de_metrage ILIKE %s"
            params.append(f"%{type_metrage}%")

        # --- F. GENRE ---
        if genre:
            # 'genre' reste souvent 'genre'
            query += " AND genre ILIKE %s"
            params.append(f"%{genre}%")

        # --- G. BUDGET ---
        if budget_min:
            # Le budget est du texte ("1 500 000 €"). On nettoie pour comparer.
            # On remplace NULL par '0' pour éviter les crashs
            query += """ 
                AND CAST(
                    COALESCE(
                        NULLIF(REGEXP_REPLACE(budget, '[^0-9]', '', 'g'), ''), 
                        '0'
                    ) AS BIGINT
                ) >= %s 
            """
            params.append(budget_min)

        # --- H. INTERVENANT + ROLE ---
        if intervenant:
            if role_filter:
                # Nettoyage du rôle : "Realisateur(s)" -> "realisateurs"
                target_col = role_filter.lower().replace("(", "").replace(")", "").replace("-", "")
                
                # Vérification de sécurité des noms de colonnes
                # Dans ton CSV, "Realisateur(s)" devient "realisateurs" via import_csv.py
                possible_cols = {
                    "realisateurs": "realisateurs",
                    "producteurs": "producteurs",
                    "scenaristes": "scenaristes",
                    "acteurs": "acteurs",
                    "diffuseurs": "diffuseurs"
                }
                
                # On trouve la bonne colonne
                found_col = None
                for key in possible_cols:
                    if key in target_col:
                        found_col = possible_cols[key]
                        break
                
                if found_col:
                    query += f" AND {found_col} ILIKE %s"
                    params.append(f"%{intervenant}%")
                else:
                    # Si on ne reconnait pas le rôle, on cherche partout
                    query += " AND (realisateurs ILIKE %s OR producteurs ILIKE %s OR scenaristes ILIKE %s)"
                    val = f"%{intervenant}%"
                    params.extend([val, val, val])
            else:
                # Pas de rôle : on cherche partout
                query += " AND (realisateurs ILIKE %s OR producteurs ILIKE %s OR scenaristes ILIKE %s OR acteurs ILIKE %s)"
                val = f"%{intervenant}%"
                params.extend([val, val, val, val])

        # --- TRI ---
        if title:
            query += " ORDER BY similarity(titre, %s) DESC"
            params.append(title)
        else:
            # Correction : date_immatriculation
            query += " ORDER BY date_immatriculation DESC"

        query += " LIMIT 100"

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        for row in rows:
            film = dict(row)
            # Gestion souple des noms de colonnes PDF
            p_path = film.get('path_plan_financement_simple') or film.get('plan_financement') or film.get('plan')
            d_path = film.get('path_devis_simple') or film.get('devis')
            
            film["plan_financement"] = normalize_pdf_path(p_path)
            film["devis"] = normalize_pdf_path(d_path)
            results.append(film)

        return jsonify(results)

    except Exception as e:
        # C'EST ICI QUE TU VERRAS L'ERREUR DANS LES LOGS RENDER
        print(f"❌ Erreur SQL sur la recherche : {e}")
        return jsonify([])

# =============================
# ROUTE PDF (VERSION PROD - REQUESTS)
# =============================
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

    # Correction URLs API RCA
    if "/documentActe/" in target_url and "/api/" not in target_url:
        target_url = target_url.replace("/rca.frontoffice", "")
        target_url = target_url.replace("/documentActe/", "/rca.frontoffice/api/documentActe/")
    
    if "api" not in target_url and "rca.frontoffice" in target_url:
         target_url = target_url.replace("/rca.frontoffice/", "/rca.frontoffice/api/")

    print(f"🔗 Download : {target_url}")

    try:
        session = get_rca_session()
        response = session.get(target_url, stream=True, verify=False, timeout=30)
        
        filename = "document.pdf"
        if "idDocument=" in target_url:
            match = re.search(r'idDocument=([a-f0-9\-]+)', target_url)
            if match: filename = f"RCA_{match.group(1)[:8]}.pdf"

        return Response(
            response.iter_content(chunk_size=8192),
            content_type='application/pdf',
            headers={'Content-Disposition': f'inline; filename="{filename}"'}
        )
    except Exception as e:
        return f"Erreur : {e}", 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
