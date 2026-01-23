console.log("JS chargé");

// ----------------------
// 1. MENU BURGER
// ----------------------
const burger = document.querySelector(".burger");
const menu = document.querySelector(".menu");

if (burger && menu) {
  burger.addEventListener("mouseenter", () => {
    menu.classList.add("show");
  });

  menu.addEventListener("mouseleave", () => {
    menu.classList.remove("show");
  });
}

// ----------------------
// 2. UTILITAIRES (Similitude & Gestion Données)
// ----------------------

// Fonction intelligente pour récupérer une donnée même si le nom de la colonne change
// (Ex: SQL renvoie parfois 'date_immatriculation' et parfois 'dateimmatriculation')
const getData = (film, keys) => {
    for (let key of keys) {
        if (film[key] && film[key] !== 'None' && film[key] !== 'NaN' && film[key] !== 'null') {
            return film[key];
        }
    }
    return null;
};

function similarity(a, b) {
  if (!a || !b) return 0;
  a = a.toLowerCase();
  b = b.toLowerCase();
  let longer = a.length > b.length ? a : b;
  let shorter = a.length > b.length ? b : a;
  let longerLength = longer.length;
  if (longerLength === 0) return 1.0;
  return (
    (longerLength - editDistance(longer, shorter)) / parseFloat(longerLength)
  );
}

function editDistance(a, b) {
  const costs = [];
  for (let i = 0; i <= a.length; i++) {
    let lastValue = i;
    for (let j = 0; j <= b.length; j++) {
      if (i === 0) costs[j] = j;
      else if (j > 0) {
        let newValue = costs[j - 1];
        if (a.charAt(i - 1) !== b.charAt(j - 1))
          newValue = Math.min(Math.min(newValue, lastValue), costs[j]) + 1;
        costs[j - 1] = lastValue;
        lastValue = newValue;
      }
    }
    if (i > 0) costs[b.length] = lastValue;
  }
  return costs[b.length];
}

// ----------------------
// 3. AFFICHAGE DES RÉSULTATS (NOUVEAU DESIGN)
// ----------------------
function renderResults(films) {
  const container = document.querySelector(".results-container");
  container.innerHTML = "";

  if (!films.length) {
    container.innerHTML = '<p style="text-align:center; margin-top:20px;">Aucun résultat trouvé.</p>';
    return;
  }

  films.forEach((film) => {
    const card = document.createElement("div");
    card.className = "film-card";

    // --- A. Récupération sécurisée des données ---
    const titre = film.titre || "Titre inconnu";
    // On cherche la date dans plusieurs colonnes possibles
    const date = getData(film, ['dateimmatriculation', 'date_immatriculation', 'dateImmatriculation']);
    const budget = getData(film, ['budget', 'devis', 'devis_global']);
    const prod = getData(film, ['production', 'producteur_delegue', 'nationalite', 'pays']);
    const genre = getData(film, ['genre', 'categorie', 'type_de_metrage', 'typemetrage']);
    const synopsis = getData(film, ['synopsis_tmdb', 'synopsis']) || "Synopsis non disponible.";

    // Intervenants
    const real = getData(film, ['realisateurs', 'realisateur', 'realisateur_s']);
    const scenar = getData(film, ['scenaristes', 'scenariste', 'scenariste_s']);
    const product = getData(film, ['producteurs', 'producteur', 'producteur_s']);
    const cast = getData(film, ['acteurs', 'acteur', 'acteur_s']);

    // --- B. Construction HTML de la liste des intervenants ---
    let intervenantsHTML = '';
    // On n'affiche le bloc que s'il y a au moins une info
    if (real || scenar || product || cast) {
        intervenantsHTML += '<div class="intervenants-list">';
        if (real) intervenantsHTML += `<div class="role-line"><span class="role-label">Réalisation :</span> <span class="role-value">${real}</span></div>`;
        if (scenar) intervenantsHTML += `<div class="role-line"><span class="role-label">Scénario :</span> <span class="role-value">${scenar}</span></div>`;
        if (product) intervenantsHTML += `<div class="role-line"><span class="role-label">Production :</span> <span class="role-value">${product}</span></div>`;
        if (cast) intervenantsHTML += `<div class="role-line"><span class="role-label">Casting :</span> <span class="role-value">${cast}</span></div>`;
        intervenantsHTML += '</div>';
    }

    // --- C. Construction des boutons PDF ---
    let buttonsHTML = '<div class="actions">';
    if (film.plan_financement) {
        buttonsHTML += `<a href="/get_pdf?path=${encodeURIComponent(film.plan_financement)}" 
                           class="btn-pdf" 
                           target="_blank" 
                           title="Consulter les annexes 1 et 2">
                           <i class="fas fa-file-pdf"></i> Plan de financement
                        </a>`;
    }
    if (film.devis) {
        buttonsHTML += `<a href="/get_pdf?path=${encodeURIComponent(film.devis)}" 
                           class="btn-pdf secondary" 
                           target="_blank" 
                           title="Détail en fin de document">
                           <i class="fas fa-file-invoice-dollar"></i> Devis
                        </a>`;
    }
    buttonsHTML += '</div>';

    // --- D. Assemblage de la carte ---
    card.innerHTML = `
      <div class="film-header">
        <h2>${titre}</h2>
        ${date ? `<span class="date-badge"><i class="far fa-calendar-alt"></i> ${date}</span>` : ''}
      </div>

      <p class="meta">
        ${genre ? `<span>${genre}</span>` : ''} 
        ${budget ? ` &nbsp;|&nbsp; <span><i class="fas fa-coins"></i> Budget: ${budget}</span>` : ''}
      </p>

      ${intervenantsHTML}

      <p class="synopsis">${synopsis}</p>

      ${buttonsHTML}
    `;

    container.appendChild(card);
  });
}

// ----------------------
// 4. GESTION DU FORMULAIRE
// ----------------------
const form = document.getElementById("search-form");

if (!form) {
  console.error("Formulaire introuvable");
} else {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    // Récupération des valeurs
    const title = document.getElementById("title")?.value.trim() || "";
    const year = document.getElementById("year")?.value || "";
    const type = document.getElementById("type")?.value || "";
    const budget = document.getElementById("budget")?.value || "";
    const intervenant = document.getElementById("intervenant")?.value.trim() || "";
    const role = document.getElementById("role")?.value || "";
    const keywords = document.getElementById("keywords")?.value.trim() || "";
    const production = document.getElementById("production")?.value || "";
    const genre = document.getElementById("genre")?.value || "";

    // Construction de l'URL
    const params = new URLSearchParams();

    if (title) params.append("title", title);
    if (year) params.append("year", year);
    if (type) params.append("type", type);
    if (budget) params.append("budget", budget);
    if (keywords) params.append("keywords", keywords);
    if (production) params.append("production", production);
    if (genre) params.append("genre", genre);
    
    if (intervenant) {
      params.append("intervenant", intervenant);
      if (role) params.append("role", role);
    }

    // Appel au serveur
    try {
        const response = await fetch(`/search?${params.toString()}`);
        let films = await response.json();

        // Tri client (Bonus : met en avant ceux qui ont un plan de financement)
        films.forEach((film) => {
            film._score = 0;
            if (film.plan_financement) film._score += 5;
            // Si recherche par titre, on affine le tri SQL avec le tri JS
            if (title) {
                film._score += similarity(title, film.titre) * 10;
            }
        });

        // On trie par score descendant
        films.sort((a, b) => b._score - a._score);

        renderResults(films);

    } catch (error) {
        console.error("Erreur lors de la recherche:", error);
    }
  });
}
