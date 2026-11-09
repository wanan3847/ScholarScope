
      try {
        document.documentElement.dataset.theme =
          localStorage.getItem("scholarscope_theme_v2") || "light";
      } catch {}
    