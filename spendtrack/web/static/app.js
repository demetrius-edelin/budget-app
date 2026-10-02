// Small behaviors: keyboard shortcuts on Review, the fuel hint on Add, the live filters on Expenses,
// the reload on a new day, the trend chart on Reports.
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

  // Expenses: the filters apply as you type. Send only the filters that have a value,
  // so that the address bar shows a short URL.
  document.addEventListener("htmx:configRequest", function (event) {
    if (event.detail.elt.id !== "filters") { return; }
    var params = event.detail.parameters;
    Array.from(params.keys()).forEach(function (name) {
      if (params[name] === "") { delete params[name]; }
    });
  });

  // Overview and Reports: reload after the local midnight, so that "today" moves to the new day.
  // The deadline uses the browser clock plus the server countdown, so a clock difference does not matter.
  // Browsers pause timers in hidden tabs and in sleep, so also check when the tab shows again.
  var reloadIn = document.body.dataset.reloadIn;
  if (reloadIn) {
    var reloadAt = Date.now() + Number(reloadIn);
    var reloadIfNewDay = function () {
      if (Date.now() >= reloadAt) { window.location.reload(); }
    };
    setInterval(reloadIfNewDay, 60000);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") { reloadIfNewDay(); }
    });
    window.addEventListener("pageshow", reloadIfNewDay);
    window.addEventListener("focus", reloadIfNewDay);
  }

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
