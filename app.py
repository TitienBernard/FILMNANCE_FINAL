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
# RECHERCHE (FILTRES COMPLETS SQL)
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
        
        # Nouveaux paramètres (Filtres avancés)
        type_metrage = request.args.get("type", "").strip()
        genre = request.args.get("genre", "").strip()
        budget_min = request.args.get("budget", "").strip()
        role_filter = request.args.get("role", "").strip() # Ex: "realisateur(s)"

        # 2. Construction de la requête SQL Dynamique
        query = "SELECT * FROM films WHERE 1=1"
        params = []

        # --- A. FILTRE TITRE (Recherche floue + Exacte) ---
        if title:
            # On cherche si le titre contient le texte OU si la ressemblance est > 30%
            query += " AND (titre ILIKE %s OR similarity(titre, %s) > 0.3)"
            params.append(f"%{title}%") 
            params.append(title) 
        
        # --- B. FILTRE ANNÉE ---
        if year:
            query += " AND dateimmatriculation ILIKE %s"
            params.append(f"%{year}%")
            
        # --- C. FILTRE PRODUCTION ---
        if production:
            # On cherche large : production, nationalité, origine...
            query += " AND (production ILIKE %s OR nationalité ILIKE %s OR origine ILIKE %s)"
            val = f"%{production}%"
            params.extend([val, val, val])

        # --- D. FILTRE KEYWORDS (Synopsis) ---
        if keywords:
            # On cherche dans la colonne synopsis_tmdb (ou synopsis)
            # COALESCE permet d'éviter les erreurs si le champ est vide
            query += " AND (synopsis_tmdb ILIKE %s)" 
            params.append(f"%{keywords}%")

        # --- E. FILTRE TYPE DE MÉTRAGE ---
        if type_metrage:
            # On cherche "long" dans "Long métrage"
            query += " AND typemetrage ILIKE %s"
            params.append(f"%{type_metrage}%")

        # --- F. FILTRE GENRE ---
        if genre:
            query += " AND genre ILIKE %s"
            params.append(f"%{genre}%")

        # --- G. FILTRE BUDGET (Conversion SQL complexe) ---
        if budget_min:
            # SQL PUISSANT : On enlève tout ce qui n'est pas un chiffre ([^0-9]) et on convertit en nombre (BIGINT)
            # Cela transforme "1 500 000 €" en 1500000 pour pouvoir faire le >=
            query += " AND CAST(REGEXP_REPLACE(budget, '[^0-9]', '', 'g') AS BIGINT) >= %s"
            params.append(budget_min)

        # --- H. FILTRE INTERVENANT AVEC RÔLE ---
        if intervenant:
            if role_filter:
                # 1. Nettoyage du nom du rôle pour correspondre à tes colonnes SQL
                # Ex: "realisateur(s)" -> "realisateurs"
                col_name = role_filter.lower().replace("(", "").replace(")", "").replace("-", "")
                
                # Petite correction manuelle pour être sûr des noms de colonnes
                if "realisat" in col_name: col_target = "realisateurs"
                elif "product" in col_name: col_target = "producteurs"
                elif "scenar" in col_name: col_target = "scenaristes"
                elif "acteu" in col_name: col_target = "acteurs"
                elif "diffus" in col_name: col_target = "diffuseurs"
                else: col_target = None

                if col_target:
                    # Recherche ciblée sur une colonne
                    query += f" AND {col_target} ILIKE %s"
                    params.append(f"%{intervenant}%")
                else:
                    # Fallback : on cherche partout si le rôle n'est pas reconnu
                    query += " AND (realisateurs ILIKE %s OR producteurs ILIKE %s OR scenaristes ILIKE %s)"
                    val = f"%{intervenant}%"
                    params.extend([val, val, val])
            else:
                # Pas de rôle choisi : on cherche partout
                query += " AND (realisateurs ILIKE %s OR producteurs ILIKE %s OR scenaristes ILIKE %s OR acteurs ILIKE %s)"
                val = f"%{intervenant}%"
                params.extend([val, val, val, val])

        # --- 3. TRI DES RÉSULTATS ---
        if title:
            # Tri par pertinence (Note de ressemblance)
            query += " ORDER BY similarity(titre, %s) DESC"
            params.append(title)
        else:
            # Tri par date par défaut
            query += " ORDER BY dateimmatriculation DESC"

        query += " LIMIT 100"

        # Exécution
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Conversion résultats et Nettoyage Chemins PDF
        results = []
        for row in rows:
            film = dict(row)
            
            # On cherche les chemins dans les colonnes possibles
            p_path = film.get('path_plan_financement_simple') or film.get('plan_financement') or film.get('plan')
            d_path = film.get('path_devis_simple') or film.get('devis')
            
            film["plan_financement"] = normalize_pdf_path(p_path)
            film["devis"] = normalize_pdf_path(d_path)
            results.append(film)

        return jsonify(results)

    except Exception as e:
        print(f"❌ Erreur SQL : {e}")
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
