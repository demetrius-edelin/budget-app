// Small behaviors: keyboard shortcuts on Review, the fuel hint on Add, the trend chart on Reports.
(function () {
  "use strict";

  // Review: keys 1-4, c, r, s and the arrow keys click the matching button.
  document.addEventListener("keydown", function (event) {
    if (event.target.matches("input, select, textarea")) { return; }
    var card = document.querySelector("[data-review-card]");
    if (!card) { return; }
    var button = card.querySelector('[data-key="' + event.key + '"]');
    if (button && !button.disabled) {
      event.preventDefault();
      button.click();
    }
  });

  // Add: show the fuel hint when the Fuel & car category is picked in km mode.
  function updateFuelHint() {
    var select = document.querySelector("[data-fuel-select]");
    var hint = document.getElementById("fuel-hint");
    if (!select || !hint) { return; }
    var option = select.options[select.selectedIndex];
    var show = option && option.dataset.fuel === "1" && hint.dataset.mode !== "receipts";
    hint.classList.toggle("hidden", !show);
  }
  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-fuel-select]")) { updateFuelHint(); }
    if (event.target.matches("[data-toggles]")) {
      var target = document.querySelector(event.target.dataset.toggles);
      if (target) { target.classList.toggle("hidden", !event.target.checked); }
    }
  });
  updateFuelHint();

  // Reports: the 12-month stacked bar chart.
  var data = document.getElementById("trend-data");
  var canvas = document.getElementById("trend-chart");
  if (data && canvas && window.Chart) {
    var parsed = JSON.parse(data.textContent);
    var colors = ["#2f855a", "#3182ce", "#d69e2e", "#c53030", "#a0aec0"];
    parsed.datasets.forEach(function (set, index) { set.backgroundColor = colors[index]; });
    new window.Chart(canvas, {
      type: "bar",
      data: parsed,
      options: {
        responsive: true,
        scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
        plugins: { legend: { position: "bottom" } }
      }
    });
  }
})();
