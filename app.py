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
# RECHERCHE
# =============================
@app.route("/search", methods=["GET"])
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
        
        # Nouveaux paramètres
        type_metrage = request.args.get("type", "").strip()
        genre = request.args.get("genre", "").strip()
        budget_min = request.args.get("budget", "").strip()
        role_filter = request.args.get("role", "").strip() # Ex: "realisateur(s)"

        query = "SELECT * FROM films WHERE 1=1"
        params = []

        # --- FILTRES ---
        
        # Titre
        if title:
            query += " AND (titre ILIKE %s OR similarity(titre, %s) > 0.3)"
            params.append(f"%{title}%") 
            params.append(title) 
        
        # Année
        if year:
            query += " AND dateimmatriculation ILIKE %s"
            params.append(f"%{year}%")
            
        # Production
        if production:
            query += " AND (production ILIKE %s OR nationalité ILIKE %s)"
            val = f"%{production}%"
            params.extend([val, val])

        # Keywords (Synopsis)
        if keywords:
            # Vérifie si ta colonne s'appelle 'synopsis' ou 'synopsis_tmdb'
            query += " AND synopsis ILIKE %s" 
            params.append(f"%{keywords}%")

        # 1. Type de métrage (Long / Court)
        if type_metrage:
            # On suppose que la colonne s'appelle 'typemetrage' ou 'type' dans la BDD
            query += " AND typemetrage ILIKE %s"
            params.append(f"%{type_metrage}%")

        # 2. Genre
        if genre:
            query += " AND genre ILIKE %s"
            params.append(f"%{genre}%")

        # 3. Budget (Complexe : Conversion Texte -> Nombre)
        if budget_min:
            # On nettoie la colonne budget (enlève tout ce qui n'est pas chiffre) et on compare
            # Attention : cela suppose que ta colonne s'appelle 'budget' ou 'devis'
            query += " AND CAST(REGEXP_REPLACE(budget, '[^0-9]', '', 'g') AS BIGINT) >= %s"
            params.append(budget_min)

        # 4. Intervenant AVEC ou SANS Rôle spécifié
        if intervenant:
            if role_filter:
                # Si un rôle est choisi, on cible la colonne précise
                # Nettoyage du nom du rôle pour correspondre aux colonnes SQL (minuscule, sans parenthèses)
                # Ex: "realisateur(s)" devient "realisateurs"
                col_name = role_filter.replace("(", "").replace(")", "").lower()
                
                # Sécurité pour éviter l'injection SQL sur le nom de colonne
                valid_cols = ["realisateurs", "producteurs", "acteurs", "diffuseurs", "scenaristes"]
                if col_name in valid_cols:
                    query += f" AND {col_name} ILIKE %s"
                    params.append(f"%{intervenant}%")
                else:
                    # Fallback si le rôle n'est pas reconnu : on cherche partout
                    query += " AND (realisateurs ILIKE %s OR producteurs ILIKE %s OR scenaristes ILIKE %s)"
                    val = f"%{intervenant}%"
                    params.extend([val, val, val])
            else:
                # Pas de rôle choisi : on cherche partout (comme avant)
                query += " AND (realisateurs ILIKE %s OR producteurs ILIKE %s OR scenaristes ILIKE %s)"
                val = f"%{intervenant}%"
                params.extend([val, val, val])

        # 2. TRI PAR PERTINENCE
        if title:
            # On trie par "Note de ressemblance" (Le plus ressemblant en premier)
            query += " ORDER BY similarity(titre, %s) DESC"
            params.append(title)
        else:
            query += " ORDER BY dateimmatriculation DESC"

        query += " LIMIT 100"

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Conversion résultats
        results = []
        for row in rows:
            film = dict(row)
            plan_path = ""
            devis_path = ""
            for key in film.keys():
                if 'plan' in key and film[key]: plan_path = film[key]
                if 'devis' in key and film[key]: devis_path = film[key]

            film["plan_financement"] = normalize_pdf_path(plan_path)
            film["devis"] = normalize_pdf_path(devis_path)
            results.append(film)

        return jsonify(results)

    except Exception as e:
        print(f"❌ Erreur SQL : {e}")
        return jsonify([])

# =============================
# ROUTE PDF (TA VERSION REQUESTS)
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

    # --- TA CORRECTION API ---
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
