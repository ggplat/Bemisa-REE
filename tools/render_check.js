#!/usr/bin/env node
/**
 * Checagem de renderização do Dashboard REE v6.
 *
 * Monta cada um dos 5 iframes num DOM real (jsdom) com o D3 de verdade e
 * confere que os 4 gráficos desenham. O alvo principal é o `NaN`: quando um
 * mês existe no dict de preço mas não em `sharesMap`, o JS do frame calcula
 * `mcap = undefined * ... = NaN`, o domínio da escala vira `[0, NaN]` e todo
 * atributo SVG sai como "NaN" — a linha de market cap some sem erro nenhum no
 * console. É exatamente isso que este script pega.
 *
 * Uso: node tools/render_check.js [caminho/do/dashboard.html]
 *
 * Requer `npm install --no-save jsdom d3@7`.
 */
"use strict";

const fs = require("fs");
const path = require("path");

let JSDOM, d3Source;
try {
  ({ JSDOM } = require("jsdom"));
  // O pacote d3 restringe "exports" e não expõe o bundle nem o package.json,
  // então subimos de src/index.js até a raiz do pacote.
  const d3Root = path.resolve(require.resolve("d3"), "..", "..");
  d3Source = fs.readFileSync(path.join(d3Root, "dist", "d3.min.js"), "utf8");
} catch (err) {
  console.error("Dependências ausentes. Rode: npm install --no-save jsdom d3@7");
  console.error(err.message);
  process.exit(2);
}

const FRAME_RE = /id="frame-(\d)"[^>]*srcdoc="(.*?)"><\/iframe>/gs;
const D3_TAG_RE = /<script src="https:\/\/cdnjs\.cloudflare\.com\/[^"]*d3[^"]*"><\/script>/;
const CHART_IDS = ["chart-main", "chart-shares", "chart-ratio", "chart-volume"];
const NUMERIC_ATTRS = ["d", "x", "y", "x1", "x2", "y1", "y2", "cx", "cy",
                       "width", "height", "r", "transform", "points"];

// A ordem importa: `&amp;` por último, senão desfaz o escape dos outros.
function unescapeSrcdoc(s) {
  return s.replace(/&quot;/g, '"')
          .replace(/&gt;/g, ">")
          .replace(/&lt;/g, "<")
          .replace(/&#x27;/g, "'")
          .replace(/&#39;/g, "'")
          .replace(/&amp;/g, "&");
}

function checkFrame(index, innerHtml) {
  const problems = [];

  if (!D3_TAG_RE.test(innerHtml)) {
    problems.push("tag do D3 não encontrada no frame");
  }
  // D3 local no lugar do CDN: a checagem roda offline e não depende de rede.
  // O replacer é uma função de propósito — o bundle do D3 contém sequências
  // como `$&` e `$'`, que numa string de substituição seriam interpretadas
  // como referências de captura e corromperiam o código injetado.
  const html = innerHtml.replace(D3_TAG_RE, () => `<script>${d3Source}</script>`);

  const errors = [];
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    beforeParse(window) {
      // jsdom não faz layout: clientWidth seria 0 e os gráficos sairiam com
      // largura negativa (sem NaN, mas sem sentido). Fixamos uma largura
      // plausível para que a geometria seja comparável à do navegador.
      Object.defineProperty(window.Element.prototype, "clientWidth",
                            { get: () => 1200, configurable: true });
      Object.defineProperty(window.Element.prototype, "clientHeight",
                            { get: () => 800, configurable: true });
      window.addEventListener("error", (e) => errors.push(e.message));
    },
  });

  const doc = dom.window.document;

  for (const id of CHART_IDS) {
    const svg = doc.getElementById(id);
    if (!svg) {
      problems.push(`#${id} não existe no DOM`);
      continue;
    }
    const marks = svg.querySelectorAll("path, rect, circle, line, text");
    if (marks.length === 0) {
      problems.push(`#${id} não desenhou nenhum elemento`);
    }
  }

  let nanCount = 0;
  const nanSamples = [];
  for (const el of doc.querySelectorAll("svg *")) {
    for (const attr of NUMERIC_ATTRS) {
      const value = el.getAttribute(attr);
      if (value && value.includes("NaN")) {
        nanCount++;
        if (nanSamples.length < 3) {
          nanSamples.push(`<${el.tagName} ${attr}="${value.slice(0, 60)}">`);
        }
      }
    }
  }
  if (nanCount > 0) {
    problems.push(`${nanCount} atributo(s) SVG com NaN — ex.: ${nanSamples.join(" ")}`);
  }

  for (const msg of errors) {
    problems.push(`erro de JS em runtime: ${msg}`);
  }

  const drawn = doc.querySelectorAll("svg *").length;
  dom.window.close();
  return { problems, drawn };
}

function main() {
  const target = process.argv[2] ||
    path.join(__dirname, "..", "Dashboard_REE_v6_Q2.html");
  const doc = fs.readFileSync(target, "utf8");

  const frames = [...doc.matchAll(FRAME_RE)];
  if (frames.length !== 5) {
    console.error(`esperados 5 frames, encontrados ${frames.length}`);
    process.exit(1);
  }

  let failed = false;
  for (const match of frames) {
    const index = Number(match[1]);
    const { problems, drawn } = checkFrame(index, unescapeSrcdoc(match[2]));
    if (problems.length === 0) {
      console.log(`  frame-${index}: OK (${drawn} elementos SVG)`);
    } else {
      failed = true;
      console.error(`  frame-${index}: FALHOU`);
      for (const p of problems) console.error(`    - ${p}`);
    }
  }

  if (failed) {
    console.error("checagem de renderização reprovada");
    process.exit(1);
  }
  console.log("renderização OK nos 5 frames");
}

main();
