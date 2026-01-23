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
# RECHERCHE (CORRECTION "DISTINCT" vs "ORDER BY")
# =============================
@app.route("/search", methods=["GET"])
def search():
    if not DATABASE_URL: return jsonify([])

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

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

        # --- CORRECTION ICI : On enlève le "DISTINCT" pour éviter le crash SQL ---
        query = "SELECT * FROM films WHERE 1=1"
        params = []

        # A. TITRE
        if title:
            query += " AND (titre ILIKE %s OR similarity(titre, %s) > 0.3)"
            params.extend([f"%{title}%", title])
        
        # B. ANNÉE
        if year:
            query += " AND (dateimmatriculation ILIKE %s OR date_immatriculation ILIKE %s)"
            params.extend([f"%{year}%", f"%{year}%"])
            
        # C. PRODUCTION
        if production:
            query += " AND (production ILIKE %s OR nationalite ILIKE %s OR origine ILIKE %s)"
            val = f"%{production}%"
            params.extend([val, val, val])

        # D. SYNOPSIS
        if keywords:
            query += " AND (synopsis_tmdb ILIKE %s OR synopsis ILIKE %s)" 
            params.extend([f"%{keywords}%", f"%{keywords}%"])

        # E. TYPE
        if type_metrage:
            query += " AND (typemetrage ILIKE %s OR type_de_metrage ILIKE %s)"
            params.extend([f"%{type_metrage}%", f"%{type_metrage}%"])

        # F. GENRE
        if genre:
            query += " AND genre ILIKE %s"
            params.append(f"%{genre}%")

        # G. BUDGET
        if budget_min:
            query += " AND CAST(NULLIF(REGEXP_REPLACE(budget, '[^0-9]', '', 'g'), '') AS BIGINT) >= %s"
            params.append(budget_min)

        # H. INTERVENANT
        if intervenant:
            target_col = None
            if role_filter:
                r = role_filter.lower()
                if "realisat" in r: target_col = "realisateurs"
                elif "product" in r: target_col = "producteurs"
                elif "scenar" in r: target_col = "scenaristes"
                elif "acteu" in r: target_col = "acteurs"
                elif "diffus" in r: target_col = "diffuseurs"

            if target_col:
                 query += f" AND ({target_col} ILIKE %s OR {target_col[:-1]} ILIKE %s)"
                 params.extend([f"%{intervenant}%", f"%{intervenant}%"])
            else:
                query += " AND (realisateurs ILIKE %s OR producteurs ILIKE %s OR scenaristes ILIKE %s OR acteurs ILIKE %s)"
                val = f"%{intervenant}%"
                params.extend([val, val, val, val])

        # TRI
        if title:
            query += " ORDER BY similarity(titre, %s) DESC"
            params.append(title)
        else:
            query += " ORDER BY dateimmatriculation DESC"

        query += " LIMIT 100"

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # --- DÉDUPLICATION EN PYTHON (C'est ici qu'on remplace le DISTINCT) ---
        seen_titles = set()
        results = []
        
        for row in rows:
            film = dict(row)
            
            # On crée une clé unique (Titre + Année) pour repérer les doublons
            unique_key = (film.get('titre', '').lower(), film.get('dateimmatriculation', ''))
            
            if unique_key in seen_titles:
                continue # On ignore ce film car on l'a déjà vu
            
            seen_titles.add(unique_key)

            # Récupération PDF
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


