// Bundle budget gate.
//
// A timeline that streams events forever, plus a chart library, is exactly the kind of app
// that quietly ships a megabyte of JavaScript. This makes the cost visible in CI instead of
// discovering it after a release.
//
// Usage: node scripts/check-bundle-size.mjs [--budget-kb 300]
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const ASSETS = "apps/web/dist/assets";
const budgetArg = process.argv.indexOf("--budget-kb");
const BUDGET_KB = budgetArg === -1 ? 300 : Number(process.argv[budgetArg + 1]);

let names;
try {
  names = readdirSync(ASSETS);
} catch {
  console.error(`no build output at ${ASSETS} — run \`npm run build\` first.`);
  process.exit(1);
}

const scripts = names.filter((name) => name.endsWith(".js"));
if (scripts.length === 0) {
  console.error(`no JavaScript bundles found in ${ASSETS}.`);
  process.exit(1);
}

let failed = false;
let total = 0;
for (const name of scripts.sort()) {
  const gzipped = gzipSync(readFileSync(join(ASSETS, name))).length;
  const kb = Math.round(gzipped / 1024);
  total += kb;
  const ok = kb <= BUDGET_KB;
  if (!ok) {
    failed = true;
  }
  console.log(`${ok ? "  ok" : "FAIL"}  ${name.padEnd(34)} ${String(kb).padStart(5)} kB gzip`);
}

console.log(`\ntotal ${total} kB gzip across ${scripts.length} bundle(s); budget ${BUDGET_KB} kB each`);
process.exit(failed ? 1 : 0);
