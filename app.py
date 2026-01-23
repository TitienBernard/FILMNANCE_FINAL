from flask import Flask, request, jsonify, render_template, Response, send_from_directory
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import urllib.parse
import requests
import urllib3
import re

# Désactiver les warnings SSL (Indispensable pour RCA)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__, static_folder="static", template_folder="templates")

DATABASE_URL = os.environ.get('DATABASE_URL')
BASE_API = "https://rca.cnc.fr"

# =============================
# CONNEXION DB
# =============================
def get_db_connection():
    if not DATABASE_URL: return None
    return psycopg2.connect(DATABASE_URL)

# =============================
# UTILS
# =============================
def normalize_pdf_path(path):
    if not path or str(path).lower() in ['nan', 'null', 'none', '']: return ""
    path = str(path).strip()
    # On nettoie les guillemets qui traînent parfois en base
    path = path.strip('"').strip("'")
    return path

# =============================
# GESTION SESSION (PROTÉGÉE)
# =============================
_rca_session = None
def get_rca_session():
    global _rca_session
    if _rca_session is None:
        _rca_session = requests.Session()
        _rca_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://rca.cnc.fr/recherche/simple',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7'
        })
        # Initialisation du cookie JSESSIONID
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
# RECHERCHE (Version Stable)
# =============================
@app.route("/search", methods=["GET"])
def search():
    if not DATABASE_URL: return jsonify([])

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Auto-détection des colonnes
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'films'")
        all_db_cols = [row['column_name'].lower() for row in cur.fetchall()]

        def find_col(keyword):
            if keyword in all_db_cols: return keyword
            for col in all_db_cols:
                if keyword in col: return col
            return None

        # Identification des colonnes
        col_titre = find_col('titre') or 'titre'
        col_date = find_col('immatriculation') or find_col('date')
        col_type = find_col('typemetrage') or find_col('type')
        col_synopsis = find_col('synopsis') or find_col('resume')
        col_prod = find_col('production')
        col_genre = find_col('genre')
        col_budget = find_col('budget') or find_col('devis')
        
        # Pour les PDF : on force les noms si détectés ou on devine
        col_pdf_plan = 'path_plan_financement_simple' if 'path_plan_financement_simple' in all_db_cols else (find_col('plan_financement') or find_col('plan'))
        col_pdf_devis = 'path_devis_simple' if 'path_devis_simple' in all_db_cols else (find_col('devis_simple') or find_col('devis'))

        # Params User
        title = request.args.get("title", "").strip()
        year = request.args.get("year", "").strip()
        intervenant = request.args.get("intervenant", "").strip()
        production = request.args.get("production", "").strip()
        keywords = request.args.get("keywords", "").strip()
        type_metrage = request.args.get("type", "").strip()
        genre = request.args.get("genre", "").strip()
        budget_min = request.args.get("budget", "").strip()
        role_filter = request.args.get("role", "").strip()

        # Requête
        query = "SELECT * FROM films WHERE 1=1"
        params = []

        # A. TITRE
        if title and col_titre:
            query += f' AND ("{col_titre}" ILIKE %s OR similarity("{col_titre}", %s) > 0.3)'
            params.extend([f"%{title}%", title])
        # B. ANNÉE
        if year and col_date:
            query += f' AND "{col_date}" ILIKE %s'
            params.append(f"%{year}%")
        # C. TYPE
        if type_metrage and col_type:
            query += f' AND "{col_type}" ILIKE %s'
            params.append(f"%{type_metrage}%")
        # D. GENRE
        if genre and col_genre:
            query += f' AND "{col_genre}" ILIKE %s'
            params.append(f"%{genre}%")
        # E. PRODUCTION
        if production:
            prod_cols = [c for c in all_db_cols if any(k in c for k in ['production', 'nationalite', 'origine'])]
            if prod_cols:
                or_clause = " OR ".join([f'"{c}" ILIKE %s' for c in prod_cols])
                query += f" AND ({or_clause})"
                params.extend([f"%{production}%"] * len(prod_cols))
        # F. SYNOPSIS
        if keywords and col_synopsis:
            query += f' AND "{col_synopsis}" ILIKE %s'
            params.append(f"%{keywords}%")
        # G. BUDGET
        if budget_min and col_budget:
            query += f""" AND CAST(NULLIF(REGEXP_REPLACE("{col_budget}", '[^0-9]', '', 'g'), '') AS BIGINT) >= %s """
            params.append(budget_min)
        # H. INTERVENANT
        if intervenant:
            target_cols = []
            if role_filter:
                r = role_filter.lower()
                key = ""
                if "realisat" in r: key = "realisat"
                elif "product" in r: key = "product"
                elif "scenar" in r: key = "scenar"
                elif "acteu" in r: key = "acteu"
                elif "diffus" in r: key = "diffus"
                if key: target_cols = [c for c in all_db_cols if key in c and "delegue" not in c]
            if not target_cols:
                role_keys = ['realisat', 'producteur', 'scenariste', 'acteur', 'diffuseur']
                target_cols = [c for c in all_db_cols if any(k in c for k in role_keys)]
            if target_cols:
                or_clause = " OR ".join([f'"{c}" ILIKE %s' for c in target_cols])
                query += f" AND ({or_clause})"
                params.extend([f"%{intervenant}%"] * len(target_cols))

        # TRI
        if title and col_titre:
            query += f' ORDER BY similarity("{col_titre}", %s) DESC'
            params.append(title)
        elif col_date:
            query += f' ORDER BY "{col_date}" DESC'

        query += " LIMIT 100"

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # --- DÉDUPLICATION ET FORMATAGE ---
        seen = set()
        results = []
        for row in rows:
            film = dict(row)
            
            # Mapping pour le JS
            if col_date and col_date in film: film['dateimmatriculation'] = film[col_date]
            if col_type and col_type in film: film['typemetrage'] = film[col_type]
            if col_synopsis and col_synopsis in film: film['synopsis'] = film[col_synopsis]
            if col_budget and col_budget in film: film['budget'] = film[col_budget]
            
            # Récupération et nettoyage des chemins PDF
            p_val = film.get(col_pdf_plan) if col_pdf_plan else None
            d_val = film.get(col_pdf_devis) if col_pdf_devis else None
            
            film["plan_financement"] = normalize_pdf_path(p_val)
            film["devis"] = normalize_pdf_path(d_val)

            unique_id = (film.get(col_titre, '').lower(), film.get(col_date, ''))
            if unique_id in seen: continue
            seen.add(unique_id)
            results.append(film)

        return jsonify(results)

    except Exception as e:
        print(f"❌ ERREUR SQL : {e}")
        return jsonify({"error": str(e)})


# ==========
# ROUTE PDF
# ==========
@app.route("/get_pdf")
def get_pdf():
    # 1. Récupération
    raw_path = request.args.get("path")
    if not raw_path: return "Erreur: Chemin manquant", 400
    
    # 2. Décodage et Nettoyage
    # On décode une fois (ex: %2F -> /)
    path = urllib.parse.unquote(raw_path).strip()
    
    # 3. Construction de l'URL cible (C'est ici la correction)
    # Cas 1 : URL déjà complète (rare mais possible)
    if path.startswith("http"):
        target_url = path
    
    # Cas 2 : Le chemin commence par /documentActe/ (Le cas que tu m'as montré)
    # On doit le transformer en : https://rca.cnc.fr/rca.frontoffice/api/documentActe/...
    elif path.startswith("/documentActe/"):
        target_url = f"https://rca.cnc.fr/rca.frontoffice/api{path}"
    
    # Cas 3 : Autre chemin relatif
    else:
        # On s'assure que le chemin commence par /
        if not path.startswith("/"): path = "/" + path
        target_url = f"https://rca.cnc.fr{path}"
        
        # Patch API si nécessaire
        if "/documentActe/" in target_url and "/api/" not in target_url:
            target_url = target_url.replace("/rca.frontoffice", "") # Au cas où
            target_url = target_url.replace("/documentActe/", "/rca.frontoffice/api/documentActe/")

    print(f"🔗 TÉLÉCHARGEMENT CIBLÉ : {target_url}")

    try:
        session = get_rca_session()
        # On télécharge en streaming
        response = session.get(target_url, stream=True, verify=False, timeout=30)
        
        print(f"📊 Code RCA : {response.status_code}")
        
        if response.status_code != 200:
            return f"Le RCA a refusé le fichier (Erreur {response.status_code})<br>Lien tenté: {target_url}", 404

        # Extraction du nom du fichier
        filename = "document_rca.pdf"
        cd = response.headers.get("Content-Disposition", "")
        if "filename=" in cd:
            filename = cd.split("filename=")[1].strip('"')
        elif "idDocument=" in target_url:
            match = re.search(r'idDocument=([a-f0-9\-]+)', target_url)
            if match: filename = f"RCA_{match.group(1)[:8]}.pdf"

        return Response(
            response.iter_content(chunk_size=8192),
            content_type='application/pdf',
            headers={'Content-Disposition': f'inline; filename="{filename}"'}
        )
    except Exception as e:
        print(f"❌ CRASH REQUÊTE PDF : {e}")
        return f"Erreur serveur : {e}", 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
