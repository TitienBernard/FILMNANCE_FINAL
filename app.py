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

# =============================
# CONNEXION DB
# =============================
def get_db_connection():
    if not DATABASE_URL: return None
    return psycopg2.connect(DATABASE_URL)

# =============================
# INTELLIGENCE DES COLONNES (Le Secret) 🧠
# =============================
# Cette variable va stocker les vrais noms de tes colonnes
REAL_COLUMNS = {}

def load_real_column_names():
    """Détecte les vrais noms de colonnes dans la base pour éviter les erreurs."""
    global REAL_COLUMNS
    if not DATABASE_URL: return
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'films'")
        rows = cur.fetchall()
        conn.close()
        
        # On crée un dictionnaire de correspondance
        # Ex: "typemetrage" -> "typemetrage", "type_de_metrage" -> "typemetrage"
        all_cols = [r[0] for r in rows]
        
        # On essaie de mapper nos besoins vers ce qui existe vraiment
        mapping = {
            "titre": ["titre", "nom", "title"],
            "date": ["date_immatriculation", "dateimmatriculation", "date", "annee"],
            "type": ["type_de_metrage", "typemetrage", "type", "categorie"],
            "budget": ["budget", "devis", "devis_global", "cout"],
            "synopsis": ["synopsis_tmdb", "synopsis", "resume", "description"],
            "production": ["production", "producteur_delegue", "societe"],
            "genre": ["genre", "genres"],
            "nationalite": ["nationalite", "pays", "origine"],
            "plan": ["path_plan_financement_simple", "plan_financement", "plan"],
            "devis": ["path_devis_simple", "devis", "devis_estime"]
        }
        
        for key, possibilities in mapping.items():
            found = None
            for p in possibilities:
                if p in all_cols:
                    found = p
                    break
            if found:
                REAL_COLUMNS[key] = found
                print(f"✅ Colonne trouvée pour '{key}': {found}")
            else:
                print(f"⚠️ Aucune colonne trouvée pour '{key}'")
                REAL_COLUMNS[key] = None # Pas de colonne dispo

        # Ajout des rôles (plus complexe car contient souvent 'realisateurs' ou 'realisateur')
        for col in all_cols:
            col_lower = col.lower()
            if "realisat" in col_lower: REAL_COLUMNS["realisateurs"] = col
            if "scenar" in col_lower: REAL_COLUMNS["scenaristes"] = col
            if "producteur" in col_lower and "delegue" not in col_lower: REAL_COLUMNS["producteurs"] = col
            if "acteur" in col_lower: REAL_COLUMNS["acteurs"] = col
            if "diffus" in col_lower: REAL_COLUMNS["diffuseurs"] = col

    except Exception as e:
        print(f"❌ Erreur détection colonnes: {e}")

# On lance la détection au démarrage
load_real_column_names()

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
# GESTION SESSION RCA
# =============================
_rca_session = None
def get_rca_session():
    global _rca_session
    if _rca_session is None:
        _rca_session = requests.Session()
        _rca_session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://rca.cnc.fr/'
        })
        try: _rca_session.get(BASE_API, verify=False, timeout=5)
        except: pass
    return _rca_session

# =============================
# ROUTES
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
# RECHERCHE INTELLIGENTE 🔍
# =============================
@app.route("/search", methods=["GET"])
def search():
    if not DATABASE_URL: return jsonify([])

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Récupération Params
        title = request.args.get("title", "").strip()
        year = request.args.get("year", "").strip()
        type_metrage = request.args.get("type", "").strip()
        genre = request.args.get("genre", "").strip()
        budget_min = request.args.get("budget", "").strip()
        production = request.args.get("production", "").strip()
        keywords = request.args.get("keywords", "").strip()
        intervenant = request.args.get("intervenant", "").strip()
        role_filter = request.args.get("role", "").strip()

        # Construction requête
        query = "SELECT * FROM films WHERE 1=1"
        params = []

        # --- FILTRES DYNAMIQUES (Seulement si la colonne existe) ---

        # 1. TITRE (On suppose que 'titre' existe toujours ou presque)
        if title and REAL_COLUMNS.get('titre'):
            col = REAL_COLUMNS['titre']
            query += f" AND ({col} ILIKE %s OR similarity({col}, %s) > 0.3)"
            params.extend([f"%{title}%", title])

        # 2. ANNÉE
        if year and REAL_COLUMNS.get('date'):
            query += f" AND {REAL_COLUMNS['date']} ILIKE %s"
            params.append(f"%{year}%")

        # 3. TYPE DE MÉTRAGE
        if type_metrage and REAL_COLUMNS.get('type'):
            query += f" AND {REAL_COLUMNS['type']} ILIKE %s"
            params.append(f"%{type_metrage}%")

        # 4. GENRE
        if genre and REAL_COLUMNS.get('genre'):
            query += f" AND {REAL_COLUMNS['genre']} ILIKE %s"
            params.append(f"%{genre}%")

        # 5. PRODUCTION (Recherche large)
        if production:
            cols_to_check = []
            if REAL_COLUMNS.get('production'): cols_to_check.append(REAL_COLUMNS['production'])
            if REAL_COLUMNS.get('nationalite'): cols_to_check.append(REAL_COLUMNS['nationalite'])
            
            if cols_to_check:
                or_clause = " OR ".join([f"{c} ILIKE %s" for c in cols_to_check])
                query += f" AND ({or_clause})"
                params.extend([f"%{production}%"] * len(cols_to_check))

        # 6. BUDGET (Nettoyage)
        if budget_min and REAL_COLUMNS.get('budget'):
            col = REAL_COLUMNS['budget']
            query += f" AND CAST(NULLIF(REGEXP_REPLACE({col}, '[^0-9]', '', 'g'), '') AS BIGINT) >= %s"
            params.append(budget_min)

        # 7. MOTS CLÉS (Synopsis)
        if keywords and REAL_COLUMNS.get('synopsis'):
            query += f" AND {REAL_COLUMNS['synopsis']} ILIKE %s"
            params.append(f"%{keywords}%")

        # 8. INTERVENANTS
        if intervenant:
            target_cols = []
            
            # Si un rôle précis est demandé
            if role_filter:
                role_key = None
                if "realisat" in role_filter: role_key = "realisateurs"
                elif "product" in role_filter: role_key = "producteurs"
                elif "scenar" in role_filter: role_key = "scenaristes"
                elif "acteu" in role_filter: role_key = "acteurs"
                elif "diffus" in role_filter: role_key = "diffuseurs"
                
                if role_key and REAL_COLUMNS.get(role_key):
                    target_cols.append(REAL_COLUMNS[role_key])
            
            # Si pas de rôle ou rôle pas trouvé, on cherche partout
            if not target_cols:
                for k in ["realisateurs", "producteurs", "scenaristes", "acteurs"]:
                    if REAL_COLUMNS.get(k): target_cols.append(REAL_COLUMNS[k])

            if target_cols:
                or_clause = " OR ".join([f"{c} ILIKE %s" for c in target_cols])
                query += f" AND ({or_clause})"
                params.extend([f"%{intervenant}%"] * len(target_cols))

        # --- TRI ---
        if title and REAL_COLUMNS.get('titre'):
             query += f" ORDER BY similarity({REAL_COLUMNS['titre']}, %s) DESC"
             params.append(title)
        elif REAL_COLUMNS.get('date'):
             query += f" ORDER BY {REAL_COLUMNS['date']} DESC"

        query += " LIMIT 100"

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Formatage résultats
        results = []
        for row in rows:
            film = dict(row)
            
            # On utilise le mapping inverse pour normaliser les sorties
            # (Pour que le JS s'y retrouve)
            p_col = REAL_COLUMNS.get('plan')
            d_col = REAL_COLUMNS.get('devis')
            
            film["plan_financement"] = normalize_pdf_path(film.get(p_col)) if p_col else ""
            film["devis"] = normalize_pdf_path(film.get(d_col)) if d_col else ""
            
            results.append(film)

        return jsonify(results)

    except Exception as e:
        print(f"❌ CRASH SQL : {e}")
        # IMPORTANT : On renvoie l'erreur au Javascript pour que tu la voies !
        return jsonify({"error": str(e)})

# =============================
# ROUTE PDF
# =============================
@app.route("/get_pdf")
def get_pdf():
    path = request.args.get("path")
    if not path: return "Chemin manquant", 400
    path = urllib.parse.unquote(path)
    
    if path.startswith('http'): target_url = path
    else:
        base = BASE_API.rstrip('/')
        clean_path = path if path.startswith('/') else '/' + path
        target_url = f"{base}{clean_path}"

    if "/documentActe/" in target_url and "/api/" not in target_url:
        target_url = target_url.replace("/rca.frontoffice", "/rca.frontoffice/api")
    
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
        return f"Erreur PDF : {e}", 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)


