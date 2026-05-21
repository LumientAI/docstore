/**
 * Playwright debug script for docstore MCP server responses.
 * Visualises query results as an HTML table in a headless browser.
 *
 * Usage:
 *   node scripts/debug_playwright.js --results results.json
 */

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

async function main() {
  const args = process.argv.slice(2);
  const resultsFlag = args.indexOf("--results");
  const resultsPath =
    resultsFlag !== -1 ? args[resultsFlag + 1] : "query_results.json";

  if (!fs.existsSync(resultsPath)) {
    console.error(`Results file not found: ${resultsPath}`);
    console.error("Run: docstore query <schema> --output json > query_results.json");
    process.exit(1);
  }

  const results = JSON.parse(fs.readFileSync(resultsPath, "utf8"));
  if (!results.length) {
    console.log("No results to display.");
    return;
  }

  const keys = Object.keys(results[0]).filter((k) => k !== "file");
  const rows = results
    .map((r) => {
      const cells = keys.map((k) => `<td>${r[k] ?? ""}</td>`).join("");
      return `<tr><td class="file">${r.file || ""}</td>${cells}</tr>`;
    })
    .join("\n");

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body { font-family: system-ui; padding: 24px; background: #f9f9f7; }
    h1 { font-size: 18px; color: #0B0B0B; margin-bottom: 16px; }
    table { border-collapse: collapse; width: 100%; background: white;
            border-radius: 8px; overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
    th { background: #0B0B0B; color: white; padding: 10px 14px;
         text-align: left; font-size: 12px; font-weight: 500; }
    td { padding: 9px 14px; font-size: 12px; border-bottom: 1px solid #f0f0ef; }
    td.file { color: #6B6B6B; font-family: monospace; font-size: 11px; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #fdf6e3; }
    .count { font-size: 11px; color: #6B6B6B; margin-top: 10px; }
  </style>
</head>
<body>
  <h1>docstore query results</h1>
  <table>
    <thead>
      <tr>
        <th>file</th>
        ${keys.map((k) => `<th>${k}</th>`).join("")}
      </tr>
    </thead>
    <tbody>
      ${rows}
    </tbody>
  </table>
  <p class="count">${results.length} records</p>
</body>
</html>`;

  const htmlPath = path.join(__dirname, "_debug_results.html");
  fs.writeFileSync(htmlPath, html);

  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`file://${htmlPath}`);
  await page.waitForLoadState("networkidle");

  const screenshotPath = path.join(__dirname, "debug_results.png");
  await page.screenshot({ path: screenshotPath, fullPage: true });
  console.log(`Screenshot saved: ${screenshotPath}`);

  await browser.close();
  fs.unlinkSync(htmlPath);
}

main().catch(console.error);
