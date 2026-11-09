import { execFileSync } from "node:child_process";
import { copyFileSync, cpSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
const repo = fileURLToPath(new URL("../", import.meta.url));
execFileSync("npm", ["run", "build"], {
  cwd: repo + "frontend",
  stdio: "inherit",
});
copyFileSync(
  repo + "src/web/static/ui/index.html",
  repo + "src/web/templates/app.html",
);
copyFileSync(
  repo + "frontend/landing.html",
  repo + "src/web/templates/index.html",
);
rmSync(repo + "src/web/static/brand", { recursive: true, force: true });
mkdirSync(repo + "src/web/static/brand", { recursive: true });
cpSync(repo + "frontend/public/brand", repo + "src/web/static/brand", {
  recursive: true,
});
for (const asset of ["cmaps", "standard_fonts", "wasm"]) {
  mkdirSync(repo + "src/web/static/pdfjs/" + asset, { recursive: true });
  cpSync(
    repo + "frontend/node_modules/pdfjs-dist/" + asset,
    repo + "src/web/static/pdfjs/" + asset,
    { recursive: true },
  );
}
console.log("Landing installed at /; research workspace installed at /app.");
