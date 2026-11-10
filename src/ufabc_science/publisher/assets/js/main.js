// Melhoria progressiva opcional: o conteúdo é totalmente legível sem JavaScript.
// Adiciona um botão para copiar o DOI quando a API de área de transferência existe.
(function () {
  "use strict";
  if (!navigator.clipboard) return;
  document.querySelectorAll(".facts dd a[href^='https://doi.org/']").forEach(function (link) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = "Copiar DOI";
    button.className = "copy-doi";
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(link.textContent.trim()).then(function () {
        button.textContent = "DOI copiado";
      });
    });
    link.insertAdjacentElement("afterend", button);
  });
})();
