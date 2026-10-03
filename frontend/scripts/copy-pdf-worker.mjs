import { copyFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
const target = fileURLToPath(new URL("../public/vendor/", import.meta.url));
mkdirSync(target, { recursive: true });
copyFileSync(fileURLToPath(new URL("../node_modules/pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url)), target + "/pdf.worker.min.mjs");
