(function () {
  const page = document.body.getAttribute("data-page") || "";
  const ctaText = document.body.getAttribute("data-nav-cta-text") || "GitHub Repo";
  const ctaHref =
    document.body.getAttribute("data-nav-cta-href") ||
    "https://github.com/d2i-cuhksz/LightWorld";
  const ctaTarget = document.body.getAttribute("data-nav-cta-target") || "";

  function activeClass(name) {
    return page === name ? ' class="active"' : "";
  }

  const nav = document.getElementById("main-nav");
  if (nav) {
    const targetAttr = ctaTarget ? ` target="${ctaTarget}" rel="noreferrer"` : "";
    nav.outerHTML = `
      <nav>
        <div class="nav-inner">
          <a href="index.html" class="nav-brand">
            <span class="nav-logo">LW</span>
            LightWorld
          </a>
          <ul class="nav-links">
            <li><a href="index.html"${activeClass("home")}>Home</a></li>
            <li><a href="architecture.html"${activeClass("architecture")}>Architecture</a></li>
            <li><a href="video.html"${activeClass("video")}>Video</a></li>
            <li><a href="guide.html"${activeClass("guide")}>User Guide</a></li>
            <li><a href="examples.html"${activeClass("examples")}>Examples</a></li>
          </ul>
          <a href="${ctaHref}" class="nav-cta"${targetAttr}>${ctaText}</a>
        </div>
      </nav>
    `;
  }

  const footer = document.getElementById("main-footer");
  if (footer) {
    footer.outerHTML = `
      <footer>
        <div class="footer-inner">
          <div class="footer-brand">LightWorld</div>
          <p class="footer-desc">
            A lightweight multi-modal social simulation engine for event analysis,
            topology-aware runtime scheduling, memory-efficient execution, and
            report generation.
          </p>
          <hr class="footer-divider" />
          <div class="footer-bottom">
            <p>GitHub Pages project site for the LightWorld repository.</p>
            <p>2026 LightWorld Project</p>
          </div>
        </div>
      </footer>
    `;
  }
})();
