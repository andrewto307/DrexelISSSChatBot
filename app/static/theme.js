(function () {
  var choice = "system";
  try {
    var stored = window.localStorage.getItem("isss.theme");
    if (stored === "light" || stored === "dark") {
      choice = stored;
    }
  } catch (error) {}
  var dark = choice === "dark" || (choice === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  document.documentElement.setAttribute("data-theme-choice", choice);
})();
