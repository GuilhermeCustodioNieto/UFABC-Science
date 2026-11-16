// Melhoria progressiva: o conteúdo é totalmente legível sem JavaScript.
(function () {
  "use strict";

  // Filtro do feed por editoria (abas e chips da barra lateral).
  var tabs = document.querySelectorAll(".tab[data-filter]");
  var chips = document.querySelectorAll("button.chip[data-filter]");
  var posts = document.querySelectorAll(".feed .post");
  var empty = document.querySelector("[data-empty]");

  function applyFilter(filter) {
    var shown = 0;
    posts.forEach(function (post) {
      var match = filter === "all" || post.dataset.category === filter;
      post.hidden = !match;
      if (match) shown += 1;
    });
    tabs.forEach(function (tab) {
      tab.setAttribute("aria-selected", String(tab.dataset.filter === filter));
    });
    chips.forEach(function (chip) {
      chip.setAttribute("aria-pressed", String(chip.dataset.filter === filter));
    });
    if (empty) empty.hidden = shown > 0;
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () { applyFilter(tab.dataset.filter); });
  });
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      var next = chip.getAttribute("aria-pressed") === "true" ? "all" : chip.dataset.filter;
      applyFilter(next);
      var feed = document.querySelector(".feed");
      if (feed && window.matchMedia("(max-width: 1000px)").matches) {
        feed.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  // Barra de progresso de leitura.
  var bar = document.querySelector(".read-progress");
  if (bar) {
    var ticking = false;
    var update = function () {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.setProperty("--p", max > 0 ? Math.min(1, window.scrollY / max) : 0);
      ticking = false;
    };
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  if (!navigator.clipboard) return;

  // Copiar link da página.
  document.querySelectorAll("[data-share]").forEach(function (button) {
    var label = button.querySelector(".icon-label");
    button.hidden = false;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(window.location.href).then(function () {
        if (label) label.textContent = "Link copiado";
        setTimeout(function () { if (label) label.textContent = "Copiar link"; }, 2000);
      });
    });
  });

  // Copiar DOI.
  document.querySelectorAll(".facts dd a[href^='https://doi.org/']").forEach(function (link) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = "Copiar";
    button.className = "copy-doi";
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(link.textContent.trim()).then(function () {
        button.textContent = "Copiado";
      });
    });
    link.insertAdjacentElement("afterend", button);
  });
})();
