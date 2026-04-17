(function () {
  const page = document.body.getAttribute("data-page") || "";
  const ctaText = document.body.getAttribute("data-nav-cta-text") || "GitHub Repo";
  const ctaHref =
    document.body.getAttribute("data-nav-cta-href") ||
    "https://github.com/d2i-cuhksz/MicroWorld";
  const ctaTarget = document.body.getAttribute("data-nav-cta-target") || "";

  function activeClass(name) {
    return page === name ? ' class="active"' : "";
  }

  function icon(name) {
    const icons = {
      home:
        '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"></path><path d="M5 9.5V20h14V9.5"></path></svg>',
      architecture:
        '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 3 8l9 5 9-5-9-5Z"></path><path d="m3 12 9 5 9-5"></path><path d="m3 16 9 5 9-5"></path></svg>',
      guide:
        '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 0 4 22V5.5Z"></path><path d="M8 7h7"></path><path d="M8 11h7"></path></svg>',
      examples:
        '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8L12 3Z"></path><path d="m18.5 15 1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1 1-2.5Z"></path></svg>',
      repo:
        '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m8 8-4 4 4 4"></path><path d="m16 8 4 4-4 4"></path><path d="m14 4-4 16"></path></svg>',
    };
    return icons[name] || "";
  }

  const nav = document.getElementById("main-nav");
  if (nav) {
    const targetAttr = ctaTarget ? ` target="${ctaTarget}" rel="noreferrer"` : "";
    nav.outerHTML = `
      <nav>
        <div class="nav-inner">
          <a href="index.html" class="nav-brand" aria-label="MicroWorld home">
            <img class="nav-logo-image" src="./assets/logo.png" alt="MicroWorld logo" />
          </a>
          <ul class="nav-links">
            <li><a href="index.html"${activeClass("home")}><span class="nav-link-inner">${icon("home")}<span>Home</span></span></a></li>
            <li><a href="architecture.html"${activeClass("architecture")}><span class="nav-link-inner">${icon("architecture")}<span>Architecture</span></span></a></li>
            <li><a href="guide.html"${activeClass("guide")}><span class="nav-link-inner">${icon("guide")}<span>User Guide</span></span></a></li>
            <li><a href="examples.html"${activeClass("examples")}><span class="nav-link-inner">${icon("examples")}<span>Examples</span></span></a></li>
          </ul>
          <a href="${ctaHref}" class="nav-cta"${targetAttr}>${icon("repo")}<span>${ctaText}</span></a>
        </div>
      </nav>
    `;
  }

  const footer = document.getElementById("main-footer");
  if (footer) {
    footer.outerHTML = `
      <footer>
        <div class="footer-inner">
          <div class="footer-brand">MicroWorld</div>
          <p class="footer-desc">
            A lightweight multi-modal social simulation engine for event analysis,
            topology-aware runtime scheduling, memory-efficient execution, and
            report generation.
          </p>
          <hr class="footer-divider" />
          <div class="footer-bottom">
            <p>GitHub Pages project site for the MicroWorld repository.</p>
            <p>2026 MicroWorld Project</p>
          </div>
        </div>
      </footer>
    `;
  }
})();
