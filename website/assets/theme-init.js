/* Apply saved/OS preference before first paint to avoid light/dark flash. */
(() => {
  let stored;
  try { stored = localStorage.getItem("jobops-theme"); } catch {}
  const preferred = stored === "light" || stored === "dark"
    ? stored
    : (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  document.documentElement.dataset.theme = preferred;
})();
