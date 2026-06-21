#!/usr/bin/env node
// cf_deploy.mjs - one-command live `wrangler deploy` for the mnemo-mcp Worker+Container.
//
// The committed wrangler.jsonc is the source of truth but holds PLACEHOLDERS so no
// live resource IDs land in this public repo:
//   <YOUR_ACCOUNT_ID>        -> CF account that owns the managed container registry
//   <mnemo-kv-namespace-id>  -> KV namespace id (creds store)
//   <mnemo-d1-database-id>    -> D1 database id (memories store)
// This script fills those in at deploy time into a temp config, then runs
// `wrangler deploy --config <temp>`. It never edits the committed wrangler.jsonc.
//
// Resolution order for each placeholder (first hit wins):
//   1. env var  (CLOUDFLARE_ACCOUNT_ID / MNEMO_KV_ID / MNEMO_D1_ID)
//   2. the gitignored wrangler.deploy.jsonc (real IDs, maintained out-of-band)
// CLOUDFLARE_ACCOUNT_ID is the one the maintainer always exports; the KV/D1 ids are
// normally picked up from wrangler.deploy.jsonc so a deploy is just:
//
//   export CLOUDFLARE_API_TOKEN=...           # CF API token (any secret manager)
//   export CLOUDFLARE_ACCOUNT_ID=<account>    # substitutes <YOUR_ACCOUNT_ID>
//   npm run cf:deploy                          # config-only redeploy
//
// This is config-only: it reuses the already-pushed container image tag and the
// secrets already set via `wrangler secret put`. To swap the image tag, set
// MNEMO_IMAGE_TAG=<tag> (default: keep whatever wrangler.jsonc / deploy.jsonc points at).
// For the full build + push + canary + rollback flow, use scripts/deploy_cf.py.

import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(repo, "wrangler.jsonc");
const DEPLOY = join(repo, "wrangler.deploy.jsonc");

// Strip full-line // comments + trailing commas so JSON.parse accepts the jsonc.
// (inline // after a value is left alone so it never corrupts https:// URLs).
function parseJsonc(text) {
  const body = text
    .split("\n")
    .filter((ln) => !/^\s*\/\//.test(ln))
    .join("\n")
    .replace(/,(\s*[}\]])/g, "$1");
  return JSON.parse(body);
}

function fromDeployConfig() {
  // Best-effort: read real IDs from the gitignored deploy.jsonc if it exists.
  try {
    const cfg = parseJsonc(readFileSync(DEPLOY, "utf8"));
    const imageRef = cfg.containers?.[0]?.image ?? "";
    const acct = imageRef.match(/registry\.cloudflare\.com\/([0-9a-f]+)\//)?.[1];
    return {
      account: acct,
      kv: cfg.kv_namespaces?.[0]?.id,
      d1: cfg.d1_databases?.[0]?.database_id,
      imageTag: imageRef.split(":").pop(),
    };
  } catch {
    return {};
  }
}

const deploy = fromDeployConfig();

const account = process.env.CLOUDFLARE_ACCOUNT_ID || deploy.account;
const kvId = process.env.MNEMO_KV_ID || deploy.kv;
const d1Id = process.env.MNEMO_D1_ID || deploy.d1;
const imageTag = process.env.MNEMO_IMAGE_TAG || deploy.imageTag || "beta";

const missing = [];
if (!account) missing.push("CLOUDFLARE_ACCOUNT_ID (or wrangler.deploy.jsonc)");
if (!kvId) missing.push("MNEMO_KV_ID (or wrangler.deploy.jsonc)");
if (!d1Id) missing.push("MNEMO_D1_ID (or wrangler.deploy.jsonc)");
if (missing.length) {
  console.error("cf:deploy: cannot resolve required IDs:\n  - " + missing.join("\n  - "));
  process.exit(1);
}

let text = readFileSync(SRC, "utf8")
  .replaceAll("<YOUR_ACCOUNT_ID>", account)
  .replaceAll("<mnemo-kv-namespace-id>", kvId)
  .replaceAll("<mnemo-d1-database-id>", d1Id)
  // pin the image tag (config-only redeploy reuses an already-pushed tag)
  .replace(
    /("image":\s*"registry\.cloudflare\.com\/[^/]+\/mnemo-mcp):[^"]+(")/,
    `$1:${imageTag}$2`,
  );

// The temp config lives in tmpdir, so wrangler would resolve the relative
// "main"/"migrations_dir" against tmpdir and miss src/worker.ts. Anchor "main"
// to the repo (JSON-escape the Windows backslashes) and pass --cwd so all other
// relative paths (migrations) resolve from the repo too.
const mainAbs = join(repo, "src", "worker.ts").replaceAll("\\", "\\\\");
text = text.replace(/("main":\s*")[^"]+(")/, `$1${mainAbs}$2`);

// MNEMO_SKIP_ROUTES=1 drops the "routes" (custom_domain) block. The custom domain
// is claimed once at first deploy; a config-only redeploy of an already-live
// Worker should not re-assert it, which avoids needing a zone-scoped
// Workers-Routes:Edit permission on the deploy token (the account-scoped token
// used for the container/bundle update typically lacks it).
if (process.env.MNEMO_SKIP_ROUTES === "1") {
  text = text.replace(/^\s*"routes":\s*\[[^\]]*\],?\s*$/m, "");
}

const tmp = join(mkdtempSync(join(tmpdir(), "mnemo-cf-")), "wrangler.deploy.jsonc");
writeFileSync(tmp, text, "utf8");

// Invoke the project-local wrangler JS entry with the current node binary (no
// shell, no .cmd shim -> works the same on POSIX and Windows, and args with
// spaces are passed verbatim). Falls back to `npx wrangler` if not installed
// locally.
const wranglerArgs = ["deploy", "--config", tmp, "--cwd", repo, ...process.argv.slice(2)];
const localEntry = join(repo, "node_modules", "wrangler", "bin", "wrangler.js");
const [bin, args] = existsSync(localEntry)
  ? [process.execPath, [localEntry, ...wranglerArgs]]
  : ["npx", ["wrangler", ...wranglerArgs]];
console.error("cf:deploy: deploying mnemo-mcp container image");
console.error(`cf:deploy: wrangler ${wranglerArgs.join(" ")}`);
execFileSync(bin, args, { stdio: "inherit", cwd: repo });
