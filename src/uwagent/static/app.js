// Progressive enhancements only: every page works without JavaScript.
document.addEventListener("DOMContentLoaded", () => {
  // Banners: success notices fade after 6 s; errors stay until dismissed so they are never missed.
  document.querySelectorAll("[data-banner]").forEach((banner) => {
    const close = () => banner.remove();
    banner.querySelector("[data-close]")?.addEventListener("click", close);
    if (banner.dataset.banner === "notice") setTimeout(close, 6000);
  });

  // "Ask broker" with nothing to ask: reopen that card's panel and focus the question field.
  const params = new URLSearchParams(window.location.search);
  if (params.get("error") === "needs_question" && params.get("card")) {
    const panel = document.getElementById(`ask-${params.get("card")}`);
    if (panel) {
      panel.open = true;
      panel.scrollIntoView({ block: "center" });
      panel.querySelector("input, textarea")?.focus();
    }
  }

  // Pipeline rows open their case.
  document.querySelectorAll("tr[data-href]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (!event.target.closest("a, button")) window.location.href = row.dataset.href;
    });
  });
});
