console.log("JS chargé");

const burger = document.querySelector(".burger");
const menu = document.querySelector(".menu");

if (burger && menu) {
  burger.addEventListener("mouseenter", () => menu.classList.add("show"));
  menu.addEventListener("mouseleave", () => menu.classList.remove("show"));
}

function similarity(a, b) {
  if (!a || !b) return 0;
  a = a.toLowerCase(); b = b.toLowerCase();
  let longer = a.length > b.length ? a : b;
  let shorter = a.length > b.length ? b : a;
  let longerLength = longer.length;
  if (longerLength === 0) return 1.0;
  return (longerLength - editDistance(longer, shorter)) / parseFloat(longerLength);
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

function renderResults(films, searchedTitle) {
  const container = document.querySelector(".results-container");
  container.innerHTML = "";

  if (!films || !films.length) {
    container.innerHTML = "<p>Aucun résultat trouvé.</p>";
    return;
  }

  films.forEach((film) => {
    const card = document.createElement("div");
    card.className = "film-card";

    // --- CORRECTION CLÉ : On accepte plusieurs orthographes pour l'affichage ---
    // PostgreSQL renvoie souvent en minuscule, le JS attendait du CamelCase
    const date = film.dateimmatriculation || film.date_immatriculation || film.dateImmatriculation || "—";
    const type = film.typemetrage || film.type_de_metrage || film.typeMetrage || "—";
    const synopsis = film.synopsis_tmdb || film.synopsis || "Synopsis non disponible.";

    card.innerHTML = `
      <div class="film-header">
        <h2>${film.titre || "Titre inconnu"}</h2>
        ${film.plan_financement ? `<span class="badge-plan">Plan de financement</span>` : ""}
      </div>

      <p class="meta">
        ${type} · ${date} ·
        Budget : ${film.budget ? Number(film.budget.replace(/[^0-9.]/g, '')).toLocaleString("fr-FR") + " €" : "NC"}
      </p>

      <p class="synopsis">${synopsis}</p>

      <div class="actions">
        ${film.plan_financement ? `<a href="/get_pdf?path=${encodeURIComponent(film.plan_financement)}" class="btn-pdf" target="_blank">Plan de financement</a>` : ""}
        ${film.devis ? `<a href="/get_pdf?path=${encodeURIComponent(film.devis)}" class="btn-pdf secondary" target="_blank">Devis</a>` : ""}
      </div>
    `;
    container.appendChild(card);
  });
}

const form = document.getElementById("search-form");
if (form) {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = document.getElementById("title")?.value.trim() || "";
    const year = document.getElementById("year")?.value || "";
    const type = document.getElementById("type")?.value || "";
    const budget = document.getElementById("budget")?.value || "";
    const intervenant = document.getElementById("intervenant")?.value.trim() || "";
    const role = document.getElementById("role")?.value || "";
    const keywords = document.getElementById("keywords")?.value.trim() || "";
    const production = document.getElementById("production")?.value || "";
    const genre = document.getElementById("genre")?.value || "";

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

    try {
        const response = await fetch(`/search?${params.toString()}`);
        let data = await response.json();

        // --- GESTION DES ERREURS SQL ---
        if (data.error) {
            alert("Erreur Technique (SQL) : " + data.error);
            console.error(data.error);
            return;
        }

        let films = data;

        films.forEach((film) => {
          film._score = 0;
          if (film.plan_financement) film._score += 5;
          if (title) film._score += similarity(title, film.titre) * 10;
        });

        films.sort((a, b) => b._score - a._score);
        renderResults(films, title);

    } catch (err) {
        console.error("Erreur Fetch:", err);
    }
  });
}
