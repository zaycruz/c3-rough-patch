#!/usr/bin/env node
// Browser E2E for the demo page: loads it in headless Chromium, fails on any page error,
// checks roster, panel, charts, reveal and metrics, saves runs/demo-page.png and runs/page-check-latest.json.
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = (process.argv[2] || "https://c3-rough-patch.zay-259.workers.dev").replace(/\/$/, "");
const errors = [];
const checks = [];
const check = (name, ok, info) => checks.push({ name, ok: !!ok, ...(info !== undefined ? { info } : {}) });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.goto(BASE + "/demo.html", { waitUntil: "networkidle" });
  await page.waitForSelector(".tile");
  check("roster renders 60 tiles", (await page.locator(".tile").count()) === 60);
  await page.waitForSelector("#panel .ev");
  check("panel shows evidence", (await page.locator("#panel .ev").count()) > 0);
  check("panel shows recommendations", (await page.locator("#panel .rec").count()) > 0);
  check("panel draws 8 charts", (await page.locator("#panel .chart svg").count()) === 8);
  await page.locator('.tile[data-id="c3-P02836"]').click();
  await page.waitForFunction(() => document.querySelector("#panel h2")?.textContent.includes("P02836"));
  await page.locator("#reveal").click();
  const outcome = await page.locator("#outcome").innerText();
  check("reveal shows what happened next", /Rough patch/.test(outcome), outcome);
  await page.waitForSelector("#metrics table");
  check("metrics table has 4 methods", (await page.locator("#metrics tr").count()) === 5);
  mkdirSync("runs", { recursive: true });
  await page.screenshot({ path: "runs/demo-page.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  check("no horizontal scroll at phone width", await page.evaluate(() => document.documentElement.scrollWidth <= 391));
  await page.screenshot({ path: "runs/demo-page-phone.png", fullPage: false });
} finally {
  await browser.close();
}
check("no page errors", errors.length === 0, errors);
const passed = checks.every((c) => c.ok);
writeFileSync("runs/page-check-latest.json", JSON.stringify({ base: BASE, ranAt: new Date().toISOString(), passed, checks }, null, 2));
for (const c of checks) console.log(`${c.ok ? "PASS" : "FAIL"}  ${c.name}${c.info !== undefined ? "  " + JSON.stringify(c.info) : ""}`);
console.log(passed ? "ALL PASSED" : "FAILED");
process.exit(passed ? 0 : 1);
