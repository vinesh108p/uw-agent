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

  // Times: show the viewer's own clock (the server text is UTC inside a container). Falls back to the server text.
  const dayFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
  const clockFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  document.querySelectorAll("time[data-when]").forEach((el) => {
    const moment = new Date(el.getAttribute("datetime"));
    if (Number.isNaN(moment.getTime())) return;
    const today = moment.toDateString() === new Date().toDateString();
    el.textContent = `${today ? "today" : dayFmt.format(moment)} at ${clockFmt.format(moment)}`;
  });

  // Pipeline rows open their case.
  document.querySelectorAll("tr[data-href]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (!event.target.closest("a, button")) window.location.href = row.dataset.href;
    });
  });
});
