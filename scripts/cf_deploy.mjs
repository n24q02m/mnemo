#!/usr/bin/env node
// scripts/cf_deploy.mjs - Bring-your-own Cloudflare deploy for mnemo-mcp.
//
// The committed base wrangler.jsonc ships <PLACEHOLDER> tokens so it stays generic
// (account / KV / D1 IDs, PUBLIC_URL, and the custom-domain route). This script
// renders those tokens from your own environment into a runnable config, then runs
// `wrangler deploy`. It backs the `cf:deploy` npm script.
//
// The maintainer CD path is separate: scripts/deploy_cf.py builds + pushes the
// container image and deploys from the gitignored wrangler.deploy.jsonc (real IDs),
// so it is unaffected by this script or by the base placeholders.
//
// Prerequisites (see README "Deploy to Cloudflare"): `wrangler login`, provision
// the D1 / Vectorize / KV bindings, and push the container image to your Cloudflare
// managed registry.
//
// Usage:
//   CLOUDFLARE_ACCOUNT_ID=... CF_KV_ID=... CF_D1_ID=... PUBLIC_URL=https://mnemo.example.com \
//     node scripts/cf_deploy.mjs
//   ... node scripts/cf_deploy.mjs --dry-run   # render + validate without deploying
//
// Any extra CLI args (e.g. --dry-run) are forwarded to `wrangler deploy`.

import { spawnSync } from "node:child_process";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const BASE_CONFIG = join(repoRoot, "wrangler.jsonc");
// Rendered config holds real resource IDs -> gitignored, and removed after deploy.
const RENDERED_CONFIG = join(repoRoot, ".wrangler.byo.jsonc");

function requireEnv(name, hint) {
  const val = process.env[name];
  if (!val) {
    console.error(`${name} is not set (${hint}).`);
    process.exit(1);
  }
  return val;
}

const accountId = requireEnv(
  "CLOUDFLARE_ACCOUNT_ID",
  "base wrangler.jsonc image uses <YOUR_ACCOUNT_ID>",
);
const kvId = requireEnv(
  "CF_KV_ID",
  "base wrangler.jsonc KV binding uses <mnemo-kv-namespace-id>",
);
const d1Id = requireEnv(
  "CF_D1_ID",
  "base wrangler.jsonc D1 binding uses <mnemo-d1-database-id>",
);
const publicUrl = requireEnv(
  "PUBLIC_URL",
  "base wrangler.jsonc vars + routes use <YOUR_PUBLIC_URL> / <YOUR_WORKER_DOMAIN>",
);

// The custom-domain route is the host of PUBLIC_URL (a BYO instance is served at
// the same host it advertises), so no separate env var is needed for it.
let workerDomain;
try {
  workerDomain = new URL(publicUrl).host;
} catch {
  console.error(`PUBLIC_URL is not a valid URL: ${publicUrl}`);
  process.exit(1);
}

let substituted = readFileSync(BASE_CONFIG, "utf8");
substituted = substituted.split("<YOUR_ACCOUNT_ID>").join(accountId);
substituted = substituted.split("<mnemo-kv-namespace-id>").join(kvId);
substituted = substituted.split("<mnemo-d1-database-id>").join(d1Id);
substituted = substituted.split("<YOUR_PUBLIC_URL>").join(publicUrl);
substituted = substituted.split("<YOUR_WORKER_DOMAIN>").join(workerDomain);

// Fail loudly if any placeholder survived (e.g. a new <...> token added to the base
// config without a matching substitution here) so a literal <...> never reaches
// wrangler and silently deploys a broken config.
const leftover = substituted.match(/<[A-Za-z0-9_-]+>/g);
if (leftover) {
  console.error(
    `Unsubstituted placeholder(s) in rendered config: ${[...new Set(leftover)].join(", ")}`,
  );
  process.exit(1);
}

writeFileSync(RENDERED_CONFIG, substituted);
try {
  const passthrough = process.argv.slice(2);
  // Run as a single shell string (not args + shell:true, which trips DEP0190) so the
  // platform shell resolves npx (npx.cmd on Windows, npx on POSIX). Only the config
  // path is quoted; the passthrough flags are the caller's own simple wrangler args.
  const cmd = [`npx wrangler deploy --config "${RENDERED_CONFIG}"`, ...passthrough].join(" ");
  console.log(`$ ${cmd}`);
  const res = spawnSync(cmd, { cwd: repoRoot, stdio: "inherit", shell: true });
  if (res.error) {
    console.error(`Failed to run wrangler via npx: ${res.error.message}`);
    process.exitCode = 1;
  } else {
    process.exitCode = res.status ?? 1;
  }
} finally {
  rmSync(RENDERED_CONFIG, { force: true });
}
