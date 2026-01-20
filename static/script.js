console.log("JS chargé");

// ----------------------
// Burger menu
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
// Utils
// ----------------------
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
// Render results
// ----------------------
function renderResults(films, searchedTitle) {
  const container = document.querySelector(".results-container");
  container.innerHTML = "";

  if (!films.length) {
    container.innerHTML = "<p>Aucun résultat trouvé.</p>";
    return;
  }

  films.forEach((film) => {
    const card = document.createElement("div");
    card.className = "film-card";

    card.innerHTML = `
      <div class="film-header">
        <h2>${film.titre || "Titre inconnu"}</h2>
        ${
          film.plan_financement
            ? `<span class="badge-plan">Plan de financement</span>`
            : ""
        }
      </div>

      <p class="meta">
        ${film.typeMetrage || "—"} ·
        ${film.dateImmatriculation || "—"} ·
        Budget :
        ${
          film.budget
            ? Number(film.budget).toLocaleString("fr-FR") + " €"
            : "NC"
        }
      </p>

      <p class="synopsis">
        ${film.synopsis_tmdb || "Synopsis non disponible."}
      </p>

      <div class="actions">
        ${
          film.plan_financement
            ? `<a href="/get_pdf?path=${encodeURIComponent(
                film.plan_financement
              )}" class="btn-pdf">Plan de financement</a>`
            : ""
        }
        ${
          film.devis
            ? `<a href="/get_pdf?path=${encodeURIComponent(
                film.devis
              )}" class="btn-pdf secondary">Devis</a>`
            : ""
        }
      </div>
    `;

    container.appendChild(card);
  });
}

// ----------------------
// Form submit
// ----------------------
const form = document.getElementById("search-form");

if (!form) {
  console.error("Formulaire introuvable");
} else {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const title = document.getElementById("title")?.value.trim() || "";
    const year = document.getElementById("year")?.value || "";
    const type = document.getElementById("type")?.value || "";
    const budget = document.getElementById("budget")?.value || "";
    const intervenant =
      document.getElementById("intervenant")?.value.trim() || "";
    const role = document.getElementById("role")?.value || "";
    const keywords = document.getElementById("keywords")?.value.trim() || "";

    // NOUVEAUX FILTRES
    const production = document.getElementById("production")?.value || "";
    const genre = document.getElementById("genre")?.value || "";

    const params = new URLSearchParams();

    if (title) params.append("title", title);
    if (year) params.append("year", year);
    if (type) params.append("type", type);
    if (budget) params.append("budget", budget);
    if (keywords) params.append("keywords", keywords);

    // AJOUT DES NOUVEAUX FILTRES
    if (production) params.append("production", production);
    if (genre) params.append("genre", genre);

    // ⚠️ rôle uniquement si intervenant présent
    if (intervenant) {
      params.append("intervenant", intervenant);
      if (role) params.append("role", role);
    }

    const response = await fetch(`/search?${params.toString()}`);
    let films = await response.json();

    // ----------------------
    // TRI DES RÉSULTATS
    // ----------------------

    films.forEach((film) => {
      film._score = 0;

      // priorité plan de financement
      if (film.plan_financement) film._score += 5;

      // similarité du titre
      if (title) {
        film._score += similarity(title, film.titre) * 10;
      }
    });

    films.sort((a, b) => b._score - a._score);

    renderResults(films, title);
  });
}
