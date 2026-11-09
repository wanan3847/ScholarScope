/* Editorial landing interactions. Product actions link to the live workspace. */
(() => {
  const all = (selector) => [...document.querySelectorAll(selector)];
  const header = document.querySelector(".header");
  const menu = document.querySelector("#menu-toggle");
  const closeMenu = () => {
    header.classList.remove("menu-open");
    menu.setAttribute("aria-expanded", "false");
    menu.setAttribute("aria-label", "展开导航");
  };
  menu.addEventListener("click", () => {
    const open = menu.getAttribute("aria-expanded") !== "true";
    header.classList.toggle("menu-open", open);
    menu.setAttribute("aria-expanded", String(open));
    menu.setAttribute("aria-label", open ? "收起导航" : "展开导航");
  });
  all(".nav-links a").forEach((link) =>
    link.addEventListener("click", closeMenu),
  );
  all(".filter-pill").forEach((button) =>
    button.addEventListener("click", () => {
      const group = button.dataset.filter;
      all(".filter-pill").forEach((b) =>
        b.setAttribute("aria-pressed", String(b === button)),
      );
      let count = 0;
      all(".path-card").forEach((card) => {
        card.hidden = group !== "全部" && card.dataset.category !== group;
        if (!card.hidden) count++;
      });
      document.querySelector("#path-count").textContent =
        `${String(count).padStart(2, "0")} / 05 研究路径`;
      all(".progress-bars i").forEach((el, i) => {
        el.style.opacity = i < count ? "1" : ".18";
      });
    }),
  );
  let scenario = 0;
  const updateScenario = () => {
    const saved = scenario === 1;
    const content = {
      "scenario-label": saved ? "场景 02 / 整理" : "场景 01 / 探索",
      "scenario-title": saved
        ? "把读过的文献，留在课题里"
        : "从综述开始，建立阅读地图",
      "scenario-description": saved
        ? "按课题收藏文献、标记已阅，并将引用导出到后续写作中。"
        : "围绕检索增强生成，阅读基础方法与领域综述，建立第一批课题文献。",
      "scenario-counter": saved ? "02 / 02" : "01 / 02",
      "scenario-card-label": saved
        ? "文献库 / 我的研究线索"
        : "课题 / 检索增强生成",
      "scenario-info": "阅读示意 · 实际结果以检索为准",
      "scenario-open": saved ? "打开文献库 ↗" : "开始检索 ↗",
    };
    Object.entries(content).forEach(([id, text]) => {
      document.getElementById(id).textContent = text;
    });
    const url = saved
      ? "/app#favorites"
      : "/app?q=retrieval%20augmented%20generation%20survey";
    document.querySelector("#scenario-open").href = url;
    document.querySelector(".work-intro .text-link").href = url;
  };
  ["scenario-prev", "scenario-next"].forEach((id) =>
    document.getElementById(id).addEventListener("click", () => {
      scenario = (scenario + 1) % 2;
      updateScenario();
    }),
  );
  // Keep all content visible when observers or reduced motion are unavailable.
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          if (entry.isIntersecting)
            all(".nav-links a").forEach((a) =>
              a.classList.toggle("active", a.hash === "#" + entry.target.id),
            );
        }),
      { rootMargin: "-15% 0px -65% 0px" },
    );
    all("main section[id]").forEach((section) => observer.observe(section));
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      location.assign("/app");
    }
  });
})();
