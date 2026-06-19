# CHANGELOG

<!-- version list -->

## v2.3.0-beta.17 (2026-06-19)

### Bug Fixes

- Bump mcp-core floor to 1.18.0b14 for the key-rotation primitive
  ([`23d10f6`](https://github.com/n24q02m/mnemo-mcp/commit/23d10f622a66396d002d44667a1a85ad46c74a0b))


## v2.3.0-beta.16 (2026-06-19)

### Bug Fixes

- Make canary gate utf-8-safe (decode+encode) and Cloudflare-UA-aware
  ([`e14d20d`](https://github.com/n24q02m/mnemo-mcp/commit/e14d20d530ad42c033a54c493265939bb3b40816))

- Make canary gate utf-8-safe and Cloudflare-UA-aware
  ([`e14d20d`](https://github.com/n24q02m/mnemo-mcp/commit/e14d20d530ad42c033a54c493265939bb3b40816))

- Neutral default endpoint + env-first secrets in CF self-host scripts
  ([`82704c7`](https://github.com/n24q02m/mnemo-mcp/commit/82704c74d17fdbe4d7189195dfc6d60577f0e923))

- Use contextlib.suppress for stdout reconfigure (SIM105)
  ([`e14d20d`](https://github.com/n24q02m/mnemo-mcp/commit/e14d20d530ad42c033a54c493265939bb3b40816))

### Features

- Add CF protocol-test harness cf_full_flow.py
  ([`8c1fb61`](https://github.com/n24q02m/mnemo-mcp/commit/8c1fb61cac8929fae4151c49126ef2e31cd7bab1))

- DISABLE_LOCAL_EMBED / DISABLE_LOCAL_RERANK disable-local toggles
  ([#826](https://github.com/n24q02m/mnemo-mcp/pull/826),
  [`66d2203`](https://github.com/n24q02m/mnemo-mcp/commit/66d2203e2d35b7d7a9ee8ba8e3912b8a55582cc2))

- Enable username-stable-sub workspace bucket
  ([`813f0b1`](https://github.com/n24q02m/mnemo-mcp/commit/813f0b11419ebb2011063a053f7961c41ff9fcb4))


## v2.3.0-beta.15 (2026-06-18)

### Bug Fixes

- Add coverage for add_memory tool and entity history handler
  ([`5725904`](https://github.com/n24q02m/mnemo-mcp/commit/57259041db7775900b463cb39c1f3c0a66fd7fa1))

- Add coverage for FallbackChainReranker and rerank chain builder
  ([`ec0aea9`](https://github.com/n24q02m/mnemo-mcp/commit/ec0aea9b2fe7da909223fcb3e67a5333535c8a87))

- Add test coverage for credential_state set_current_sub/get_current_sub
  ([`c833145`](https://github.com/n24q02m/mnemo-mcp/commit/c833145e2f6f261358a47e40445579188ade1c25))

- Add tests for search_memory tool query/limit/rerank/graph-boost paths
  ([`7abca3f`](https://github.com/n24q02m/mnemo-mcp/commit/7abca3f07d16a6d4cb0dbee05cb74fe979a1bb74))

- Add unit tests for delete_memory tool in server.py
  ([`76ac51f`](https://github.com/n24q02m/mnemo-mcp/commit/76ac51f1a298f2d470f76e2384af60548e7fe538))

- Add unit tests for MemoryDB sync_state get/upsert helpers
  ([`8171b7f`](https://github.com/n24q02m/mnemo-mcp/commit/8171b7f3e2dde00eae62de2673348306bf92432b))

- Batch LWW apply_bundle upserts to remove per-row N+1 in delta sync
  ([`766c70f`](https://github.com/n24q02m/mnemo-mcp/commit/766c70f0c0e112df59c54384d8293cffea58de52))

- Bump mcp-core to 1.18.0b10
  ([`6689ee3`](https://github.com/n24q02m/mnemo-mcp/commit/6689ee3534422849d724f399a6b2d4f91fbbf3a7))

- Cover Qwen3EmbedBackend query/embed paths and cloud provider mapping in embedder tests
  ([`5fc5f31`](https://github.com/n24q02m/mnemo-mcp/commit/5fc5f3148a43fc32fe90be6ec84c6bec67ed32c2))

- Prefix unused account var to satisfy RUF059
  ([`75f8186`](https://github.com/n24q02m/mnemo-mcp/commit/75f8186feac7b7c4501baa85c97dd5e12ae40777))

- Refresh lockfile (renovate maintenance)
  ([`8096fd3`](https://github.com/n24q02m/mnemo-mcp/commit/8096fd32d3150f32b3db20ef29d8b7a3ed58496b))

- Standardize error-response hints under the 'suggestion' key
  ([`5a439b1`](https://github.com/n24q02m/mnemo-mcp/commit/5a439b1a8ce4a1f1549cf4cf4a54228c154a4efa))

- Update mcp-core pin-guard test to 1.18.0b10 floor
  ([`6689ee3`](https://github.com/n24q02m/mnemo-mcp/commit/6689ee3534422849d724f399a6b2d4f91fbbf3a7))

- Update non-major dependencies
  ([`fd51782`](https://github.com/n24q02m/mnemo-mcp/commit/fd51782dcce61df8d6a2854a59b0d813ca384a70))

### Features

- Add CF deploy script with post-deploy canary gate and auto-rollback
  ([`75f8186`](https://github.com/n24q02m/mnemo-mcp/commit/75f8186feac7b7c4501baa85c97dd5e12ae40777))


## v2.3.0-beta.14 (2026-06-17)

### Bug Fixes

- Chunk MemoryDBD1 bulk import under D1's 100-bound-parameter ceiling
  ([#817](https://github.com/n24q02m/mnemo-mcp/pull/817),
  [`e354a3b`](https://github.com/n24q02m/mnemo-mcp/commit/e354a3b7302fe46b72932c38419a75314a5e733b))


## v2.3.0-beta.13 (2026-06-17)

### Features

- Add JSONL import/export to MemoryDBD1 for CF memory migration
  ([#816](https://github.com/n24q02m/mnemo-mcp/pull/816),
  [`f5a309f`](https://github.com/n24q02m/mnemo-mcp/commit/f5a309ff2d7ff413690255d4fed7c402684eae5a))


## v2.3.0-beta.12 (2026-06-17)

### Bug Fixes

- Cover MemoryDBD1 search/stats/sync_state to restore 95% gate
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Exclude node_modules and venv from docker build context
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Report cf-d1 db_path in config status on Cloudflare
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

### Features

- Add CF full-flow self-test (OAuth + memory-survives-recreate + per-sub)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Add cloud-embed-forcing regression gate for Cloudflare
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Add Cloudflare Worker (per-user DO + KV/D1/Vectorize outbound)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Add Cloudflare-migration test harness (fakes, parity corpus, golden)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Add D1 schema (per-sub isolation, FTS5, graph, sync_state PK fix)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Add D1Connection shim (sqlite3-like surface over D1, per-sub)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Add MemoryDBD1 CRUD on D1 + Vectorize (per-sub scoped)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Add wrangler config + document Cloudflare serverless mode
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Bump mcp-core pin to 1.18.0b9 for CF storage backends
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Disable passport delta-sync on Cloudflare (D1 is durable store)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Encrypt OAuth tokens via PerPluginStore (KV-routable, per-sub)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Make knowledge-graph SQL per-sub aware via connection shim
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Migrate mnemo-mcp to Cloudflare (D1 + Vectorize + KV)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Per-sub embedding-identity guard on D1 store_meta
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Per-sub sync_state on D1 (fixes mem_002 PK collision)
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Pin D3 per-sub isolation schema contract test
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Rewrite hybrid search as D1-FTS + Vectorize + app-side RRF
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Route per-sub credentials through PerPluginStore cf-kv seam
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))

- Select MemoryDBD1 on Cloudflare via DOCS_DB_BACKEND
  ([#815](https://github.com/n24q02m/mnemo-mcp/pull/815),
  [`4f828ff`](https://github.com/n24q02m/mnemo-mcp/commit/4f828ff85e007a296aa5362f45c2c2f930319205))


## v2.3.0-beta.11 (2026-06-15)

### Bug Fixes

- Bump mcp-core to 1.18.0b5 for vertex_express support
  ([#812](https://github.com/n24q02m/mnemo-mcp/pull/812),
  [`fa3c157`](https://github.com/n24q02m/mnemo-mcp/commit/fa3c157040273b54972d2dc48228f86952be8ad6))

- Correct stale config.enc references to config.json in docstrings
  ([#812](https://github.com/n24q02m/mnemo-mcp/pull/812),
  [`fa3c157`](https://github.com/n24q02m/mnemo-mcp/commit/fa3c157040273b54972d2dc48228f86952be8ad6))


## v2.3.0-beta.10 (2026-06-15)

### Bug Fixes

- Clarify embedding-model switch requires reindex (B2 guard)
  ([#789](https://github.com/n24q02m/mnemo-mcp/pull/789),
  [`b3fd2c3`](https://github.com/n24q02m/mnemo-mcp/commit/b3fd2c3a411608cecaadfca3df3242741ec9d3be))

- Correct credential storage and relay setup docs to match runtime
  ([`48b186d`](https://github.com/n24q02m/mnemo-mcp/commit/48b186d633900534333eb3efbe9862efa2445910))

- Correct stale config.enc references to config.json in docstrings
  ([`f40fc4e`](https://github.com/n24q02m/mnemo-mcp/commit/f40fc4e901dc53fb26e6ccf6178168ab527e3410))

- Drop vestigial mcp-core checkout from CI
  ([`586c531`](https://github.com/n24q02m/mnemo-mcp/commit/586c5312cbc49f4da0c2e47c56d5f1a976b629bf))

- Remove literal v<auto> placeholder from stabilization note
  ([#775](https://github.com/n24q02m/mnemo-mcp/pull/775),
  [`a989724`](https://github.com/n24q02m/mnemo-mcp/commit/a989724df419f25ad2a1a2c75213e3d768452874))

- Type-safe entity ID accumulation in upsert_entities
  ([#788](https://github.com/n24q02m/mnemo-mcp/pull/788),
  [`c58e3c9`](https://github.com/n24q02m/mnemo-mcp/commit/c58e3c95c289581265a64357adf9f9eaa06b6f17))

- **deps**: Update dependency cryptography to v49
  ([#785](https://github.com/n24q02m/mnemo-mcp/pull/785),
  [`7d73369`](https://github.com/n24q02m/mnemo-mcp/commit/7d733694f25e96962b100fba4fd72f923910663a))

- **deps**: Update non-major dependencies to >=1.43.29
  ([#784](https://github.com/n24q02m/mnemo-mcp/pull/784),
  [`572e4a4`](https://github.com/n24q02m/mnemo-mcp/commit/572e4a4d836658db89a5352860a27d519e55c52d))

### Chores

- **deps**: Lock file maintenance ([#786](https://github.com/n24q02m/mnemo-mcp/pull/786),
  [`f0288d4`](https://github.com/n24q02m/mnemo-mcp/commit/f0288d411f822bfd6d47ca5be1e56ca75493614a))

- **deps**: Update python:3.13-slim-bookworm docker digest to 05b9539
  ([#783](https://github.com/n24q02m/mnemo-mcp/pull/783),
  [`fc19362`](https://github.com/n24q02m/mnemo-mcp/commit/fc19362d8c5eeaa294404027d5afd05151c71051))

### Features

- Add actionable suggestions to JSON error responses
  ([#787](https://github.com/n24q02m/mnemo-mcp/pull/787),
  [`9006a86`](https://github.com/n24q02m/mnemo-mcp/commit/9006a86ce6b3a40b70ce4b92f77e600a638caa7f))


## v2.3.0-beta.9 (2026-06-12)

### Bug Fixes

- Make BYO embedding registration tolerant of re-init
  ([#782](https://github.com/n24q02m/mnemo-mcp/pull/782),
  [`3caf44a`](https://github.com/n24q02m/mnemo-mcp/commit/3caf44a6f4a289ca1d6e99360df924d9284e586e))


## v2.3.0-beta.8 (2026-06-12)

### Bug Fixes

- Make BYO reranker registration tolerant of re-init
  ([#781](https://github.com/n24q02m/mnemo-mcp/pull/781),
  [`11daf28`](https://github.com/n24q02m/mnemo-mcp/commit/11daf2864cbab5609c50aa5c006dc5500c206a3a))


## v2.3.0-beta.7 (2026-06-12)

### Bug Fixes

- Sync README tagline to current capability description
  ([#778](https://github.com/n24q02m/mnemo-mcp/pull/778),
  [`ada65ad`](https://github.com/n24q02m/mnemo-mcp/commit/ada65adf5793f7735910d090c57cefa54060eb0c))

### Features

- Register a BYO local reranker via CustomRerankerSpec
  ([#780](https://github.com/n24q02m/mnemo-mcp/pull/780),
  [`010cbb6`](https://github.com/n24q02m/mnemo-mcp/commit/010cbb6388d323037c4818aa0d9a75375acf055f))

- Sync cross-promo section ([#779](https://github.com/n24q02m/mnemo-mcp/pull/779),
  [`3b55e43`](https://github.com/n24q02m/mnemo-mcp/commit/3b55e43adf8adf17c8ffa0cc635972622c8adb80))


## v2.3.0-beta.6 (2026-06-12)

### Features

- Guard vector store against embedding-model mismatch with opt-in reindex
  ([#777](https://github.com/n24q02m/mnemo-mcp/pull/777),
  [`b21301c`](https://github.com/n24q02m/mnemo-mcp/commit/b21301c8cc9db54441e7c3521089f7de9737fc5e))


## v2.3.0-beta.5 (2026-06-12)

### Bug Fixes

- Correct dedup threshold doc and add multi-user trust row
  ([#773](https://github.com/n24q02m/mnemo-mcp/pull/773),
  [`f9f6041`](https://github.com/n24q02m/mnemo-mcp/commit/f9f6041d1fba1275c91179a40b3a34421a560811))

- Remove orphaned Qodo pr-agent config ([#770](https://github.com/n24q02m/mnemo-mcp/pull/770),
  [`9758c86`](https://github.com/n24q02m/mnemo-mcp/commit/9758c86859a6608be83bb91c7706f8d2af41e8a6))

- Restore PSR changelog generation and backfill version history
  ([#772](https://github.com/n24q02m/mnemo-mcp/pull/772),
  [`7ede24d`](https://github.com/n24q02m/mnemo-mcp/commit/7ede24d785b628eb1b2610fe26856f3d8f268790))

### Features

- Allow overriding the local embed/rerank model via env
  ([#774](https://github.com/n24q02m/mnemo-mcp/pull/774),
  [`6a3442f`](https://github.com/n24q02m/mnemo-mcp/commit/6a3442f656ac41848dc3dd5e24764af859859b34))


## v2.3.0-beta.4 (2026-06-11)

### Bug Fixes

- Default local reranker to YesNo ONNX variant (~598MB vs ~12GB)
  ([#769](https://github.com/n24q02m/mnemo-mcp/pull/769),
  [`74a4b87`](https://github.com/n24q02m/mnemo-mcp/commit/74a4b873f787d705d2cfa971c57ca62db0268b16))

- **deps**: Update non-major dependencies ([#762](https://github.com/n24q02m/mnemo-mcp/pull/762),
  [`67191f0`](https://github.com/n24q02m/mnemo-mcp/commit/67191f06f7ecf0b0960a015c515d95f430402f43))

### Chores

- **deps**: Lock file maintenance ([#763](https://github.com/n24q02m/mnemo-mcp/pull/763),
  [`ebdbfb5`](https://github.com/n24q02m/mnemo-mcp/commit/ebdbfb586f5ac74aef0dcc3cbbc30a6a84e5db78))

### Performance Improvements

- **embedder**: Implement concurrent batching in CloudEmbeddingBackend
  ([#767](https://github.com/n24q02m/mnemo-mcp/pull/767),
  [`1632ae0`](https://github.com/n24q02m/mnemo-mcp/commit/1632ae045ca9304da67aec7f378ea41ad89eebc8))

### Refactoring

- **server**: Structure UX suggestions in error responses
  ([#764](https://github.com/n24q02m/mnemo-mcp/pull/764),
  [`74ad9f5`](https://github.com/n24q02m/mnemo-mcp/commit/74ad9f51a96b299666183f3701d8acfccc54672d))


## v2.3.0-beta.3 (2026-06-11)

### Bug Fixes

- Document per-task model chains (mnemo) ([#766](https://github.com/n24q02m/mnemo-mcp/pull/766),
  [`35fd79b`](https://github.com/n24q02m/mnemo-mcp/commit/35fd79b79da4335b6597283d95d2c690a0668e1c))

- Document per-task model chains + provider->key table (drop priority-router docs)
  ([#766](https://github.com/n24q02m/mnemo-mcp/pull/766),
  [`35fd79b`](https://github.com/n24q02m/mnemo-mcp/commit/35fd79b79da4335b6597283d95d2c690a0668e1c))

- Update mnemo config docstring to chain model (drop priority-router text)
  ([#766](https://github.com/n24q02m/mnemo-mcp/pull/766),
  [`35fd79b`](https://github.com/n24q02m/mnemo-mcp/commit/35fd79b79da4335b6597283d95d2c690a0668e1c))

### Features

- Drop config(action="models") catalog-listing tool action
  ([#768](https://github.com/n24q02m/mnemo-mcp/pull/768),
  [`fa739d8`](https://github.com/n24q02m/mnemo-mcp/commit/fa739d82150d61f1650e3ecce34b5f17ddc2b25c))


## v2.3.0-beta.2 (2026-06-11)

### Bug Fixes

- Gate default model chain by configured provider key (no-usable-key falls to local)
  ([#765](https://github.com/n24q02m/mnemo-mcp/pull/765),
  [`414bc84`](https://github.com/n24q02m/mnemo-mcp/commit/414bc846406b7e481a687023817581d320c2cbce))

- Keep Passport Sync capabilityInfo entry in mnemo relay schema
  ([#765](https://github.com/n24q02m/mnemo-mcp/pull/765),
  [`414bc84`](https://github.com/n24q02m/mnemo-mcp/commit/414bc846406b7e481a687023817581d320c2cbce))

### Features

- Mnemo per-task model chains, drop priority-router + singular/backend
  ([#765](https://github.com/n24q02m/mnemo-mcp/pull/765),
  [`414bc84`](https://github.com/n24q02m/mnemo-mcp/commit/414bc846406b7e481a687023817581d320c2cbce))

- Mnemo relay model-chain tasks + derived key fields
  ([#765](https://github.com/n24q02m/mnemo-mcp/pull/765),
  [`414bc84`](https://github.com/n24q02m/mnemo-mcp/commit/414bc846406b7e481a687023817581d320c2cbce))

- Model-chain selection (mnemo) — Phase 1 sample server
  ([#765](https://github.com/n24q02m/mnemo-mcp/pull/765),
  [`414bc84`](https://github.com/n24q02m/mnemo-mcp/commit/414bc846406b7e481a687023817581d320c2cbce))


## v2.3.0-beta.1 (2026-06-11)

### Bug Fixes

- ANTHROPIC LLM gate + =-form model normalisation in graph
  ([#761](https://github.com/n24q02m/mnemo-mcp/pull/761),
  [`2288bbb`](https://github.com/n24q02m/mnemo-mcp/commit/2288bbb73a101a8824b4fb36e00218c551ee6aab))

### Features

- Migrate LLM/embedding/rerank dispatch to mcp_core.llm litellm passthrough
  ([#761](https://github.com/n24q02m/mnemo-mcp/pull/761),
  [`2288bbb`](https://github.com/n24q02m/mnemo-mcp/commit/2288bbb73a101a8824b4fb36e00218c551ee6aab))

- Migrate LLM/embedding/rerank to litellm passthrough via mcp-core[llm]
  ([#761](https://github.com/n24q02m/mnemo-mcp/pull/761),
  [`2288bbb`](https://github.com/n24q02m/mnemo-mcp/commit/2288bbb73a101a8824b4fb36e00218c551ee6aab))

### Testing

- Patch mcp_core.llm instead of native SDKs for litellm passthrough
  ([#761](https://github.com/n24q02m/mnemo-mcp/pull/761),
  [`2288bbb`](https://github.com/n24q02m/mnemo-mcp/commit/2288bbb73a101a8824b4fb36e00218c551ee6aab))


## v2.2.2-beta.2 (2026-06-10)

### Bug Fixes

- Add input validation for recall_context and save_summary prompts
  ([#752](https://github.com/n24q02m/mnemo-mcp/pull/752),
  [`932e852`](https://github.com/n24q02m/mnemo-mcp/commit/932e8524e9b393c07b38c17bf82e8f6edee575f7))

- Remove unused pytest import in prompt validation test
  ([#752](https://github.com/n24q02m/mnemo-mcp/pull/752),
  [`932e852`](https://github.com/n24q02m/mnemo-mcp/commit/932e8524e9b393c07b38c17bf82e8f6edee575f7))

- Use OS-correct Path comparison in sub-token path test
  ([`3861c3e`](https://github.com/n24q02m/mnemo-mcp/commit/3861c3e8e670fd2f01d36659bf886842c934d173))

### Testing

- Add comprehensive tests for decode_bundle ([#756](https://github.com/n24q02m/mnemo-mcp/pull/756),
  [`25b9b5f`](https://github.com/n24q02m/mnemo-mcp/commit/25b9b5fa477f5740064e9be5a44d774a267cba1e))

- Add exhaustive edge-case tests for encode_bundle
  ([#759](https://github.com/n24q02m/mnemo-mcp/pull/759),
  [`92e58d5`](https://github.com/n24q02m/mnemo-mcp/commit/92e58d50835866e64fef5e0a621b29e8d552f8eb))

- Add validation for empty memory_id in link_memory_entities
  ([#754](https://github.com/n24q02m/mnemo-mcp/pull/754),
  [`c44d4be`](https://github.com/n24q02m/mnemo-mcp/commit/c44d4bee3da770bd25dea52ec542b42d3a24d216))


## v2.2.2-beta.1 (2026-06-10)

### Bug Fixes

- Correct stale documentation drift across docs
  ([#751](https://github.com/n24q02m/mnemo-mcp/pull/751),
  [`03558df`](https://github.com/n24q02m/mnemo-mcp/commit/03558df778a7430a45357d6dd53e49417db74a5b))


## v2.2.1 (2026-06-09)


## v2.2.1-beta.1 (2026-06-09)

### Bug Fixes

- Gitignore bot/merge junk artifacts (*.orig/*.rej/*.patch/*.diff/*.cover/*.bak)
  ([#728](https://github.com/n24q02m/mnemo-mcp/pull/728),
  [`9bb6068`](https://github.com/n24q02m/mnemo-mcp/commit/9bb60689a14ab3e717266951993ef5d21cd230e4))

- **deps**: Update non-major dependencies ([#730](https://github.com/n24q02m/mnemo-mcp/pull/730),
  [`060e641`](https://github.com/n24q02m/mnemo-mcp/commit/060e641d56beea504f2030cea1d6c83c0e574f8c))

### Chores

- **deps**: Update codecov/codecov-action action to v7
  ([#731](https://github.com/n24q02m/mnemo-mcp/pull/731),
  [`c1df57e`](https://github.com/n24q02m/mnemo-mcp/commit/c1df57e5dafb0998961a4ac5651faa8799fbe4ff))


## v2.2.0 (2026-06-07)

### Bug Fixes

- Report package version in serverInfo and align DB path env var
  ([#724](https://github.com/n24q02m/mnemo-mcp/pull/724),
  [`971e3e6`](https://github.com/n24q02m/mnemo-mcp/commit/971e3e6caf05fcf257d9a5cdab11808adf45d90e))


## v2.2.0-beta.1 (2026-06-07)

### Bug Fixes

- Avoid SQLite variable limit in tag filter using json_each
  ([`23dd65a`](https://github.com/n24q02m/mnemo-mcp/commit/23dd65a5ebdd2bffa6357fe15e70f96fb6b7316b))

- Escape single quotes in Google Drive query strings
  ([`f4f6407`](https://github.com/n24q02m/mnemo-mcp/commit/f4f6407a5543a9dc08870ba3c20c6bc68e80ef92))

- Update actions/checkout digest to df4cb1c
  ([`2f99f82`](https://github.com/n24q02m/mnemo-mcp/commit/2f99f8295743dc57241896b8a28016463c2b98bd))

- Update non-major dependencies
  ([`1464106`](https://github.com/n24q02m/mnemo-mcp/commit/1464106f6848bb433ace0a1ed5fb32d12346d0a6))

### Features

- Add bundle encode/decode truncation test coverage
  ([`f5b91c0`](https://github.com/n24q02m/mnemo-mcp/commit/f5b91c07b84a5d3760f2626c3803bf0f06800213))

- Add temporal resolve exception-handling test coverage
  ([`8db679a`](https://github.com/n24q02m/mnemo-mcp/commit/8db679a180da195621780a633f6f0052fbf55fa3))

- Add test coverage for sync/gdrive.py
  ([`eea68c2`](https://github.com/n24q02m/mnemo-mcp/commit/eea68c2993b43804a540840e81783900fb844956))

- Add token_store OSError fallback test coverage
  ([`5d61a06`](https://github.com/n24q02m/mnemo-mcp/commit/5d61a061ddce65eb65db5608f64aefb2bd62bb1d))


## v2.1.4 (2026-06-01)

### Bug Fixes

- Pin mcp-core 1.17.2 (stable)
  ([`0bc24b4`](https://github.com/n24q02m/mnemo-mcp/commit/0bc24b45e5af35152d654acb13f85b8bf4ccddb1))


## v2.1.4-beta.1 (2026-06-01)

### Bug Fixes

- Bump mcp-core to 1.17.2-beta.1 for beta testing
  ([`8e779b2`](https://github.com/n24q02m/mnemo-mcp/commit/8e779b242c0478c6e491755881a3425c15322b00))

- Count GOOGLE_DRIVE_CLIENT_ID in setup-status for accurate state
  ([#665](https://github.com/n24q02m/mnemo-mcp/pull/665),
  [`0ff9fde`](https://github.com/n24q02m/mnemo-mcp/commit/0ff9fdefebfcde3aad9aef07eb1845485341d22b))

- Count GOOGLE_DRIVE_CLIENT_ID in setup-status so reported state is accurate
  ([#685](https://github.com/n24q02m/mnemo-mcp/pull/685),
  [`4f16841`](https://github.com/n24q02m/mnemo-mcp/commit/4f168411bbae4f7a3ec7c80232e4ad095f824d6a))

- Harden list_memories SQL against bandit injection findings
  ([#683](https://github.com/n24q02m/mnemo-mcp/pull/683),
  [`db8fad7`](https://github.com/n24q02m/mnemo-mcp/commit/db8fad7320f929b0a73c5d0795867937a0059a0a))

- Mirror CLAUDE.md doc fixes into AGENTS.md ([#685](https://github.com/n24q02m/mnemo-mcp/pull/685),
  [`4f16841`](https://github.com/n24q02m/mnemo-mcp/commit/4f168411bbae4f7a3ec7c80232e4ad095f824d6a))

- Sync mnemo-mcp docs with current code ([#685](https://github.com/n24q02m/mnemo-mcp/pull/685),
  [`4f16841`](https://github.com/n24q02m/mnemo-mcp/commit/4f168411bbae4f7a3ec7c80232e4ad095f824d6a))


## v2.1.3 (2026-05-29)

### Bug Fixes

- Pin mcp-core 1.17.1 (BearerMCPApp resource_metadata #260)
  ([`c986479`](https://github.com/n24q02m/mnemo-mcp/commit/c986479fb72618cdcb974dc825669d5c608ed66b))


## v2.1.2 (2026-05-29)

### Bug Fixes

- Pin mcp-core 1.17.0 (stable OAuth refresh_token)
  ([`7dac822`](https://github.com/n24q02m/mnemo-mcp/commit/7dac822198dfa0210e448790c858d955ed7e6d01))

- Redact sensitive material from Google Drive error logs
  ([#675](https://github.com/n24q02m/mnemo-mcp/pull/675),
  [`737765f`](https://github.com/n24q02m/mnemo-mcp/commit/737765f54e71369d44c286bd6bea7e1617b011ca))


## v2.1.2-beta.1 (2026-05-29)

### Bug Fixes

- Add coverage tests for _serialize_f32 ([#650](https://github.com/n24q02m/mnemo-mcp/pull/650),
  [`01ca439`](https://github.com/n24q02m/mnemo-mcp/commit/01ca439ca87bbd737f3f87ff2808186d9e7b453c))

- Add edge-case tests for find_similar_entity
  ([#653](https://github.com/n24q02m/mnemo-mcp/pull/653),
  [`c812315`](https://github.com/n24q02m/mnemo-mcp/commit/c8123150f482dde5ca3b982ef2385caff89c6b23))

- Add error-path tests for _validate_cloud_models
  ([#655](https://github.com/n24q02m/mnemo-mcp/pull/655),
  [`7d1d066`](https://github.com/n24q02m/mnemo-mcp/commit/7d1d0665eb50150d24c61264b53b57b0f6e936a7))

- Add test for _json formatting helper ([#652](https://github.com/n24q02m/mnemo-mcp/pull/652),
  [`08ba464`](https://github.com/n24q02m/mnemo-mcp/commit/08ba46486898dbc0fb07e12ecb4e787f5d233094))

- Add tests for _env_compression_enabled ([#658](https://github.com/n24q02m/mnemo-mcp/pull/658),
  [`0caca74`](https://github.com/n24q02m/mnemo-mcp/commit/0caca744057c874707a8cd843a32c319b59f9fd5))

- Bump mcp-core to 1.17.0-beta.1 for OAuth refresh_token
  ([`e9cb25a`](https://github.com/n24q02m/mnemo-mcp/commit/e9cb25a72e829d7bc00f18ab0c53a692b1818be0))

- Escape LIKE wildcards in temporal entity substring fallback to prevent LIKE injection
  ([#664](https://github.com/n24q02m/mnemo-mcp/pull/664),
  [`117a6ba`](https://github.com/n24q02m/mnemo-mcp/commit/117a6ba27d529eee7e894957b58b342205df98a0))

### Testing

- Add edge case tests for find_similar_entity
  ([#653](https://github.com/n24q02m/mnemo-mcp/pull/653),
  [`c812315`](https://github.com/n24q02m/mnemo-mcp/commit/c8123150f482dde5ca3b982ef2385caff89c6b23))

- Add edge case tests for find_similar_entity with macOS fix
  ([#653](https://github.com/n24q02m/mnemo-mcp/pull/653),
  [`c812315`](https://github.com/n24q02m/mnemo-mcp/commit/c8123150f482dde5ca3b982ef2385caff89c6b23))


## v2.1.1 (2026-05-28)

### Bug Fixes

- Drop local path source for mcp-core to align with PyPI-only pattern
  ([`0ae4d58`](https://github.com/n24q02m/mnemo-mcp/commit/0ae4d58716611c35f7968873c81f8ec0dc2a2532))


## v2.1.1-beta.1 (2026-05-28)

### Bug Fixes

- **deps**: Pin pydantic to <2.13 to match mcp-core 1.15.0 transitive cap
  ([`3ee31c9`](https://github.com/n24q02m/mnemo-mcp/commit/3ee31c99d15fbe6cdb4abd13802b74d6bd50f55b))

- **deps**: Update non-major dependencies ([#644](https://github.com/n24q02m/mnemo-mcp/pull/644),
  [`f3c7d2c`](https://github.com/n24q02m/mnemo-mcp/commit/f3c7d2c3be7b48e6a77e9b3573ad1acaf791c948))


## v2.1.0 (2026-05-26)


## v2.1.0-beta.2 (2026-05-26)

### Features

- Wire MCP_AUTH_DISABLE env to run_http_server(auth_disabled=)
  ([`9d72798`](https://github.com/n24q02m/mnemo-mcp/commit/9d72798383e411ff28985e0349bd8282fc7bcb67))


## v2.1.0-beta.1 (2026-05-26)

### Bug Fixes

- **sync**: Resolve unsupported class base diagnostic from ty for _SyncModuleProxy
  ([#639](https://github.com/n24q02m/mnemo-mcp/pull/639),
  [`1f813b2`](https://github.com/n24q02m/mnemo-mcp/commit/1f813b277eae95c59a5a70bbd4d086fd8994b562))

- **test**: Update relay schema tests for new LLM providers
  ([#638](https://github.com/n24q02m/mnemo-mcp/pull/638),
  [`3b6d62b`](https://github.com/n24q02m/mnemo-mcp/commit/3b6d62b50b016deae44e9d2dfecfa4b8070e64f1))

### Features

- Add MCP_AUTH_DISABLE env flag for external auth boundary
  ([`8b4a341`](https://github.com/n24q02m/mnemo-mcp/commit/8b4a341baba441f80ea5ce976bbf85a013052643))

- **mcp**: Add ACTION GUIDEs to tool descriptions
  ([#640](https://github.com/n24q02m/mnemo-mcp/pull/640),
  [`a329aac`](https://github.com/n24q02m/mnemo-mcp/commit/a329aac8ec07673adad2f035c644672fe4194e3d))

- **relay**: Add Anthropic and xAI to relay schema
  ([#638](https://github.com/n24q02m/mnemo-mcp/pull/638),
  [`3b6d62b`](https://github.com/n24q02m/mnemo-mcp/commit/3b6d62b50b016deae44e9d2dfecfa4b8070e64f1))

### Performance Improvements

- **db**: Optimize sqlite json tags filtering
  ([#639](https://github.com/n24q02m/mnemo-mcp/pull/639),
  [`1f813b2`](https://github.com/n24q02m/mnemo-mcp/commit/1f813b277eae95c59a5a70bbd4d086fd8994b562))


## v2.0.1-beta.1 (2026-05-24)

### Bug Fixes

- Add supply-chain security tests for pinned CVE patches
  ([#630](https://github.com/n24q02m/mnemo-mcp/pull/630),
  [`c3afdd7`](https://github.com/n24q02m/mnemo-mcp/commit/c3afdd78d8d6c55da66b75acef293f1e7a979a3a))

- **deps**: Update dependency cohere to v7 ([#636](https://github.com/n24q02m/mnemo-mcp/pull/636),
  [`4bd58dd`](https://github.com/n24q02m/mnemo-mcp/commit/4bd58dd3a235c35886dd803f863dcb93dc76dd81))

- **deps**: Update non-major dependencies ([#635](https://github.com/n24q02m/mnemo-mcp/pull/635),
  [`7ed58b4`](https://github.com/n24q02m/mnemo-mcp/commit/7ed58b47e5f7884b08020272f64daf52086b6277))

- **deps**: Update non-major dependencies ([#624](https://github.com/n24q02m/mnemo-mcp/pull/624),
  [`c5f0556`](https://github.com/n24q02m/mnemo-mcp/commit/c5f0556e8f1681021a97c1a95d143b71d4ead39d))

### Chores

- **deps**: Update codecov/codecov-action digest to e79a696
  ([#625](https://github.com/n24q02m/mnemo-mcp/pull/625),
  [`d69201e`](https://github.com/n24q02m/mnemo-mcp/commit/d69201ea43751dc84f86e34b530bf1b8ac646338))

- **deps**: Update docker/build-push-action digest to f9f3042
  ([#629](https://github.com/n24q02m/mnemo-mcp/pull/629),
  [`56ebea0`](https://github.com/n24q02m/mnemo-mcp/commit/56ebea0b9659bb3d1c9a22bf5b03dc2d2f1c094e))

- **deps**: Update docker/login-action digest to 650006c
  ([#633](https://github.com/n24q02m/mnemo-mcp/pull/633),
  [`3ca20b1`](https://github.com/n24q02m/mnemo-mcp/commit/3ca20b1b8904c32e4785a9b368ef0a1e647d65b7))

- **deps**: Update docker/setup-buildx-action digest to d7f5e7f
  ([#634](https://github.com/n24q02m/mnemo-mcp/pull/634),
  [`8cb5b91`](https://github.com/n24q02m/mnemo-mcp/commit/8cb5b91fc157bdd300acac759ded5d5185a38009))

- **deps**: Update python:3.13-slim-bookworm docker digest to e4fa1f9
  ([#627](https://github.com/n24q02m/mnemo-mcp/pull/627),
  [`31c3e7d`](https://github.com/n24q02m/mnemo-mcp/commit/31c3e7d3822d9745146da6215cafe02ec706052e))

### Performance Improvements

- Prevent expensive json.dumps calls for empty lists
  ([#637](https://github.com/n24q02m/mnemo-mcp/pull/637),
  [`470c3b5`](https://github.com/n24q02m/mnemo-mcp/commit/470c3b5e9307e66b0d508f972d8cdf7768a23f29))


## v2.0.0 (2026-05-19)


## v2.0.0-beta.7 (2026-05-16)

### Bug Fixes

- Add pre-commit hook canonicalizing uv.lock without local path sources
  ([`98c33f0`](https://github.com/n24q02m/mnemo-mcp/commit/98c33f010ad04e5a05ae52d8ebeb4e3f58a736d6))

- Pin urllib3 floor to patch 2 high CVEs (header forwarding + decompression bomb)
  ([`556b8f8`](https://github.com/n24q02m/mnemo-mcp/commit/556b8f8b6df4d30c5036a9aea93d0eab34d1f66a))

- Scrub internal dev-process terminology from user-facing surfaces
  ([`53ed36a`](https://github.com/n24q02m/mnemo-mcp/commit/53ed36a9d64d5b4f5d76b98cf629ab847b8dcb8d))

- Store per-sub config.json with 0600 permissions (CodeQL #12)
  ([`d2e6280`](https://github.com/n24q02m/mnemo-mcp/commit/d2e628059c03c849369e8329f6501bb5cac696c8))

- **deps**: Update actions/create-github-app-token digest to bcd2ba4
  ([`425c104`](https://github.com/n24q02m/mnemo-mcp/commit/425c104794c47ed40b17eec3affe22a95b27dfd0))

- **deps**: Update non-major dependencies (google-genai, openai, tiktoken, boto3, moto)
  ([`915fe3b`](https://github.com/n24q02m/mnemo-mcp/commit/915fe3b83761aaa50e27c47b7803eac82f3bfd09))

- **deps**: Update python:3.13-slim-bookworm docker digest to 386df64
  ([`96ffe9d`](https://github.com/n24q02m/mnemo-mcp/commit/96ffe9da33f5a84c0e48570c2f8a99d1e86cd6c5))


## v2.0.0-beta.6 (2026-05-14)

### Bug Fixes

- Rebuild uv.lock without sources for Docker CD (recurrence #4)
  ([`487c76f`](https://github.com/n24q02m/mnemo-mcp/commit/487c76f34ce5054a68e38b74c7f0976921c50937))


## v2.0.0-beta.5 (2026-05-14)

### Bug Fixes

- Relay form scope back to API keys only - S3/passphrase = operator env
  ([`c5a7f07`](https://github.com/n24q02m/mnemo-mcp/commit/c5a7f07faf1106fc5fed3b466bf61cb46071c969))

### Features

- Document XOR backend semantics + per-mode runbook in passport docs
  ([`f88b127`](https://github.com/n24q02m/mnemo-mcp/commit/f88b1272c0c1f77d0d6e9e3d5e523969b04fe625))

- Wire XOR sync mode into lifespan + credential save path
  ([`5491ea7`](https://github.com/n24q02m/mnemo-mcp/commit/5491ea748815a949f8c60b8cc5f7816e60ed08e3))

- XOR sync backend resolver for Method 1 vs Method 2/3 deployments
  ([`46f9a46`](https://github.com/n24q02m/mnemo-mcp/commit/46f9a4611a065b43ef6cf0f5793266699d2dbb52))


## v2.0.0-beta.4 (2026-05-14)

### Bug Fixes

- Rebuild uv.lock without local path sources for Docker CD (third recurrence)
  ([`78bc995`](https://github.com/n24q02m/mnemo-mcp/commit/78bc99569f17b1285b26957be350bbd57c3e0284))


## v2.0.0-beta.3 (2026-05-14)

### Bug Fixes

- Package alembic config + scripts in wheel so migrations run on uvx install
  ([`2020a66`](https://github.com/n24q02m/mnemo-mcp/commit/2020a66bb33ac0401bdaab64c1edbc72ea1540c9))


## v2.0.0-beta.2 (2026-05-10)

### Bug Fixes

- Rebuild uv.lock without local path sources for Docker CD (recurrence)
  ([`c8c10b6`](https://github.com/n24q02m/mnemo-mcp/commit/c8c10b68e453cfcb6c9836d64150d6062263e909))


## v2.0.0-beta.1 (2026-05-10)

### Bug Fixes

- Skip vec KNN coverage tests on macOS — sqlite3 lacks load_extension
  ([`5ab76ef`](https://github.com/n24q02m/mnemo-mcp/commit/5ab76effa617dbc09e38ac9e57420fc3c731fd73))

### Features

- Alembic mem_002_compression migration with sync_state table
  ([`56e2511`](https://github.com/n24q02m/mnemo-mcp/commit/56e2511e6153f4462c8d33ae2a75a3f3513826ff))

- Alembic mem_003_temporal — bitemporal columns + entity rename + audit + vec
  ([`e24b86a`](https://github.com/n24q02m/mnemo-mcp/commit/e24b86a9363c31044e20e6d17ba5fecd6313fe22))

- Bundle codec — populate memory_entities + memory_edges + links sections
  ([`aaeeed7`](https://github.com/n24q02m/mnemo-mcp/commit/aaeeed7467705efc60c9527c2a5fcd22220ad215))

- Delta-sync orchestrator with last-write-wins conflict resolution
  ([`ae0238c`](https://github.com/n24q02m/mnemo-mcp/commit/ae0238cc37f91257e68edf07c508a9cb4ffa8f12))

- Docs — Phase 3 ARCHITECTURE / BENCHMARKS / README refresh
  ([`0580992`](https://github.com/n24q02m/mnemo-mcp/commit/058099214abeb95a1faf0b6fc564ea25bd819fe8))

- KG_AUTO_ENABLED auto-extract on capture via temporal pipeline
  ([`ba23223`](https://github.com/n24q02m/mnemo-mcp/commit/ba23223c7c80c4a2c4f52b73056914edaca99b7b))

- Knowledge-audit skill — Phase 3 temporal KG audit dimensions
  ([`e02b8e7`](https://github.com/n24q02m/mnemo-mcp/commit/e02b8e7a49a61cb6e0fdaef1e69d4ff1ba9612d7))

- LLM-driven compression pipeline with tiktoken graceful skip
  ([`8252865`](https://github.com/n24q02m/mnemo-mcp/commit/8252865d32fec019b69f52bce4c760861ab6e75a))

- Passport bundle codec - AES-256-GCM payload + Argon2id KDF
  ([`6280056`](https://github.com/n24q02m/mnemo-mcp/commit/62800569ae23805be19edcac01badb84f1cef8b8))

- Passport sync MCP actions sync_now / export / import + memory compress
  ([`830153b`](https://github.com/n24q02m/mnemo-mcp/commit/830153b09075c5959a28b43c6ff28cef137e3b69))

- Passport sync scheduler with lock + passport-bootstrap skill
  ([`7b42ce2`](https://github.com/n24q02m/mnemo-mcp/commit/7b42ce2db611c62d28e83debd7baa4e954ef0efa))

- Phase 2 coverage gate - tests for GDriveBackend / S3 errors / bundle edges
  ([`c9f2814`](https://github.com/n24q02m/mnemo-mcp/commit/c9f2814a4a72b947a28b9f79d57b8fad8072171f))

- Phase 2 docs - ARCHITECTURE / passport / compression / BENCHMARKS
  ([`6d23ff5`](https://github.com/n24q02m/mnemo-mcp/commit/6d23ff566a09594c807dd9f3cb17c0fde5ff2b17))

- Phase 3 coverage tests — KG handlers + bundle KG + resolve vec KNN
  ([`67ad902`](https://github.com/n24q02m/mnemo-mcp/commit/67ad902d924bca5b5cca18abe39fee1077e4c0c8))

- Refactor sync.py into backend-pluggable sync/ package
  ([`b831fc3`](https://github.com/n24q02m/mnemo-mcp/commit/b831fc39efcda1f797e9c6d1f206f365ef63c777))

- Relay form S3 + passphrase fields with Argon2id hash storage
  ([`26dd253`](https://github.com/n24q02m/mnemo-mcp/commit/26dd25354f756deec4984321c7a6d1bd7f9ac4ec))

- S3 sync backend with boto3 + custom endpoint for R2/B2/MinIO
  ([`fade034`](https://github.com/n24q02m/mnemo-mcp/commit/fade03475b9907723fa28985c3e1ee1755474124))

- Surface COMPRESSION_ENABLED/PROVIDER/MODEL as Pydantic settings
  ([`1ae5bd7`](https://github.com/n24q02m/mnemo-mcp/commit/1ae5bd7b5f4cc24054b8a3f0186814afcb1374e2))

- Temporal/extract.py — entity extraction via llm.call_llm dispatch
  ([`f8d1196`](https://github.com/n24q02m/mnemo-mcp/commit/f8d11961fd6198163271e265ed4f7e91008c280c))

- Temporal/queries.py + entity_search + entity_graph + history actions
  ([`43affe3`](https://github.com/n24q02m/mnemo-mcp/commit/43affe3f9d90d85a13e346d9179d192bfb1f23aa))

- Temporal/resolve.py — entity resolution via name + embedding KNN
  ([`b0579ac`](https://github.com/n24q02m/mnemo-mcp/commit/b0579ac07dc50bac820a0761be20fe180e5ae66d))

- Temporal/store.py — KG persistence with memory_id + bitemporal columns
  ([`33d6b68`](https://github.com/n24q02m/mnemo-mcp/commit/33d6b68879f17020b743b835f13832ab273d2bf8))


## v1.27.0-beta.2 (2026-05-09)

### Bug Fixes

- Rebuild uv.lock without local path sources for Docker CD
  ([`87ed4a6`](https://github.com/n24q02m/mnemo-mcp/commit/87ed4a6243ca8f4d45ad37e1abb71cfb4f22f5cd))


## v1.27.0-beta.1 (2026-05-09)

### Bug Fixes

- Fix silent save_token failures by improving observability
  ([#604](https://github.com/n24q02m/mnemo-mcp/pull/604),
  [`09c3304`](https://github.com/n24q02m/mnemo-mcp/commit/09c3304df873a5046971e9c2fd776792397561f4))

- Refactor complex memory tool and resolve CI failures
  ([#601](https://github.com/n24q02m/mnemo-mcp/pull/601),
  [`fd6e3ee`](https://github.com/n24q02m/mnemo-mcp/commit/fd6e3ee419c7bc59f9c00486dd63824c9ac136ff))

- Refactor overly complex memory tool and update tests
  ([#601](https://github.com/n24q02m/mnemo-mcp/pull/601),
  [`fd6e3ee`](https://github.com/n24q02m/mnemo-mcp/commit/fd6e3ee419c7bc59f9c00486dd63824c9ac136ff))

- Refactor overly complex memory tool into specialized tools
  ([#601](https://github.com/n24q02m/mnemo-mcp/pull/601),
  [`fd6e3ee`](https://github.com/n24q02m/mnemo-mcp/commit/fd6e3ee419c7bc59f9c00486dd63824c9ac136ff))

- Remove setup.md + refresh memory and config help
  ([`43d28c1`](https://github.com/n24q02m/mnemo-mcp/commit/43d28c12b2d9e4840d5467d1f31077a691a85a43))

- Remove unused 'mcp' import in __init__.py ([#587](https://github.com/n24q02m/mnemo-mcp/pull/587),
  [`cb546ec`](https://github.com/n24q02m/mnemo-mcp/commit/cb546ecf351ce33a4aec05ad8524272ffaf6300f))

- Revert setup docs duplicates per Spec F single source of truth
  ([`4f50017`](https://github.com/n24q02m/mnemo-mcp/commit/4f50017f683d9261117b3eafb8a7965f85c95230))

- Sync CLAUDE.md and AGENTS.md + add diff guard hook
  ([`7c0d636`](https://github.com/n24q02m/mnemo-mcp/commit/7c0d636c044b5aaca85ce53be149153facfdecfa))

- **config**: Replace unused import with find_spec for GGUF support
  ([#581](https://github.com/n24q02m/mnemo-mcp/pull/581),
  [`41cf206`](https://github.com/n24q02m/mnemo-mcp/commit/41cf206a8ca6c12f23ee68fa41c7b609d64406d8))

- **deps**: Bump google-genai to v2.0.1 + mcp-core floor to v1.14.0
  ([`1c0fa49`](https://github.com/n24q02m/mnemo-mcp/commit/1c0fa4995db4cb456f45ae57758395e061dc5770))

- **deps**: Update non-major dependencies ([#607](https://github.com/n24q02m/mnemo-mcp/pull/607),
  [`3ca3fe5`](https://github.com/n24q02m/mnemo-mcp/commit/3ca3fe56fbefa4412d0f816c51e4bac6df6c9a51))

- **server**: Stats_resource pass single ctx arg to _handle_stats
  ([`ec02587`](https://github.com/n24q02m/mnemo-mcp/commit/ec02587785f489a8d40e4763c617026c54204acb))

### Chores

- Remove unused async_delete_token function and its test
  ([#584](https://github.com/n24q02m/mnemo-mcp/pull/584),
  [`9626f81`](https://github.com/n24q02m/mnemo-mcp/commit/9626f815471d8fdd5d725ed0a5decc79306405f0))

- **deps**: Update actions/dependency-review-action action to v5
  ([#610](https://github.com/n24q02m/mnemo-mcp/pull/610),
  [`68998ba`](https://github.com/n24q02m/mnemo-mcp/commit/68998ba7cf793f3af9dcb0b3bdc8f1d9e575d28a))

### Features

- Add Table of contents heading + auto-generated link list (Spec E Wave 2)
  ([`fedb166`](https://github.com/n24q02m/mnemo-mcp/commit/fedb16630f27e463d98d3700c8e3cc602df5e395))

- Alembic baseline + mem_001_context_types migration with backup-before-migrate
  ([`35b5845`](https://github.com/n24q02m/mnemo-mcp/commit/35b5845d0a9993c81d955227931961d233a59b73))

- Archive policy importance times recency with restore action
  ([`2dd6a77`](https://github.com/n24q02m/mnemo-mcp/commit/2dd6a7775560dbdd8cf1cedc3e5e97083a038311))

- Link to mcp.n24q02m.com unified docs site (Spec F Phase 4)
  ([`68238db`](https://github.com/n24q02m/mnemo-mcp/commit/68238db08fae80ebe82519ccc73ea1071f06fc61))

- Memory capture action with context typing and dedup
  ([`370528c`](https://github.com/n24q02m/mnemo-mcp/commit/370528c6910150d029fe20b334f2d8846eb4f23a))

- Multi-provider LLM auto-detect dispatch layer with graceful skip
  ([`f391b85`](https://github.com/n24q02m/mnemo-mcp/commit/f391b85cc96b58aa9a2764c3aa6df2ad8aae9f38))

- Plugin trinity recall-context memory-commit skills + SessionStart hook
  ([`b221367`](https://github.com/n24q02m/mnemo-mcp/commit/b22136762e5be327303b87d647d573b5a85c0db2))

- Refresh README + setup docs + ARCHITECTURE for Phase 1
  ([`2726e71`](https://github.com/n24q02m/mnemo-mcp/commit/2726e71904521e03761347c3337d4be20ad0a922))

- Retrieval RRF fusion + cross-encoder rerank + temporal decay + filters
  ([`6822bca`](https://github.com/n24q02m/mnemo-mcp/commit/6822bca8383b62e15cf21aea9c005fd0e43d670a))

- Sync cross-promo section ([#605](https://github.com/n24q02m/mnemo-mcp/pull/605),
  [`abf2af1`](https://github.com/n24q02m/mnemo-mcp/commit/abf2af1417941e42eeaf381331c331141ca642f8))

- **prompts**: Add ACTION GUIDEs to prompt docstrings
  ([#611](https://github.com/n24q02m/mnemo-mcp/pull/611),
  [`0b7a655`](https://github.com/n24q02m/mnemo-mcp/commit/0b7a65532c2c356e4ce9d827a646564ce9808865))

### Refactoring

- **credential_state**: Split long save_credentials method
  ([#598](https://github.com/n24q02m/mnemo-mcp/pull/598),
  [`c92062f`](https://github.com/n24q02m/mnemo-mcp/commit/c92062fbe52a2117d413f9af648c39b11a56d27c))

### Testing

- Add coverage for CloudReranker API error fallback
  ([#578](https://github.com/n24q02m/mnemo-mcp/pull/578),
  [`269a03c`](https://github.com/n24q02m/mnemo-mcp/commit/269a03ce0193136578b4431c3a917cae3a574428))

- Add coverage for SQLite column migration failure
  ([#588](https://github.com/n24q02m/mnemo-mcp/pull/588),
  [`647290c`](https://github.com/n24q02m/mnemo-mcp/commit/647290c06e788210d2e81834874bcccb9092d68b))

- Add coverage for SQLite column migration failure and fix type hint warning
  ([#588](https://github.com/n24q02m/mnemo-mcp/pull/588),
  [`647290c`](https://github.com/n24q02m/mnemo-mcp/commit/647290c06e788210d2e81834874bcccb9092d68b))

- Add coverage for vector search error handling
  ([#593](https://github.com/n24q02m/mnemo-mcp/pull/593),
  [`dde45e9`](https://github.com/n24q02m/mnemo-mcp/commit/dde45e92f393b35fcc281457a0c15c0a698bd2e8))

- Add TypeError coverage for bad dates in _calc_recency
  ([#580](https://github.com/n24q02m/mnemo-mcp/pull/580),
  [`ef61e6a`](https://github.com/n24q02m/mnemo-mcp/commit/ef61e6ac55e3254608b28d7c1f3f4ffed854bc5c))

- Consolidate and implement __main__.py tests
  ([#592](https://github.com/n24q02m/mnemo-mcp/pull/592),
  [`a649627`](https://github.com/n24q02m/mnemo-mcp/commit/a649627d4a7bf571ad562779e064dd39b6dbe468))

- Fix ty check error in _calc_recency coverage test
  ([#580](https://github.com/n24q02m/mnemo-mcp/pull/580),
  [`ef61e6a`](https://github.com/n24q02m/mnemo-mcp/commit/ef61e6ac55e3254608b28d7c1f3f4ffed854bc5c))

- **db**: Add missing error path test for invalid JSON in bulk import
  ([#603](https://github.com/n24q02m/mnemo-mcp/pull/603),
  [`6d731d1`](https://github.com/n24q02m/mnemo-mcp/commit/6d731d16a828c030c9df2662a4c7ae4159241e1d))

- **embedder**: Add fallback test for local check_available
  ([#591](https://github.com/n24q02m/mnemo-mcp/pull/591),
  [`d88af6a`](https://github.com/n24q02m/mnemo-mcp/commit/d88af6a90229d61cf08d6a8c7b8afcfb11e31b3c))

- **embedder**: Add tests for cloud embedding dimension recovery
  ([#582](https://github.com/n24q02m/mnemo-mcp/pull/582),
  [`5cb06f3`](https://github.com/n24q02m/mnemo-mcp/commit/5cb06f38fd9f9020b980bc5a9e346fe1a46182be))


## v1.26.0 (2026-05-06)


## v1.26.0-beta.1 (2026-05-06)

### Bug Fixes

- Consolidate setup docs body to 3 methods (drop legacy Method 4/5)
  ([#564](https://github.com/n24q02m/mnemo-mcp/pull/564),
  [`8d0c7af`](https://github.com/n24q02m/mnemo-mcp/commit/8d0c7af7a768652c5b118e06ce2394e0b4a9c03d))

- Path traversal vulnerability in multi-user remote mode
  ([#571](https://github.com/n24q02m/mnemo-mcp/pull/571),
  [`b050446`](https://github.com/n24q02m/mnemo-mcp/commit/b0504463fa128aa56a2c58ceed425330b6a83e72))

- Stop deleting credential_state from sys.modules in migration tests
  ([`b174237`](https://github.com/n24q02m/mnemo-mcp/commit/b1742375982cd93245661e6fc233a2bf3d040cb9))

- **deps**: Update non-major dependencies ([#572](https://github.com/n24q02m/mnemo-mcp/pull/572),
  [`b763529`](https://github.com/n24q02m/mnemo-mcp/commit/b763529f6a7a4b3dbdaaf73a5427aceaf9f1ddb5))

### Features

- Add explicit Method overview section to setup docs
  ([#563](https://github.com/n24q02m/mnemo-mcp/pull/563),
  [`29783e4`](https://github.com/n24q02m/mnemo-mcp/commit/29783e49b18443f84da349ee9de7af192e2e112f))

- Align userConfig with relay_schema fields ([#567](https://github.com/n24q02m/mnemo-mcp/pull/567),
  [`807336f`](https://github.com/n24q02m/mnemo-mcp/commit/807336f0aa19334f001d5bb89cae292acfe29a0f))

- Clarify Method 1/2/3 mutually exclusive (CC scope-by-endpoint)
  ([#569](https://github.com/n24q02m/mnemo-mcp/pull/569),
  [`5ece2c2`](https://github.com/n24q02m/mnemo-mcp/commit/5ece2c2e93474e48e19c8e8ea802bec35fe4d9d7))

- Declare userConfig schema and document install prompt
  ([#565](https://github.com/n24q02m/mnemo-mcp/pull/565),
  [`86ef846`](https://github.com/n24q02m/mnemo-mcp/commit/86ef84693f091e0406305d6866fff93598027ba3))

- Document userConfig credential prompts per plugin
  ([#568](https://github.com/n24q02m/mnemo-mcp/pull/568),
  [`5c0256a`](https://github.com/n24q02m/mnemo-mcp/commit/5c0256a53d548dfa2084bdc85cb2433c3e04b363))


## v1.25.0 (2026-05-04)

### Bug Fixes

- Bump mcp-core to 1.13.0 (STABLE) ([#562](https://github.com/n24q02m/mnemo-mcp/pull/562),
  [`9af5dbf`](https://github.com/n24q02m/mnemo-mcp/commit/9af5dbfb7465af5ddea10975dbdbbd33c0375986))


## v1.25.0-beta.9 (2026-05-03)

### Bug Fixes

- Bump mcp-core to 1.13.0-beta.9 for /login form shell refactor
  ([#558](https://github.com/n24q02m/mnemo-mcp/pull/558),
  [`2452d6a`](https://github.com/n24q02m/mnemo-mcp/commit/2452d6a683ac11b2a1519c1024bddce2678168cf))


## v1.25.0-beta.8 (2026-05-03)

### Features

- Bump mcp-core to 1.13.0-beta.7 ([#556](https://github.com/n24q02m/mnemo-mcp/pull/556),
  [`413c863`](https://github.com/n24q02m/mnemo-mcp/commit/413c863c0d83ff2b11f3a3b5a9f8ee03c4232295))

- Document MCP_RELAY_PASSWORD edge auth gate ([#557](https://github.com/n24q02m/mnemo-mcp/pull/557),
  [`6a1303d`](https://github.com/n24q02m/mnemo-mcp/commit/6a1303d53f8f2310493acb8d1b6cccda54950dde))

- Pass MCP_RELAY_PASSWORD env to HTTP container
  ([#555](https://github.com/n24q02m/mnemo-mcp/pull/555),
  [`41c33f2`](https://github.com/n24q02m/mnemo-mcp/commit/41c33f2b7d1f3c2758e6ef735d6753c3b306687a))


## v1.25.0-beta.7 (2026-05-03)

### Bug Fixes

- HTTP multi-user credential wiring (per-sub contextvar)
  ([#552](https://github.com/n24q02m/mnemo-mcp/pull/552),
  [`c0ee624`](https://github.com/n24q02m/mnemo-mcp/commit/c0ee624ca07734fda98ff81fe5929b35ba926ffb))

- Regenerate uv.lock for new mcp-core beta (Docker trap)
  ([#552](https://github.com/n24q02m/mnemo-mcp/pull/552),
  [`c0ee624`](https://github.com/n24q02m/mnemo-mcp/commit/c0ee624ca07734fda98ff81fe5929b35ba926ffb))


## v1.25.0-beta.6 (2026-05-02)

### Bug Fixes

- Regenerate uv.lock for new mcp-core beta (Docker trap)
  ([#550](https://github.com/n24q02m/mnemo-mcp/pull/550),
  [`f03616c`](https://github.com/n24q02m/mnemo-mcp/commit/f03616cae3acf10bae638e59fea2e478682811b2))


## v1.25.0-beta.5 (2026-05-02)

### Bug Fixes

- Stdio mode skips PerPluginStore fallback (spec §4.1)
  ([#549](https://github.com/n24q02m/mnemo-mcp/pull/549),
  [`6e5f317`](https://github.com/n24q02m/mnemo-mcp/commit/6e5f317b76707e9e35863b7f0e473c3401602c45))


## v1.25.0-beta.4 (2026-05-02)

### Bug Fixes

- Setup docs + README reflect stdio-pure architecture
  ([#547](https://github.com/n24q02m/mnemo-mcp/pull/547),
  [`1c83ed8`](https://github.com/n24q02m/mnemo-mcp/commit/1c83ed80df418dba67f1d1d312e996587868fae6))

- Update register_open_relay_tool call to new HTTP-only signature
  ([#546](https://github.com/n24q02m/mnemo-mcp/pull/546),
  [`8c23280`](https://github.com/n24q02m/mnemo-mcp/commit/8c23280aa14ea1162bc72c8140b3adafe46e9be6))

- **deps**: Update non-major dependencies ([#535](https://github.com/n24q02m/mnemo-mcp/pull/535),
  [`f9616dd`](https://github.com/n24q02m/mnemo-mcp/commit/f9616dd1acbc35ce52d692fea48098d5ce299250))

### Chores

- **deps**: Update dawidd6/action-send-mail action to v17
  ([#536](https://github.com/n24q02m/mnemo-mcp/pull/536),
  [`6457643`](https://github.com/n24q02m/mnemo-mcp/commit/6457643ba45b1bbd9a7b96c427a19885d7ee44fa))

### Features

- Stdio-pure + http-multi-user (drop daemon-bridge)
  ([#546](https://github.com/n24q02m/mnemo-mcp/pull/546),
  [`8c23280`](https://github.com/n24q02m/mnemo-mcp/commit/8c23280aa14ea1162bc72c8140b3adafe46e9be6))


## v1.25.0-beta.3 (2026-04-30)

### Bug Fixes

- Regenerate uv.lock UV_NO_SOURCES=1 (Docker trap)
  ([`892c6f7`](https://github.com/n24q02m/mnemo-mcp/commit/892c6f764ff22f77df9c5e577ab220b4aca98146))


## v1.25.0-beta.2 (2026-04-30)

### Bug Fixes

- G6 UX status accuracy — derive state from live PerPluginStore
  ([#542](https://github.com/n24q02m/mnemo-mcp/pull/542),
  [`4ab744b`](https://github.com/n24q02m/mnemo-mcp/commit/4ab744bd026071dd754c261e8c2b9fc49821625d))

- Re-trigger CI after mcp-core lint+format fix
  ([#541](https://github.com/n24q02m/mnemo-mcp/pull/541),
  [`2a91ca5`](https://github.com/n24q02m/mnemo-mcp/commit/2a91ca5099842cb951dc2040e6cded4b5cd66292))

- **tests**: Isolate ~/.mnemo-mcp via HOME/USERPROFILE monkeypatch
  ([#541](https://github.com/n24q02m/mnemo-mcp/pull/541),
  [`2a91ca5`](https://github.com/n24q02m/mnemo-mcp/commit/2a91ca5099842cb951dc2040e6cded4b5cd66292))

### Features

- **docs**: Add trust model section to README
  ([#540](https://github.com/n24q02m/mnemo-mcp/pull/540),
  [`57d9a8f`](https://github.com/n24q02m/mnemo-mcp/commit/57d9a8f659aec12816f9a6375082a0f6f3780834))

- **storage**: Migrate to PerPluginStore from mcp-core 1.13.0b1+
  ([#541](https://github.com/n24q02m/mnemo-mcp/pull/541),
  [`2a91ca5`](https://github.com/n24q02m/mnemo-mcp/commit/2a91ca5099842cb951dc2040e6cded4b5cd66292))


## v1.25.0-beta.1 (2026-04-30)

### Features

- Route stdio mode to FastMCP direct + multi-target Dockerfile
  ([#538](https://github.com/n24q02m/mnemo-mcp/pull/538),
  [`7ce1d48`](https://github.com/n24q02m/mnemo-mcp/commit/7ce1d4836e7d5d3f8ddd1ed40dc164ad3a56e936))


## v1.24.4 (2026-04-29)

### Bug Fixes

- Bump n24q02m-mcp-core to 1.11.3 for D17 tools cache refresh
  ([#532](https://github.com/n24q02m/mnemo-mcp/pull/532),
  [`f729b7e`](https://github.com/n24q02m/mnemo-mcp/commit/f729b7e50f8f2155c8c55b8f1c57b9bc2feeabea))


## v1.24.3 (2026-04-29)

### Bug Fixes

- Rebuild uv.lock without local path source ([#529](https://github.com/n24q02m/mnemo-mcp/pull/529),
  [`4d3b340`](https://github.com/n24q02m/mnemo-mcp/commit/4d3b34047d081cc9eac1072ba5a7746c701b9c66))


## v1.24.2 (2026-04-29)

### Bug Fixes

- Register config__open_relay tool (Transparent Bridge Wave 3)
  ([#527](https://github.com/n24q02m/mnemo-mcp/pull/527),
  [`3342205`](https://github.com/n24q02m/mnemo-mcp/commit/3342205e05c8e36fb2401d829afcf2098edaf463))


## v1.24.1 (2026-04-28)

### Bug Fixes

- Clarify default-local relay URL in setup docs (no n24q02m subdomain)
  ([#521](https://github.com/n24q02m/mnemo-mcp/pull/521),
  [`c8dc075`](https://github.com/n24q02m/mnemo-mcp/commit/c8dc07555a44af9a2ccbfdfbc88f4aa5f41c1e85))

- Pass MCP_TRANSPORT=stdio in plugin.json + uv run --no-sync hooks
  ([#523](https://github.com/n24q02m/mnemo-mcp/pull/523),
  [`a247bfc`](https://github.com/n24q02m/mnemo-mcp/commit/a247bfc45ba1ca1505280f854a960e249bcbc659))

- Pass MCP_TRANSPORT=stdio in plugin.json + uv run --no-sync hooks
  ([#522](https://github.com/n24q02m/mnemo-mcp/pull/522),
  [`c1e02a1`](https://github.com/n24q02m/mnemo-mcp/commit/c1e02a13ac719aeae3efd8b6106d80787cb1a0d5))

- **credentials**: Rip _share_cloud_keys_to_peers — per-server isolation
  ([#523](https://github.com/n24q02m/mnemo-mcp/pull/523),
  [`a247bfc`](https://github.com/n24q02m/mnemo-mcp/commit/a247bfc45ba1ca1505280f854a960e249bcbc659))

- **deps**: Bump n24q02m-mcp-core to 1.10.0 — Transparent Bridge waves 1-3
  ([#525](https://github.com/n24q02m/mnemo-mcp/pull/525),
  [`2fdce51`](https://github.com/n24q02m/mnemo-mcp/commit/2fdce51ae02b8c09c4cc9661da9745c794d3ebed))

- **lint**: Ruff format pass ([#523](https://github.com/n24q02m/mnemo-mcp/pull/523),
  [`a247bfc`](https://github.com/n24q02m/mnemo-mcp/commit/a247bfc45ba1ca1505280f854a960e249bcbc659))


## v1.24.0 (2026-04-28)

### Bug Fixes

- Bump n24q02m-mcp-core to 1.9.0 ([#520](https://github.com/n24q02m/mnemo-mcp/pull/520),
  [`a38d999`](https://github.com/n24q02m/mnemo-mcp/commit/a38d999caed42f45ff9fd402c3a65d448d0fc21f))

- Refresh uv.lock for mcp-core 1.8.2 + pydantic 2.12.x cohere compat
  ([#515](https://github.com/n24q02m/mnemo-mcp/pull/515),
  [`d1022ff`](https://github.com/n24q02m/mnemo-mcp/commit/d1022ff70f41ae388f606a4f040906b112339650))

- Restore CI coverage gate to >=95% ([#516](https://github.com/n24q02m/mnemo-mcp/pull/516),
  [`5a4272a`](https://github.com/n24q02m/mnemo-mcp/commit/5a4272a4f432a2bbf6db7bb85615fbb7e2fd1f4f))

### Features

- **ux**: Add actionable suggestions to missing argument errors
  ([#515](https://github.com/n24q02m/mnemo-mcp/pull/515),
  [`d1022ff`](https://github.com/n24q02m/mnemo-mcp/commit/d1022ff70f41ae388f606a4f040906b112339650))

### Testing

- Fix incorrect assertion for suggestions in test_server_lifespan
  ([#515](https://github.com/n24q02m/mnemo-mcp/pull/515),
  [`d1022ff`](https://github.com/n24q02m/mnemo-mcp/commit/d1022ff70f41ae388f606a4f040906b112339650))

- Update server tests for suggestion fields ([#515](https://github.com/n24q02m/mnemo-mcp/pull/515),
  [`d1022ff`](https://github.com/n24q02m/mnemo-mcp/commit/d1022ff70f41ae388f606a4f040906b112339650))

- Update test assertions for unknown actions ([#515](https://github.com/n24q02m/mnemo-mcp/pull/515),
  [`d1022ff`](https://github.com/n24q02m/mnemo-mcp/commit/d1022ff70f41ae388f606a4f040906b112339650))


## v1.23.0 (2026-04-27)

### Bug Fixes

- Bump n24q02m-mcp-core to 1.8.1 ([#510](https://github.com/n24q02m/mnemo-mcp/pull/510),
  [`dd465b7`](https://github.com/n24q02m/mnemo-mcp/commit/dd465b7c8a9669c34be25d550428abb41198f685))

### Features

- Add ## E2E section to CLAUDE.md per Task 21 docs rollout
  ([#507](https://github.com/n24q02m/mnemo-mcp/pull/507),
  [`c18ea67`](https://github.com/n24q02m/mnemo-mcp/commit/c18ea6750e6489e9e7c0a36e432c59fbaaab6b68))

- **mcp**: Add actionable suggestions to empty states and errors
  ([#505](https://github.com/n24q02m/mnemo-mcp/pull/505),
  [`fc10c55`](https://github.com/n24q02m/mnemo-mcp/commit/fc10c55d0e81fd44a71862c853cb66a0e8103e03))


## v1.23.0-beta.2 (2026-04-27)

### Bug Fixes

- Trigger per-sub GDrive device-code in multi-user remote mode
  ([`b0b66e4`](https://github.com/n24q02m/mnemo-mcp/commit/b0b66e47634467a2e0428f22b5f3f711b18c7903))


## v1.23.0-beta.1 (2026-04-27)

### Bug Fixes

- Regenerate uv.lock with UV_NO_SOURCES=1 for Docker build compat
  ([`53a5ecd`](https://github.com/n24q02m/mnemo-mcp/commit/53a5ecddb8257a0b08e7395c47ae345704663b54))

- Sweep doppler/infisical refs to skret SSM
  ([`a36fc18`](https://github.com/n24q02m/mnemo-mcp/commit/a36fc18c1d47dfac08e047a597a4cb0e8264afa6))

- Unit tests for multi-user credential helpers (cover macos coverage gap)
  ([#506](https://github.com/n24q02m/mnemo-mcp/pull/506),
  [`386018e`](https://github.com/n24q02m/mnemo-mcp/commit/386018e2c7e76635b9fd01dda3645cb698d33d72))

### Features

- Mnemo-mcp multi-user remote mode via PUBLIC_URL + per-sub credential storage
  ([#506](https://github.com/n24q02m/mnemo-mcp/pull/506),
  [`386018e`](https://github.com/n24q02m/mnemo-mcp/commit/386018e2c7e76635b9fd01dda3645cb698d33d72))

- Multi-user remote mode (PUBLIC_URL + per-JWT-sub)
  ([#506](https://github.com/n24q02m/mnemo-mcp/pull/506),
  [`386018e`](https://github.com/n24q02m/mnemo-mcp/commit/386018e2c7e76635b9fd01dda3645cb698d33d72))


## v1.22.3 (2026-04-24)

### Bug Fixes

- Add --frozen to Dockerfile uv sync (not --no-sources)
  ([#504](https://github.com/n24q02m/mnemo-mcp/pull/504),
  [`25db07d`](https://github.com/n24q02m/mnemo-mcp/commit/25db07d8e14b45d560f63bddd0caa71832b77700))


## v1.22.2 (2026-04-24)

### Bug Fixes

- Add --frozen --no-sources to Dockerfile uv sync
  ([#503](https://github.com/n24q02m/mnemo-mcp/pull/503),
  [`28417a7`](https://github.com/n24q02m/mnemo-mcp/commit/28417a79f872161004c0bcb250c86d1f1d6ddf50))


## v1.22.1 (2026-04-24)

### Bug Fixes

- Regenerate uv.lock without [tool.uv.sources] for Docker build
  ([#502](https://github.com/n24q02m/mnemo-mcp/pull/502),
  [`2f6ef9c`](https://github.com/n24q02m/mnemo-mcp/commit/2f6ef9c8e2bd60770fdcfd36077a451cb9d1b914))


## v1.22.0 (2026-04-24)

### Bug Fixes

- Bump mcp-core pin to 1.7.5 for ty strict narrowing
  ([#495](https://github.com/n24q02m/mnemo-mcp/pull/495),
  [`75481c6`](https://github.com/n24q02m/mnemo-mcp/commit/75481c63630815b403f5180d380777c5522bbb65))

- Bump mcp-core to 1.7.1 ([#495](https://github.com/n24q02m/mnemo-mcp/pull/495),
  [`75481c6`](https://github.com/n24q02m/mnemo-mcp/commit/75481c63630815b403f5180d380777c5522bbb65))

- Bump n24q02m-mcp-core to 1.7.6 ([#501](https://github.com/n24q02m/mnemo-mcp/pull/501),
  [`c2f693b`](https://github.com/n24q02m/mnemo-mcp/commit/c2f693b44935cd0faa3f79cd8d330bbafe5be052))

- Bump n24q02m-mcp-core to >=1.7.1 ([#495](https://github.com/n24q02m/mnemo-mcp/pull/495),
  [`75481c6`](https://github.com/n24q02m/mnemo-mcp/commit/75481c63630815b403f5180d380777c5522bbb65))

- **ci**: Add checkout step for mcp-core dependency
  ([#492](https://github.com/n24q02m/mnemo-mcp/pull/492),
  [`71cb4f5`](https://github.com/n24q02m/mnemo-mcp/commit/71cb4f5e8849573294db1bc06200504946b84ceb))

- **ci**: Fix checkout path for mcp-core dependency
  ([#492](https://github.com/n24q02m/mnemo-mcp/pull/492),
  [`71cb4f5`](https://github.com/n24q02m/mnemo-mcp/commit/71cb4f5e8849573294db1bc06200504946b84ceb))

- **ci**: Fix python script quotation and mcp-core checkout path
  ([#492](https://github.com/n24q02m/mnemo-mcp/pull/492),
  [`71cb4f5`](https://github.com/n24q02m/mnemo-mcp/commit/71cb4f5e8849573294db1bc06200504946b84ceb))

- **tests**: Correct mock in test_main_invalid_log_level
  ([`463dc06`](https://github.com/n24q02m/mnemo-mcp/commit/463dc06bad9626463f0bfa1a89b07fb2b44fe7aa))

- **tests**: Restore test_main_invalid_log_level mock for 1-Daemon arch
  ([`bb873ad`](https://github.com/n24q02m/mnemo-mcp/commit/bb873ad1237c1f176312f9244697e0e51b8f2995))

### Chores

- **deps**: Update python:3.13-slim-bookworm docker digest to bb73517
  ([#491](https://github.com/n24q02m/mnemo-mcp/pull/491),
  [`51f0b84`](https://github.com/n24q02m/mnemo-mcp/commit/51f0b844cfcb0cd9ac602a9019ff26c4922048e1))

### Features

- Enforce Smart Daemon Manager (1-Daemon) for stdio transport
  ([`fab6668`](https://github.com/n24q02m/mnemo-mcp/commit/fab66688952814c5a2afd43e17568d7dc9923d70))

- Migrate stdio transport to 1-Daemon architecture (run_smart_stdio_proxy)
  ([`05d144a`](https://github.com/n24q02m/mnemo-mcp/commit/05d144a7945c91580a7d8ece9d75a58f31387b7d))

- **ux**: Add suggestion fields for not-found errors in memory actions
  ([#492](https://github.com/n24q02m/mnemo-mcp/pull/492),
  [`71cb4f5`](https://github.com/n24q02m/mnemo-mcp/commit/71cb4f5e8849573294db1bc06200504946b84ceb))


## v1.21.3 (2026-04-22)

### Bug Fixes

- Bump mcp-core to 1.6.2 ([#490](https://github.com/n24q02m/mnemo-mcp/pull/490),
  [`30fd32c`](https://github.com/n24q02m/mnemo-mcp/commit/30fd32ce1f6683842a2104407ab32aec0658ad84))

- Bump mcp-core to 1.6.3 ([#490](https://github.com/n24q02m/mnemo-mcp/pull/490),
  [`30fd32c`](https://github.com/n24q02m/mnemo-mcp/commit/30fd32ce1f6683842a2104407ab32aec0658ad84))

- Bump n24q02m-mcp-core to 1.6.3 (relay form follow redirect_url)
  ([#490](https://github.com/n24q02m/mnemo-mcp/pull/490),
  [`30fd32c`](https://github.com/n24q02m/mnemo-mcp/commit/30fd32ce1f6683842a2104407ab32aec0658ad84))


## v1.21.2 (2026-04-22)

### Bug Fixes

- Bump mcp-core to 1.6.2 ([#488](https://github.com/n24q02m/mnemo-mcp/pull/488),
  [`0387816`](https://github.com/n24q02m/mnemo-mcp/commit/03878164c4c3413cf281a97a1c05ec8537e17989))


## v1.21.1 (2026-04-22)

### Bug Fixes

- Bump n24q02m-mcp-core to 1.5.1
  ([`8effc6e`](https://github.com/n24q02m/mnemo-mcp/commit/8effc6ea875f5f51db5346a1e7ea640badcba8fb))

- Bump n24q02m-mcp-core to 1.6.1 ([#484](https://github.com/n24q02m/mnemo-mcp/pull/484),
  [`23f9be6`](https://github.com/n24q02m/mnemo-mcp/commit/23f9be6e3a3567877881f5215d0c169b04f0688b))

- Require explicit MCP_RELAY_URL for remote-relay mode
  ([#484](https://github.com/n24q02m/mnemo-mcp/pull/484),
  [`23f9be6`](https://github.com/n24q02m/mnemo-mcp/commit/23f9be6e3a3567877881f5215d0c169b04f0688b))

- Require explicit MCP_RELAY_URL for remote-relay mode per matrix 2.5
  ([#484](https://github.com/n24q02m/mnemo-mcp/pull/484),
  [`23f9be6`](https://github.com/n24q02m/mnemo-mcp/commit/23f9be6e3a3567877881f5215d0c169b04f0688b))

- **deps**: Update dependency qwen3-embed to >=1.9.0
  ([#481](https://github.com/n24q02m/mnemo-mcp/pull/481),
  [`c073a62`](https://github.com/n24q02m/mnemo-mcp/commit/c073a62d0e77c61e050e49a77a1ecfd5d636532d))

### Chores

- **deps**: Lock file maintenance ([#483](https://github.com/n24q02m/mnemo-mcp/pull/483),
  [`935b70b`](https://github.com/n24q02m/mnemo-mcp/commit/935b70b3cbb2a4ada6939347811cf2ec8e208d60))

- **deps**: Update astral-sh/setup-uv action to v8
  ([#482](https://github.com/n24q02m/mnemo-mcp/pull/482),
  [`3b25bd6`](https://github.com/n24q02m/mnemo-mcp/commit/3b25bd637964f9c8f04e253c905a0c5a7e6cef73))


## v1.21.0 (2026-04-21)

### Bug Fixes

- Bump n24q02m-mcp-core to 1.5.0 in uv.lock
  ([`27ced98`](https://github.com/n24q02m/mnemo-mcp/commit/27ced98ff926d770ccd78477a52e83659d3432b8))

- Lock file maintenance patch bumps
  ([`88c02bd`](https://github.com/n24q02m/mnemo-mcp/commit/88c02bddc0ce9a2f6b6f06a4a094c067c81d77bc))

### Features

- Add empty-state suggestion field to list actions
  ([`11cde8f`](https://github.com/n24q02m/mnemo-mcp/commit/11cde8f28f5f22fe860c87e6231e8468a86507fc))


## v1.20.4 (2026-04-21)

### Bug Fixes

- Accept SubjectContext arg on save_credentials
  ([`45b9095`](https://github.com/n24q02m/mnemo-mcp/commit/45b9095c63db3ec53386b10021673a3872209074))

- Cache environment checks with functools.lru_cache to eliminate repetitive import overhead
  ([`d188282`](https://github.com/n24q02m/mnemo-mcp/commit/d18828280b74072c3a957fbc2aa3e594b85e8990))

- Stdio fallback spawns local credential form, not remote relay
  ([`7dd1d59`](https://github.com/n24q02m/mnemo-mcp/commit/7dd1d595f1aea1a3f7dde7e802d8da37160bfdc9))

- **deps**: Bump mcp-core to 1.4.3
  ([`43799d8`](https://github.com/n24q02m/mnemo-mcp/commit/43799d88eee0cd7fad60b8d205c059691f9a57ef))

- **deps**: Lock file maintenance (authlib 1.6.11->1.7.0 security align)
  ([`f14ee2e`](https://github.com/n24q02m/mnemo-mcp/commit/f14ee2ee2a5667a1043f193c0e8382b33ba5baa9))

### Performance Improvements

- **config**: Cache environment checks for significant speedup
  ([`d188282`](https://github.com/n24q02m/mnemo-mcp/commit/d18828280b74072c3a957fbc2aa3e594b85e8990))


## v1.20.3 (2026-04-19)

### Bug Fixes

- Add tests for GDrive OAuth failure callback + token save error paths
  ([#466](https://github.com/n24q02m/mnemo-mcp/pull/466),
  [`b49e217`](https://github.com/n24q02m/mnemo-mcp/commit/b49e2176407a5f3bbce4f4dc053044c9de68890c))

- Bump mcp-core to 1.3.0 ([#462](https://github.com/n24q02m/mnemo-mcp/pull/462),
  [`088a730`](https://github.com/n24q02m/mnemo-mcp/commit/088a73002f23a9cf8fa3d6ac55a074c8fe999a06))

- Bump n24q02m-mcp-core to 1.4.0 ([#468](https://github.com/n24q02m/mnemo-mcp/pull/468),
  [`be37093`](https://github.com/n24q02m/mnemo-mcp/commit/be3709317456be92794342cb0650e86d3425240e))

- Silence ty invalid-assignment on _ConnProxy test wrapper
  ([#463](https://github.com/n24q02m/mnemo-mcp/pull/463),
  [`33b967d`](https://github.com/n24q02m/mnemo-mcp/commit/33b967de5cef9f264fc9b0abf1a62a694c07ec6f))

- Surface OAuth token save failures in GDrive device code poll
  ([#466](https://github.com/n24q02m/mnemo-mcp/pull/466),
  [`b49e217`](https://github.com/n24q02m/mnemo-mcp/commit/b49e2176407a5f3bbce4f4dc053044c9de68890c))

- Sync mnemo GDrive OAuth defaults to match wet-mcp parity
  ([`d172f92`](https://github.com/n24q02m/mnemo-mcp/commit/d172f92a76ef71266cfc4d27448add3699b513cf))

- Untrack .jules AI traces + add .Jules/.superpower to gitignore
  ([`858682e`](https://github.com/n24q02m/mnemo-mcp/commit/858682e54cda2947793aa3fbc803d416af21abe7))

- **config**: Remove hardcoded oauth credentials
  ([#434](https://github.com/n24q02m/mnemo-mcp/pull/434),
  [`edfc2a1`](https://github.com/n24q02m/mnemo-mcp/commit/edfc2a1abc154ed04ba126802a4775eabbb50f4b))

- **db**: Use 'k = ?' constraint for vector search compatibility
  ([#453](https://github.com/n24q02m/mnemo-mcp/pull/453),
  [`29c1a22`](https://github.com/n24q02m/mnemo-mcp/commit/29c1a227e6ec3d07efaa58c94f65313c21e81d0d))

- **db**: Use static parameterized query for all fields in update method
  ([#455](https://github.com/n24q02m/mnemo-mcp/pull/455),
  [`6e50ee1`](https://github.com/n24q02m/mnemo-mcp/commit/6e50ee110067f3ff6e08416fd2bc1932874d9b66))

- **relay**: Modularize ensure_config long method
  ([#442](https://github.com/n24q02m/mnemo-mcp/pull/442),
  [`3f6c38f`](https://github.com/n24q02m/mnemo-mcp/commit/3f6c38f73bd1d9945ac5243cb9ede8dd0e226d01))

- **security**: Resolve SQL injection in update method and fix CI type errors
  ([#455](https://github.com/n24q02m/mnemo-mcp/pull/455),
  [`6e50ee1`](https://github.com/n24q02m/mnemo-mcp/commit/6e50ee110067f3ff6e08416fd2bc1932874d9b66))

- **server**: Refactor config tool to reduce complexity
  ([#452](https://github.com/n24q02m/mnemo-mcp/pull/452),
  [`b4cfe8b`](https://github.com/n24q02m/mnemo-mcp/commit/b4cfe8ba1dbe0265bfc2b88afbcaa9a654c92846))

- **sync**: Refactor setup_google_auth into smaller helper methods
  ([#450](https://github.com/n24q02m/mnemo-mcp/pull/450),
  [`6a32f11`](https://github.com/n24q02m/mnemo-mcp/commit/6a32f11d4ce951791391a3734373712b16688597))

### Chores

- **deps**: Lock file maintenance ([#438](https://github.com/n24q02m/mnemo-mcp/pull/438),
  [`ac272d9`](https://github.com/n24q02m/mnemo-mcp/commit/ac272d99f9dd5a1da34524b58a481c630b48e92f))

### Performance Improvements

- **sync**: Refactor folder ID caching to use asynchronous I/O
  ([#443](https://github.com/n24q02m/mnemo-mcp/pull/443),
  [`6704aac`](https://github.com/n24q02m/mnemo-mcp/commit/6704aacebe1951c01dfa780fb9eef6a5c41db681))

- **token-store**: Make token storage operations asynchronous
  ([#449](https://github.com/n24q02m/mnemo-mcp/pull/449),
  [`5d23f9f`](https://github.com/n24q02m/mnemo-mcp/commit/5d23f9fb0dfc2f37185e1e9c20dccaed2cc5c209))

### Testing

- **config**: Achieve 100% coverage for GPU and reranker detection
  ([#445](https://github.com/n24q02m/mnemo-mcp/pull/445),
  [`777fb97`](https://github.com/n24q02m/mnemo-mcp/commit/777fb97c80b481bde877efe0584e8801c88e675f))

- **relay**: Add apply_config tests and consolidate module tests
  ([#444](https://github.com/n24q02m/mnemo-mcp/pull/444),
  [`daf6d6e`](https://github.com/n24q02m/mnemo-mcp/commit/daf6d6e57346aa9357d41b56420b6cff080acbdf))


## v1.20.2 (2026-04-17)

### Bug Fixes

- Bump n24q02m-mcp-core to 1.2.0 (authlib CVE patch)
  ([`a8195e8`](https://github.com/n24q02m/mnemo-mcp/commit/a8195e8a67a735b27827a6ab887616049c7cd5ec))


## v1.20.1 (2026-04-17)

### Bug Fixes

- Bump n24q02m-mcp-core to 1.1.1 for OAuth issuer fix
  ([`092df1b`](https://github.com/n24q02m/mnemo-mcp/commit/092df1b0a66baa0bcaf6da43256f62aee6b34531))


## v1.20.0 (2026-04-17)

### Bug Fixes

- Add diacritic preservation pre-commit hook ([#458](https://github.com/n24q02m/mnemo-mcp/pull/458),
  [`a613a75`](https://github.com/n24q02m/mnemo-mcp/commit/a613a7532a2f251f0a4e6de7dfbf0ad9c2c39656))

- Add tests for GPU detection error path ([#426](https://github.com/n24q02m/mnemo-mcp/pull/426),
  [`e4cc498`](https://github.com/n24q02m/mnemo-mcp/commit/e4cc4980b40b73fd493c2276fd0edcbec4c45c58))

- Add tests for link_memory_entities error path
  ([#417](https://github.com/n24q02m/mnemo-mcp/pull/417),
  [`359485c`](https://github.com/n24q02m/mnemo-mcp/commit/359485cf8a362e0a6bb74d3e0ace47f098506bb4))

- Auto-open default browser at Google device-code URL
  ([`b754afe`](https://github.com/n24q02m/mnemo-mcp/commit/b754afeb983d7e4d97cfc22c16835c8a1541bcbb))

- Bump authlib to 1.6.11 for CSRF cache bypass (GHSA-jj8c-mmj3-mmgv)
  ([`15ce143`](https://github.com/n24q02m/mnemo-mcp/commit/15ce1437fa69bb3e8216c0d232a25f7f668ccd26))

- Bump n24q02m-mcp-core to >=1.0.0 stable
  ([`a563432`](https://github.com/n24q02m/mnemo-mcp/commit/a563432d1c9da82286aafd87c483fc1fcbad97d5))

- Correct README config tool actions list
  ([`e8f1d75`](https://github.com/n24q02m/mnemo-mcp/commit/e8f1d7586ea58edb6ea385ac1356ab103ab9d8c4))

- Cover _init_schema vec0 branch without requiring sqlite-vec
  ([`dc9a5e3`](https://github.com/n24q02m/mnemo-mcp/commit/dc9a5e31ac9f2422b997c606824e54e13aa8b5a0))

- Cover vec-enabled db branches on runners lacking sqlite-vec
  ([`4154e8c`](https://github.com/n24q02m/mnemo-mcp/commit/4154e8c804388af01e59ad4f8593d975709a3d4c))

- Cover vec-enabled search branch with connection proxy
  ([`cd5361e`](https://github.com/n24q02m/mnemo-mcp/commit/cd5361e69e46e265470a1522aed6393ff784eae8))

- Do not auto-open browser from background sync loop
  ([`711e3c4`](https://github.com/n24q02m/mnemo-mcp/commit/711e3c4cb741edc02b50428271317a68d4d329a0))

- Drop local uv.sources override for n24q02m-mcp-core
  ([`b5dfc70`](https://github.com/n24q02m/mnemo-mcp/commit/b5dfc70e5f3109cdcaf3407f283bc510f89c4a08))

- Lock file maintenance
  ([`da6e544`](https://github.com/n24q02m/mnemo-mcp/commit/da6e544a39d0828cd89c8de8e6b465942ceb969f))

- Log non-blocking exceptions in server search/add handlers
  ([`3731e96`](https://github.com/n24q02m/mnemo-mcp/commit/3731e9672bac421ed9fe485f37573f8d69f7d273))

- Make sqlite-vec tests robust to runners lacking enable_load_extension
  ([`5e360d0`](https://github.com/n24q02m/mnemo-mcp/commit/5e360d00fa0a21a1503844be326563a8e4d1dbcf))

- Optimize graph traversal via semi-join
  ([`fc313d9`](https://github.com/n24q02m/mnemo-mcp/commit/fc313d9aa52cdc304b468895c192edfc7e9176cd))

- Precompute archive cutoff date and gitignore coverage artifacts
  ([#457](https://github.com/n24q02m/mnemo-mcp/pull/457),
  [`541d12b`](https://github.com/n24q02m/mnemo-mcp/commit/541d12be5fb8179d0aa9c6dab585c46e7167b42f))

- Prevent SQL injection in MemoryDB.update method
  ([`703455a`](https://github.com/n24q02m/mnemo-mcp/commit/703455a8b529bf2d80a0818f9bb6a7a46b5d97ad))

- Remove hardcoded Google Drive OAuth credentials
  ([`0363f5e`](https://github.com/n24q02m/mnemo-mcp/commit/0363f5e3021810cef00b1c49bc3a67a9cfa3f5fd))

- Retry GDrive folder search before creating to prevent duplicates
  ([`e3e24f8`](https://github.com/n24q02m/mnemo-mcp/commit/e3e24f88d2dba8b0325e1f6fe157a42ace2c0cee))

- Split schema initialization into focused sub-methods
  ([#416](https://github.com/n24q02m/mnemo-mcp/pull/416),
  [`4a000de`](https://github.com/n24q02m/mnemo-mcp/commit/4a000defbebba6f6f251c4d0aa2dd745db44e026))

- Update dependency cohere to v6
  ([`a4e36a9`](https://github.com/n24q02m/mnemo-mcp/commit/a4e36a98fab4a349beb1ce4a01a7fe992189edd7))

- Update docker/build-push-action digest to bcafcac
  ([`f0495c3`](https://github.com/n24q02m/mnemo-mcp/commit/f0495c3ded5f1c13c8be78b823304d7a9980fe8f))

- Update Pygments to 2.20.0 to fix ReDoS vulnerability
  ([`dacfdd6`](https://github.com/n24q02m/mnemo-mcp/commit/dacfdd6a636807e3b75658b86d3102e843366819))

- Update python:3.13-slim-bookworm docker digest to 061b6e5
  ([`0605066`](https://github.com/n24q02m/mnemo-mcp/commit/0605066b306ce97ffbe6476e3d3d4a88c654e684))

- Validate embedding_dims bounds before SQL interpolation
  ([`4477a4a`](https://github.com/n24q02m/mnemo-mcp/commit/4477a4a1b2781174ffaa25789b0514913c120bce))

- Wrap _conn and enforce vec dims for SQL testing
  ([`f6fe46f`](https://github.com/n24q02m/mnemo-mcp/commit/f6fe46fbf74b17265044df39ff80c481e7887e01))

- **db**: Enhance vector search mocking and dimension detection
  ([`f6fe46f`](https://github.com/n24q02m/mnemo-mcp/commit/f6fe46fbf74b17265044df39ff80c481e7887e01))

- **db**: Finalize security refactor with ruff formatting
  ([#395](https://github.com/n24q02m/mnemo-mcp/pull/395),
  [`6219d97`](https://github.com/n24q02m/mnemo-mcp/commit/6219d97fc274c797533d3143686035d7bfbf01a9))

- **db**: Prevent SQL injection via dynamic query construction
  ([#395](https://github.com/n24q02m/mnemo-mcp/pull/395),
  [`6219d97`](https://github.com/n24q02m/mnemo-mcp/commit/6219d97fc274c797533d3143686035d7bfbf01a9))

- **db**: Robust vector search testing and dimension management
  ([`f6fe46f`](https://github.com/n24q02m/mnemo-mcp/commit/f6fe46fbf74b17265044df39ff80c481e7887e01))

- **db**: Wrap vec_db._conn to fix the vec SQL for testing
  ([`f6fe46f`](https://github.com/n24q02m/mnemo-mcp/commit/f6fe46fbf74b17265044df39ff80c481e7887e01))

- **deps**: Bump actions/create-github-app-token digest to 1b10c78
  ([#435](https://github.com/n24q02m/mnemo-mcp/pull/435),
  [`610a973`](https://github.com/n24q02m/mnemo-mcp/commit/610a97358aa77903c8203723fc9baa4e64c39c30))

- **deps**: Bump actions/upload-artifact digest to 043fb46
  ([#436](https://github.com/n24q02m/mnemo-mcp/pull/436),
  [`3a84d92`](https://github.com/n24q02m/mnemo-mcp/commit/3a84d92c3e9a6d93b5a0225f295b9ddb68ba78db))

- **deps**: Bump non-major dependencies ([#437](https://github.com/n24q02m/mnemo-mcp/pull/437),
  [`2214f94`](https://github.com/n24q02m/mnemo-mcp/commit/2214f94c4874e29b78345f7c4713fbf84df3684d))

- **deps**: Update non-major dependencies ([#405](https://github.com/n24q02m/mnemo-mcp/pull/405),
  [`cb2d014`](https://github.com/n24q02m/mnemo-mcp/commit/cb2d01450628660e3a8f2573f7e18d9e423c155a))

- **server**: Log non-blocking exceptions in search and add handlers
  ([`3731e96`](https://github.com/n24q02m/mnemo-mcp/commit/3731e9672bac421ed9fe485f37573f8d69f7d273))

- **tests**: Resolve linting issues in security tests
  ([#395](https://github.com/n24q02m/mnemo-mcp/pull/395),
  [`6219d97`](https://github.com/n24q02m/mnemo-mcp/commit/6219d97fc274c797533d3143686035d7bfbf01a9))

### Chores

- **deps**: Bump cryptography in the uv group across 1 directory
  ([#407](https://github.com/n24q02m/mnemo-mcp/pull/407),
  [`6550b8c`](https://github.com/n24q02m/mnemo-mcp/commit/6550b8c1f12ed39de040240687afb4e652849a46))

- **deps**: Lock file maintenance ([#406](https://github.com/n24q02m/mnemo-mcp/pull/406),
  [`c42c4f8`](https://github.com/n24q02m/mnemo-mcp/commit/c42c4f8365e26927698dd54bc8194101a23cc790))

- **deps**: Update python:3.13-slim-bookworm docker digest to f13a6b7
  ([#404](https://github.com/n24q02m/mnemo-mcp/pull/404),
  [`c7989ec`](https://github.com/n24q02m/mnemo-mcp/commit/c7989ece8223420b76fbd76d572999754ae2198b))

- **deps**: Update step-security/harden-runner digest to f808768
  ([#411](https://github.com/n24q02m/mnemo-mcp/pull/411),
  [`cb5f6e1`](https://github.com/n24q02m/mnemo-mcp/commit/cb5f6e10943cde8ec4d7a2286b79ed6ef9dd321e))

### Features

- Add cross-OS CI matrix (ubuntu/windows/macos)
  ([`f57103e`](https://github.com/n24q02m/mnemo-mcp/commit/f57103e5863b221eeca4c2e0902cf5983f063c1b))

- Add error path tests for link_memory_entities and graph helpers
  ([`689f94a`](https://github.com/n24q02m/mnemo-mcp/commit/689f94af8c716578ac0a76fa9ae7e6f2136dbb41))

- Add GDrive device code flow and setup_complete_hook wiring
  ([`4717c7c`](https://github.com/n24q02m/mnemo-mcp/commit/4717c7c1ef79a7297344d82594704ad839e51c77))

- Add HTTP+OAuth transport, default to HTTP with --stdio fallback
  ([`2f76239`](https://github.com/n24q02m/mnemo-mcp/commit/2f76239206b63bec096164ed0914ae16201c523a))

- Migrate from mcp-relay-core to mcp-core
  ([`9839a2b`](https://github.com/n24q02m/mnemo-mcp/commit/9839a2b2885bbd9909e54ad8d985e0c88e811a09))

### Performance Improvements

- **db**: Implement FTS5 deferred join pattern in search
  ([#403](https://github.com/n24q02m/mnemo-mcp/pull/403),
  [`eed40e5`](https://github.com/n24q02m/mnemo-mcp/commit/eed40e5de56e7205d3ec0416c3e3dba1930ccb1d))

- **graph**: Replace inner join with semi-join for graph traversal
  ([`fc313d9`](https://github.com/n24q02m/mnemo-mcp/commit/fc313d9aa52cdc304b468895c192edfc7e9176cd))


## v1.19.0 (2026-04-07)

### Bug Fixes

- Add relay tests and isolate config-dependent test from env leak
  ([`7fc545f`](https://github.com/n24q02m/mnemo-mcp/commit/7fc545fe8254bd55d3fcfbf5663a6a57ecef1690))

- Always re-init embedding backend on setup_complete
  ([`aafa1a0`](https://github.com/n24q02m/mnemo-mcp/commit/aafa1a011b45709f83afc620b9ad15679f2d8b14))

- Remove BETA markers and promote relay as primary setup method
  ([`8f30f5b`](https://github.com/n24q02m/mnemo-mcp/commit/8f30f5be221d0ad38d882f58604bdd662945833e))

- Sync uv.lock with current version
  ([`9d73d94`](https://github.com/n24q02m/mnemo-mcp/commit/9d73d94916bf46ccb874f0e1d5a6100bbd5f85ca))

### Features

- Migrate code review from Qodo to CodeRabbit
  ([#369](https://github.com/n24q02m/mnemo-mcp/pull/369),
  [`a314243`](https://github.com/n24q02m/mnemo-mcp/commit/a314243eb3ddf8437abaae145d58eb0bcc405e1c))


## v1.18.5-beta.1 (2026-04-07)

### Bug Fixes

- Persist GDrive folder ID to prevent duplicate folder creation
  ([`619a68e`](https://github.com/n24q02m/mnemo-mcp/commit/619a68e7701a97bb4a2eb97ae4143af5d6cb7fa0))


## v1.18.4 (2026-04-06)

### Bug Fixes

- Use setup_providers() mode in setup_complete embedding re-init
  ([`c6507c3`](https://github.com/n24q02m/mnemo-mcp/commit/c6507c323fcaff56810da395898b4f9ecc4f7b45))


## v1.18.3 (2026-04-06)

### Bug Fixes

- Re-init embedding backend in setup_complete after credentials loaded
  ([`a82755c`](https://github.com/n24q02m/mnemo-mcp/commit/a82755c48d1632a564f3e70dfabfb4f4d4527865))


## v1.18.2 (2026-04-06)

### Bug Fixes

- Share cloud keys to peer servers when loading from config on startup
  ([`f56a979`](https://github.com/n24q02m/mnemo-mcp/commit/f56a9798d1a175c78ce2c564af3d51237eb524bc))


## v1.18.1 (2026-04-06)

### Bug Fixes

- Send complete message to browser after relay and trigger GDrive OAuth
  ([`7e5f5af`](https://github.com/n24q02m/mnemo-mcp/commit/7e5f5af8507b3d3d63c2ed2ba62b2c1b0abfc61b))


## v1.18.0 (2026-04-06)

### Features

- Remove auto-fallback from mnemo-mcp credential-aware embedding init
  ([`fde8e53`](https://github.com/n24q02m/mnemo-mcp/commit/fde8e5339ea5fbfdfb09ef448e0e922c70f5b030))


## v1.17.0 (2026-04-06)

### Bug Fixes

- Mark relay as BETA, promote env vars as primary setup method
  ([`faa7dee`](https://github.com/n24q02m/mnemo-mcp/commit/faa7dee7dc747a55ef4e3497f746a9a57f729b4b))

### Features

- Non-blocking relay with state machine and lazy trigger
  ([`2c314e9`](https://github.com/n24q02m/mnemo-mcp/commit/2c314e9727cb0b5d1b25106ae19d71f21dab19a0))


## v1.16.0 (2026-04-04)

### Bug Fixes

- Add error path tests for GPU detection and link_memory_entities logging
  ([#343](https://github.com/n24q02m/mnemo-mcp/pull/343),
  [`1cea41e`](https://github.com/n24q02m/mnemo-mcp/commit/1cea41e1f8723a23fa39896a35a9bb6a9f4e2409))

- Remove exposed model name from setup guide
  ([`41713cf`](https://github.com/n24q02m/mnemo-mcp/commit/41713cfc9adcf1ade95f5575dd565a0a49ddaf3d))

### Features

- Add agent/manual setup guides, simplify README, cleanup root
  ([`9062564`](https://github.com/n24q02m/mnemo-mcp/commit/9062564ebadba9d1a2006b3d626f7fa7f3fcfb70))


## v1.15.1 (2026-04-03)

### Bug Fixes

- Consolidate Jules PR review -- security hardening, N+1 query fixes, dep updates
  ([#321](https://github.com/n24q02m/mnemo-mcp/pull/321),
  [`8f3b59d`](https://github.com/n24q02m/mnemo-mcp/commit/8f3b59daa0580d666f567d1c46bfbd2b57e37e2f))

- Scope marketplace sync token to claude-plugins repo
  ([`0bf1d5d`](https://github.com/n24q02m/mnemo-mcp/commit/0bf1d5d1c9567bd2db2cf5679879912fa0daffa0))


## v1.15.0 (2026-04-03)

### Features

- Remove deprecated Gemini CLI extension support
  ([`75a18b3`](https://github.com/n24q02m/mnemo-mcp/commit/75a18b35f7164df335b6e2e4a2d84aaedb876e39))


## v1.15.0-beta.1 (2026-04-03)

### Bug Fixes

- E2E relay test for auto-trigger servers and Windows compatibility
  ([`c74450e`](https://github.com/n24q02m/mnemo-mcp/commit/c74450e3b7479149064c42ed1bf49a4c3879098a))

### Features

- Add E2E test with relay/env/plugin + GDrive OAuth
  ([`34b1d2d`](https://github.com/n24q02m/mnemo-mcp/commit/34b1d2dd10352d9205be341070219e17954435bc))


## v1.14.0 (2026-04-01)

### Bug Fixes

- Remove GOOGLE_DRIVE_CLIENT_ID from relay form
  ([`1d913b2`](https://github.com/n24q02m/mnemo-mcp/commit/1d913b285534ed4a464084f442842e5d44a1a6c7))

- Resolve relay schema, sync_enabled, and apply_config bugs
  ([`35dd5ce`](https://github.com/n24q02m/mnemo-mcp/commit/35dd5cedfc5f98877f7b699d434d2945518c4dfb))

- Send complete message AFTER GDrive OAuth, not before
  ([`2f1a614`](https://github.com/n24q02m/mnemo-mcp/commit/2f1a614b362f6f5d160f60815880c2bde73dcf0e))

- Trigger GDrive OAuth from default settings, increase timeout to 300s
  ([`4f91ea4`](https://github.com/n24q02m/mnemo-mcp/commit/4f91ea4f3e68e2398cd39622919030e98f7be2ec))

### Continuous Integration

- Fix Qodo vertex_ai config and VERTEXAI_LOCATION
  ([`13062e8`](https://github.com/n24q02m/mnemo-mcp/commit/13062e8b6ed322b21054f866bc1b36b8a97d8220))

- **cd**: Add plugin marketplace sync on stable release
  ([`22d27ee`](https://github.com/n24q02m/mnemo-mcp/commit/22d27ee9dfbf6c45e9cbcd386b936b5255d744af))

### Features

- Add coverage threshold and boost coverage to 97%
  ([`3bb58d4`](https://github.com/n24q02m/mnemo-mcp/commit/3bb58d4a998c4442c62a2299ee78dcb9bbd0887a))

- Add GDrive OAuth client_secret for Device Code token exchange
  ([`438b21e`](https://github.com/n24q02m/mnemo-mcp/commit/438b21e1e8cb5c44efc1b33db41bc239c45271ca))

- Ship default GDrive OAuth Client ID, remove from relay form
  ([`a6d7b2e`](https://github.com/n24q02m/mnemo-mcp/commit/a6d7b2ed32981e4187ab2ee2f3e8455885ba4a12))


## v1.14.0-beta.1 (2026-03-31)

### Features

- Redesign relay with capability info, always-on GDrive sync
  ([`6be0700`](https://github.com/n24q02m/mnemo-mcp/commit/6be07005b5f7ba11f476e91a64b9ebeac57d8afb))

### Refactoring

- Merge setup tool into config tool
  ([`526ed2e`](https://github.com/n24q02m/mnemo-mcp/commit/526ed2eccacb07d0aaa96cabf83765a8990f823f))


## v1.13.1 (2026-03-28)

### Bug Fixes

- Bump mcp-relay-core to >=1.0.5
  ([`5719429`](https://github.com/n24q02m/mnemo-mcp/commit/57194298cfa1491b09c2e71b6cdc40577d36b404))

- Increase relay timeout from 30s to 120s
  ([`e6908d8`](https://github.com/n24q02m/mnemo-mcp/commit/e6908d8e6ac1c3c6e136699aeac6d71d8e26031a))

- Use read_config instead of resolve_config for relay config loading
  ([`cf4b02f`](https://github.com/n24q02m/mnemo-mcp/commit/cf4b02ff483d49e36f6404ef5c382f6a04058d02))

### Chores

- **deps**: Bump the uv group across 1 directory with 2 updates
  ([#270](https://github.com/n24q02m/mnemo-mcp/pull/270),
  [`c0cb098`](https://github.com/n24q02m/mnemo-mcp/commit/c0cb0985f3ffedd1c864e87bd906b4636806e3d6))

- **deps**: Update actions/create-github-app-token action to v3
  ([#268](https://github.com/n24q02m/mnemo-mcp/pull/268),
  [`31e5889`](https://github.com/n24q02m/mnemo-mcp/commit/31e58896573fcee91295cf3450ab9584351d0442))

- **deps**: Update google-github-actions/auth action to v3
  ([#269](https://github.com/n24q02m/mnemo-mcp/pull/269),
  [`d303e29`](https://github.com/n24q02m/mnemo-mcp/commit/d303e29c0c96fc37a81af8bb795d549db9d43d5c))

### Documentation

- Fix stale pytest addopts and env var in CLAUDE.md
  ([`088ebe7`](https://github.com/n24q02m/mnemo-mcp/commit/088ebe752f6dd3470bdfddc65e6a6d7f0ff832ad))

- Fix stale rclone reference in AGENTS.md
  ([`75682b3`](https://github.com/n24q02m/mnemo-mcp/commit/75682b3c1fcc35a4886637a6287654a52613f429))

- Update CLAUDE.md with missing modules, env vars, and dep version
  ([`4d00e09`](https://github.com/n24q02m/mnemo-mcp/commit/4d00e09b5dfcab93a28c66631ef81729be8279a6))

### Testing

- Update relay_setup tests for read_config refactor
  ([`afe3a66`](https://github.com/n24q02m/mnemo-mcp/commit/afe3a66e2abd730e5658ba5e6f213beb7e84e513))


## v1.13.0 (2026-03-27)

### Bug Fixes

- Credential resolution order -- relay only when no local credentials
  ([`6d8977b`](https://github.com/n24q02m/mnemo-mcp/commit/6d8977b31d157189cfa92406ef2ae3ca1fc627e8))

- Pin Docker base images to SHA digests
  ([`6c30030`](https://github.com/n24q02m/mnemo-mcp/commit/6c3003077dec64eec5fbb5e590a79165f900ff2e))

- Pin pre-commit hooks to commit SHA
  ([`dec810c`](https://github.com/n24q02m/mnemo-mcp/commit/dec810c1a2e5d9ca813e8b8768f4ca26124493d6))

- Resolve ty type check errors
  ([`84210e6`](https://github.com/n24q02m/mnemo-mcp/commit/84210e6a22d0f9d2ae74dc81010d7ae5d6c1c95a))

- Send complete message to relay page after config saved
  ([`89f731f`](https://github.com/n24q02m/mnemo-mcp/commit/89f731f955fec5d2841e7ffa12679fca44b35de4))

- **cd**: Remove empty env blocks from OIDC migration
  ([`76124bb`](https://github.com/n24q02m/mnemo-mcp/commit/76124bbb6fb5a3338a710144223045a4db342881))

- **cd**: Replace GH_PAT with GitHub App installation token
  ([`f90d67f`](https://github.com/n24q02m/mnemo-mcp/commit/f90d67f92e815bdcce2a6141b38c980a1b7f35c4))

- **cd**: Use PyPI OIDC trusted publishing instead of PYPI_TOKEN
  ([`8610942`](https://github.com/n24q02m/mnemo-mcp/commit/8610942d526ddd54587fcb8519f4fbfb8da9e425))

- **ci**: Consolidate SMTP_USERNAME and NOTIFY_EMAIL into one secret
  ([`a2a5e7f`](https://github.com/n24q02m/mnemo-mcp/commit/a2a5e7f5ac4659fa708794bb6f165ca65af29e1f))

- **ci**: Consolidate SMTP_USERNAME+PASSWORD into SMTP_CREDENTIAL
  ([`fac7205`](https://github.com/n24q02m/mnemo-mcp/commit/fac72052f0fed5147ced263487e08a1f9eee829f))

- **ci**: Remove CODECOV_TOKEN, use tokenless upload
  ([`66d2ce1`](https://github.com/n24q02m/mnemo-mcp/commit/66d2ce10d17cc1557617196d422cef498e3899b4))

- **ci**: Use Vertex AI WIF instead of GEMINI_API_KEY for code review
  ([`5b6bbb7`](https://github.com/n24q02m/mnemo-mcp/commit/5b6bbb7b0ed94288a183917088584729c8eaad1e))

- **deps**: Update dependency openai to >=2.30.0
  ([#263](https://github.com/n24q02m/mnemo-mcp/pull/263),
  [`3cd022f`](https://github.com/n24q02m/mnemo-mcp/commit/3cd022febcd1f71a02016faf0805411cdf81e629))

- **deps**: Update non-major dependencies ([#241](https://github.com/n24q02m/mnemo-mcp/pull/241),
  [`b3925ee`](https://github.com/n24q02m/mnemo-mcp/commit/b3925ee166b14057d3199eb8a7fa99f10dc46679))

- **tests**: Clear env vars before testing ensure_config file/relay paths
  ([`1015f30`](https://github.com/n24q02m/mnemo-mcp/commit/1015f30e7716c9fbb2dcdd81aa05813b8b05697e))

- **tests**: Update mock paths for lazy imports
  ([`3ed82a9`](https://github.com/n24q02m/mnemo-mcp/commit/3ed82a9da75b322b60624bdfe005d303e1702fa8))

- **tests**: Use Any type to satisfy ty 0.0.25 stricter checking
  ([`e21c383`](https://github.com/n24q02m/mnemo-mcp/commit/e21c383c3fbe1b95c9fcb5138d9ea92be5e6ac5e))

### Chores

- **deps**: Lock file maintenance ([#265](https://github.com/n24q02m/mnemo-mcp/pull/265),
  [`ea0cc69`](https://github.com/n24q02m/mnemo-mcp/commit/ea0cc69c81a06c2877958da960966d336b711e3d))

- **deps**: Update codecov/codecov-action action to v6
  ([#264](https://github.com/n24q02m/mnemo-mcp/pull/264),
  [`b6f73fd`](https://github.com/n24q02m/mnemo-mcp/commit/b6f73fdccaf6db26d41416d02b043b683de1b3d8))

### Features

- Optimize N+1 query in entity upsertion ([#252](https://github.com/n24q02m/mnemo-mcp/pull/252),
  [`f2635b5`](https://github.com/n24q02m/mnemo-mcp/commit/f2635b5c86327a94bd1141b3ec2f5f076003927b))

- Relay-first startup — always show relay URL
  ([`da342d6`](https://github.com/n24q02m/mnemo-mcp/commit/da342d635b951ca9d6a3f8a8ae710c7dcfe2fa4f))

- Replace rclone with Google Drive API for sync
  ([`0607fca`](https://github.com/n24q02m/mnemo-mcp/commit/0607fca119c716112a9a4deafd57a59d5e84af86))


## v1.12.0 (2026-03-26)

### Chores

- Add server.json to PSR version_variables, sync version
  ([`e8668b0`](https://github.com/n24q02m/mnemo-mcp/commit/e8668b086cf75d4b84d94735c7680b20681627ab))

- Clean up plugin manifest for best practices
  ([`50b245b`](https://github.com/n24q02m/mnemo-mcp/commit/50b245b36acbda42f65de8ce3301eb95951ec061))

### Documentation

- Fix marketplace references, improve Gemini CLI extension config
  ([`63144ec`](https://github.com/n24q02m/mnemo-mcp/commit/63144ec683a38f5f0040f53ac88f1078686a8aed))

- Standardize README structure
  ([`548a159`](https://github.com/n24q02m/mnemo-mcp/commit/548a159d35af3dfcf719d723b55b8a4965725588))


## v1.12.0-beta.1 (2026-03-25)

### Bug Fixes

- Remove litellm references, use API_KEYS for cloud mode
  ([#257](https://github.com/n24q02m/mnemo-mcp/pull/257),
  [`4d5b225`](https://github.com/n24q02m/mnemo-mcp/commit/4d5b225c7e0f8432a0b34a85ca7f209d9ede2cc8))

- Ruff format server.py and test_relay_setup.py
  ([#257](https://github.com/n24q02m/mnemo-mcp/pull/257),
  [`4d5b225`](https://github.com/n24q02m/mnemo-mcp/commit/4d5b225c7e0f8432a0b34a85ca7f209d9ede2cc8))

- Switch mcp-relay-core from git dep to published PyPI package
  ([#257](https://github.com/n24q02m/mnemo-mcp/pull/257),
  [`4d5b225`](https://github.com/n24q02m/mnemo-mcp/commit/4d5b225c7e0f8432a0b34a85ca7f209d9ede2cc8))

- Use direct provider API keys instead of API_KEYS format
  ([#257](https://github.com/n24q02m/mnemo-mcp/pull/257),
  [`4d5b225`](https://github.com/n24q02m/mnemo-mcp/commit/4d5b225c7e0f8432a0b34a85ca7f209d9ede2cc8))

### Documentation

- Add relay files to CLAUDE.md file structure
  ([`9737599`](https://github.com/n24q02m/mnemo-mcp/commit/9737599d14bd3798cecd65136a687ecd29171741))

- Add zero-config relay setup section to README
  ([`4c0e3b5`](https://github.com/n24q02m/mnemo-mcp/commit/4c0e3b50926a20b248b5c6d2e332001e77cf60d6))

### Features

- Integrate mcp-relay-core for zero-env-config proxy setup
  ([#257](https://github.com/n24q02m/mnemo-mcp/pull/257),
  [`4d5b225`](https://github.com/n24q02m/mnemo-mcp/commit/4d5b225c7e0f8432a0b34a85ca7f209d9ede2cc8))

- Zero-env-config relay setup via mcp-relay-core
  ([#257](https://github.com/n24q02m/mnemo-mcp/pull/257),
  [`4d5b225`](https://github.com/n24q02m/mnemo-mcp/commit/4d5b225c7e0f8432a0b34a85ca7f209d9ede2cc8))


## v1.11.0 (2026-03-25)

### Bug Fixes

- Add 'docs/' to .gitignore
  ([`a4ff2c4`](https://github.com/n24q02m/mnemo-mcp/commit/a4ff2c4e33163fc9cbd3084e6c7ddf32ae29bed1))

- Delete docs directory
  ([`407bc34`](https://github.com/n24q02m/mnemo-mcp/commit/407bc34adf61e0299f1b55bcd91ae4f562bd4079))


## v1.11.0-beta.2 (2026-03-25)

### Bug Fixes

- Correct default embed model to gemini-embedding-001 for public repos
  ([`c7676d5`](https://github.com/n24q02m/mnemo-mcp/commit/c7676d5387b565761d0249ced2e20e23fbf6e48a))

- Replace LiteLLM references with native SDK providers in docs
  ([`e28bedb`](https://github.com/n24q02m/mnemo-mcp/commit/e28bedb9f2bd79ea73a2a2213101ffb70ed2714e))

- Update AGENTS.md — remove litellm references
  ([`53fc993`](https://github.com/n24q02m/mnemo-mcp/commit/53fc99384804a0b95c50d29197b64ccfe44bdad4))

- Update README.md — remove litellm references, add multi-provider docs
  ([`212d950`](https://github.com/n24q02m/mnemo-mcp/commit/212d95038269ad0e86e21064bcd1e689d2e963d6))

### Features

- Upgrade to multi-provider embedding (jina > gemini > openai > cohere)
  ([`48102fe`](https://github.com/n24q02m/mnemo-mcp/commit/48102fee608988fcb8ad88a1874330fd95676769))


## v1.11.0-beta.1 (2026-03-25)

### Bug Fixes

- Add --python 3.13 to uvx command in README
  ([`c0ae1d4`](https://github.com/n24q02m/mnemo-mcp/commit/c0ae1d40238941452c47d52c0819bfd61cf7be76))

- Auto-sync plugin.json version via PSR
  ([`9cad0b6`](https://github.com/n24q02m/mnemo-mcp/commit/9cad0b60b7475ff40a02a77c2ebaa11e88853c4f))

- Correct plugin install commands per official docs
  ([`e046f35`](https://github.com/n24q02m/mnemo-mcp/commit/e046f35418996d727e2788a0ced815fc454364c4))

- Pin third-party GitHub Actions to SHA hashes
  ([`7c08894`](https://github.com/n24q02m/mnemo-mcp/commit/7c08894ee0bb862b4e01fd2883d1ae7fbae7670b))

- Remove empty env vars from plugin configs to prevent empty-string bugs
  ([`365beda`](https://github.com/n24q02m/mnemo-mcp/commit/365beda42761993bd80755122904fe893b96348a))

- Remove env from README MCP config examples
  ([`038865e`](https://github.com/n24q02m/mnemo-mcp/commit/038865ecfe4bff21976c73a1c5aea21dad1339b1))

- Remove env vars from plugin.json to prevent overwriting user config
  ([`e84d698`](https://github.com/n24q02m/mnemo-mcp/commit/e84d698311df3fed063f2fccd6faf28612c84e5c))

- Remove pr-title-check job from CI
  ([`f564bc4`](https://github.com/n24q02m/mnemo-mcp/commit/f564bc4f27f7a9761fa6b2a781b1dee2835c4509))

- Resolve ty type check errors (Context | None, raise guard, assert)
  ([`293dad6`](https://github.com/n24q02m/mnemo-mcp/commit/293dad6c35b34f719d6e5f0a6877ebac2374c12d))

- Resolve ty type check errors in native SDK migration
  ([`f868e02`](https://github.com/n24q02m/mnemo-mcp/commit/f868e02366cde1e225007b493bcaa053b2772033))

- Split PSR version_toml — move JSON files to version_variables
  ([`3b2073d`](https://github.com/n24q02m/mnemo-mcp/commit/3b2073d041923ba872dce8fb1c9c5003b0518d99))

- Sync plugin.json version and add skills/hooks references
  ([`3aa462a`](https://github.com/n24q02m/mnemo-mcp/commit/3aa462a116cadb66c2730bf762151d3dc32135b1))

- Sync uv.lock with native provider SDK dependencies
  ([`73031a8`](https://github.com/n24q02m/mnemo-mcp/commit/73031a86377c634b62724be84e9343fe48b0be04))

- Unify Plugin install section with marketplace + individual options
  ([`066166c`](https://github.com/n24q02m/mnemo-mcp/commit/066166ce0e85ea89effa7c3152b77b77f8f03b02))

- Update ruff pre-commit hook to v0.15.7
  ([`b674129`](https://github.com/n24q02m/mnemo-mcp/commit/b6741296b68eb5f5031d81e5abd65ad728c43c82))

### Features

- Add complete env vars and pipx mode to plugin config
  ([`170911f`](https://github.com/n24q02m/mnemo-mcp/commit/170911fd3d0130be5e6644441d4ae70881c52d83))

- Add Gemini CLI extension config with PSR version sync
  ([`d9325f6`](https://github.com/n24q02m/mnemo-mcp/commit/d9325f6180fa74ba65405191bda375a96eeac611))

- Add model config env vars and default sync enabled
  ([`19c2f49`](https://github.com/n24q02m/mnemo-mcp/commit/19c2f49227087cb76a82164b8a523ef8a76b7b4b))

- Multi-mode plugin config (stdio + docker + http)
  ([`f356f52`](https://github.com/n24q02m/mnemo-mcp/commit/f356f52e0f5b112f60b00dc65eb9255932809e89))

- Standardize README with MCP Resources, Security, collapsible clients
  ([`b9b5e89`](https://github.com/n24q02m/mnemo-mcp/commit/b9b5e89c1714f11f6f8091e9a97f06c17bf1dc67))

### Refactoring

- Remove litellm entirely, use Cohere + native SDKs
  ([`c9adeec`](https://github.com/n24q02m/mnemo-mcp/commit/c9adeec96fbaaf1f649d0a2defdb1079658f5398))


## v1.10.0 (2026-03-24)

### Bug Fixes

- Add gitleaks secret detection to pre-commit hooks
  ([`69be394`](https://github.com/n24q02m/mnemo-mcp/commit/69be39435884b986647bb90ac8e5f35ff8aa1f8e))

- Apply ruff formatting to pass CI
  ([`a985f74`](https://github.com/n24q02m/mnemo-mcp/commit/a985f74c0cd2ab883f7e63ed537a5a491d52a34c))

- Resolve lint errors in full test files
  ([`ce7aa59`](https://github.com/n24q02m/mnemo-mcp/commit/ce7aa5983c1bb81ad338f577c63dd8c8bc13cb34))

### Testing

- Add cloud embedding mode tests with API_KEYS
  ([`2f05b0f`](https://github.com/n24q02m/mnemo-mcp/commit/2f05b0f7339ef085a8c56fb6ddd08d92ae395691))

- Add full/real live tests for all tools and modes
  ([`f0741f3`](https://github.com/n24q02m/mnemo-mcp/commit/f0741f3eff99032de077326ae942fab5a58a04d8))


## v1.10.0-beta.1 (2026-03-23)

### Bug Fixes

- Add difflib-based corrective errors for LLM call pass rate
  ([`73b38e1`](https://github.com/n24q02m/mnemo-mcp/commit/73b38e1a8806188fb53dc81ae3566a6367a9ebb7))

- Correct plugin packaging paths and marketplace schema
  ([`2839df6`](https://github.com/n24q02m/mnemo-mcp/commit/2839df6a11d6d5e74e13eef51173af9ecd99036c))

- Move _EMBEDDING_CANDIDATES to config.py to avoid circular import
  ([`62a8352`](https://github.com/n24q02m/mnemo-mcp/commit/62a835236058c3f457846af598e35187fdbbadb8))

- Standardize README structure with plugin-first Quick Start
  ([`d468381`](https://github.com/n24q02m/mnemo-mcp/commit/d4683816f8f885f5ad67282cb1db52f8cda3e29a))

- Sync plugin.json and server.json to v1.9.1
  ([`bad0418`](https://github.com/n24q02m/mnemo-mcp/commit/bad04185fdff9d593788c93653b7df9b5e5202de))

- Update hook message with all tools and standardize pre-commit config
  ([`bc29e99`](https://github.com/n24q02m/mnemo-mcp/commit/bc29e9966114ae703cd083bc4452678c710ef04d))

- **deps**: Update non-major dependencies ([#235](https://github.com/n24q02m/mnemo-mcp/pull/235),
  [`4d58dc1`](https://github.com/n24q02m/mnemo-mcp/commit/4d58dc15a0dc19eab6fcf4b9a680e59b7a1aacea))

### Chores

- **deps**: Lock file maintenance ([#236](https://github.com/n24q02m/mnemo-mcp/pull/236),
  [`9c8dc75`](https://github.com/n24q02m/mnemo-mcp/commit/9c8dc7519d1dc4d751b390a99e710a33d3528b4a))

### Documentation

- Add warmup/setup_sync actions and rerank_top_n to README
  ([`1efaf6f`](https://github.com/n24q02m/mnemo-mcp/commit/1efaf6f68554b35bfb44f4827fa7dc5e53711546))

- Add warmup/setup_sync to config.md, update sync prerequisites
  ([`eef88b3`](https://github.com/n24q02m/mnemo-mcp/commit/eef88b31de5b0f62ede01a316469ff9aa14794e2))

- Standardize README sections and sync Also by table
  ([`0c73d6d`](https://github.com/n24q02m/mnemo-mcp/commit/0c73d6d3d8a4abc6975f62adcc8623e9e822e2e3))

### Features

- Add plugin packaging (skills, hooks, plugin manifest)
  ([`db8a28c`](https://github.com/n24q02m/mnemo-mcp/commit/db8a28c0f408dc320ec1a2efa74d43a4383f1a90))

- Add warmup and setup_sync as config tool actions
  ([`a89c538`](https://github.com/n24q02m/mnemo-mcp/commit/a89c5388fc8ca30604e0d8ebc90c803d06e98e51))

- Improve memory tool descriptions for better LLM pass rate
  ([`c9710af`](https://github.com/n24q02m/mnemo-mcp/commit/c9710af9b1dbc24fdda0a9f756b62a8eb1f905f0))

### Performance Improvements

- **db**: Add index on archived_at for list_archived pagination
  ([#238](https://github.com/n24q02m/mnemo-mcp/pull/238),
  [`3417fa4`](https://github.com/n24q02m/mnemo-mcp/commit/3417fa4339feee881e9249936c4ef3fd94b3465e))

### Refactoring

- Migrate warmup/setup-sync CLI to MCP setup tool
  ([`7ec610e`](https://github.com/n24q02m/mnemo-mcp/commit/7ec610e973405657873e1c20ca52d97a3330523e))

- Redesign skills/hooks per approved spec
  ([`df05f8b`](https://github.com/n24q02m/mnemo-mcp/commit/df05f8b5d1fb09f2a192a8e2a39be94918e93e70))

### Testing

- Add pytest-based live MCP protocol tests
  ([`5aa1f7f`](https://github.com/n24q02m/mnemo-mcp/commit/5aa1f7f42dbcaf44fdcef204044b7b19342b361b))


## v1.9.1 (2026-03-20)

### Bug Fixes

- Support Cohere embedding provider with dimensions fallback
  ([`db3a45d`](https://github.com/n24q02m/mnemo-mcp/commit/db3a45daa665beeeb89a4ed265754bd894810d36))

### Chores

- Add .code-review-graph/ to .gitignore
  ([`edee24a`](https://github.com/n24q02m/mnemo-mcp/commit/edee24a3c8019afb34f9ff64dbdb259117720384))

### Performance Improvements

- Optimize knowledge graph relation insertion using unique index
  ([#234](https://github.com/n24q02m/mnemo-mcp/pull/234),
  [`bff2f28`](https://github.com/n24q02m/mnemo-mcp/commit/bff2f28a445e2994476a9e9ad5d2770fd31861e5))


## v1.9.0 (2026-03-20)

### Bug Fixes

- Add assert mem is not None in test_db.py ([#223](https://github.com/n24q02m/mnemo-mcp/pull/223),
  [`8533ca1`](https://github.com/n24q02m/mnemo-mcp/commit/8533ca13b2313e18d21f221140e21e5dc934c7f4))

- Add coverage for json decode error in sync auth extraction]
  ([#226](https://github.com/n24q02m/mnemo-mcp/pull/226),
  [`743a8e3`](https://github.com/n24q02m/mnemo-mcp/commit/743a8e340cf70a26ad29dfa60a88557060ebb4b8))

- Chore: Rename `# Fixtures` to `# Test Setup` in test_db_coverage.py
  ([#220](https://github.com/n24q02m/mnemo-mcp/pull/220),
  [`1c48ce1`](https://github.com/n24q02m/mnemo-mcp/commit/1c48ce106e7b3f66aea916efe9137c02b749f5e6))

- Correct ruff formatting error in test_graph.py
  ([#226](https://github.com/n24q02m/mnemo-mcp/pull/226),
  [`743a8e3`](https://github.com/n24q02m/mnemo-mcp/commit/743a8e340cf70a26ad29dfa60a88557060ebb4b8))

- Fix DoS risk via parameter clamping in handler functions
  ([#213](https://github.com/n24q02m/mnemo-mcp/pull/213),
  [`11ee352`](https://github.com/n24q02m/mnemo-mcp/commit/11ee35235c13dff2cf7eb937a9c8c41df00f47f1))

- Fix false positive action task by replacing comment keyword
  ([#219](https://github.com/n24q02m/mnemo-mcp/pull/219),
  [`f227714`](https://github.com/n24q02m/mnemo-mcp/commit/f22771425905e786147f4b46cd493ffa7d46cb40))

- Fix missing test coverage for OSError in token_store]
  ([#229](https://github.com/n24q02m/mnemo-mcp/pull/229),
  [`c2f362c`](https://github.com/n24q02m/mnemo-mcp/commit/c2f362c22d0b74537d316714bee0d227919457c4))

- Fix potential SQL injection in vector table creation
  ([#224](https://github.com/n24q02m/mnemo-mcp/pull/224),
  [`d720304`](https://github.com/n24q02m/mnemo-mcp/commit/d720304edf83cf791c9b2bebe7fa8d1b3cd66565))

- Format tests/test_graph.py to pass ruff formatting check
  ([#223](https://github.com/n24q02m/mnemo-mcp/pull/223),
  [`8533ca1`](https://github.com/n24q02m/mnemo-mcp/commit/8533ca13b2313e18d21f221140e21e5dc934c7f4))

- Improve test coverage from 94% to 97% and remove dead code
  ([`a6df5c1`](https://github.com/n24q02m/mnemo-mcp/commit/a6df5c1a5102cec1661ffe65c732ef01d497a614))

- Remove 27 duplicate `assert mem is not None` lines in test_db.py
  ([#233](https://github.com/n24q02m/mnemo-mcp/pull/233),
  [`f0a4493`](https://github.com/n24q02m/mnemo-mcp/commit/f0a449375a84a1a933f6b917a040f22480a54f91))

- Testing improvement] Add error test for config GPU detection
  ([#223](https://github.com/n24q02m/mnemo-mcp/pull/223),
  [`8533ca1`](https://github.com/n24q02m/mnemo-mcp/commit/8533ca13b2313e18d21f221140e21e5dc934c7f4))

- Testing improvement] Add tests for config GGUF support ImportError branch
  ([#228](https://github.com/n24q02m/mnemo-mcp/pull/228),
  [`70a7c2c`](https://github.com/n24q02m/mnemo-mcp/commit/70a7c2ca2954f41969908f69059dce3004a04d0f))

- **ci**: Remove job-level continue-on-error from dependency-review
  ([`bb6907a`](https://github.com/n24q02m/mnemo-mcp/commit/bb6907a4759e2f221d4458a74b72326c137fc23b))

- **deps**: Update dependency qwen3-embed to >=1.5.0
  ([#214](https://github.com/n24q02m/mnemo-mcp/pull/214),
  [`aa8142a`](https://github.com/n24q02m/mnemo-mcp/commit/aa8142a50865015383e067f5557a3d913e7382bf))

### Chores

- Align CI/CD action versions
  ([`9f564ec`](https://github.com/n24q02m/mnemo-mcp/commit/9f564ec38dba325c681c10b87faaa0091b5001c5))

- Remove fix_ty.py to pass ruff checks ([#223](https://github.com/n24q02m/mnemo-mcp/pull/223),
  [`8533ca1`](https://github.com/n24q02m/mnemo-mcp/commit/8533ca13b2313e18d21f221140e21e5dc934c7f4))

- Rename `# Fixtures` to `# Test Setup` in test_db_coverage.py
  ([#220](https://github.com/n24q02m/mnemo-mcp/pull/220),
  [`1c48ce1`](https://github.com/n24q02m/mnemo-mcp/commit/1c48ce106e7b3f66aea916efe9137c02b749f5e6))

- **deps**: Lock file maintenance ([#211](https://github.com/n24q02m/mnemo-mcp/pull/211),
  [`76eeeee`](https://github.com/n24q02m/mnemo-mcp/commit/76eeeeeb1b2037bdf0f623072e3a28cfd3dfb31c))

- **deps**: Update codecov/codecov-action digest to 1af5884
  ([#216](https://github.com/n24q02m/mnemo-mcp/pull/216),
  [`212b072`](https://github.com/n24q02m/mnemo-mcp/commit/212b072fc264cc21876c86aacaf772da662ae6c9))

- **deps**: Update dawidd6/action-send-mail action to v16
  ([#215](https://github.com/n24q02m/mnemo-mcp/pull/215),
  [`73e73b2`](https://github.com/n24q02m/mnemo-mcp/commit/73e73b2704167357dc3b3bf3859c7a96fdfb5b5c))

### Documentation

- Update README for v1.8.0 features and Jina AI priority
  ([`dcaac15`](https://github.com/n24q02m/mnemo-mcp/commit/dcaac156259028a304988aace2fd16ab4f76451e))

### Features

- Optimize archive_old_memories using executemany
  ([#222](https://github.com/n24q02m/mnemo-mcp/pull/222),
  [`aba7352`](https://github.com/n24q02m/mnemo-mcp/commit/aba73520be32acabbb6cf46b4a248ffc46fbdff8))

- Optimize relation creation via executemany ([#231](https://github.com/n24q02m/mnemo-mcp/pull/231),
  [`c5d1d6d`](https://github.com/n24q02m/mnemo-mcp/commit/c5d1d6da349f296fbcd19e62eafd90e1d8d2d9f4))

- Optimize struct.pack serialization for vectors
  ([#212](https://github.com/n24q02m/mnemo-mcp/pull/212),
  [`789c6cc`](https://github.com/n24q02m/mnemo-mcp/commit/789c6ccf71f80c9461e431bb1f78214fa00e4da0))

- Remove unused legacy embed_texts] ([#225](https://github.com/n24q02m/mnemo-mcp/pull/225),
  [`cd975af`](https://github.com/n24q02m/mnemo-mcp/commit/cd975afc06edf064ba8c308019e9af14aca59164))

- Testing] Add missing coverage for local embedding init failure
  ([#221](https://github.com/n24q02m/mnemo-mcp/pull/221),
  [`547c38f`](https://github.com/n24q02m/mnemo-mcp/commit/547c38fca51027ab71286cd179fcbd5186573b2e))

### Refactoring

- Remove custom endpoint support (EMBEDDING_API_BASE, RERANK_API_BASE)
  ([`8364d50`](https://github.com/n24q02m/mnemo-mcp/commit/8364d506d1b678a60935ff2c19dca04badc4967f))

### Testing

- Add coverage for JSONDecodeError in _interactive_auth
  ([#226](https://github.com/n24q02m/mnemo-mcp/pull/226),
  [`743a8e3`](https://github.com/n24q02m/mnemo-mcp/commit/743a8e340cf70a26ad29dfa60a88557060ebb4b8))

- Fix type checking errors in test_db.py ([#226](https://github.com/n24q02m/mnemo-mcp/pull/226),
  [`743a8e3`](https://github.com/n24q02m/mnemo-mcp/commit/743a8e340cf70a26ad29dfa60a88557060ebb4b8))


## v1.8.1 (2026-03-17)

### Bug Fixes

- Security hardening from code audit
  ([`d3944dd`](https://github.com/n24q02m/mnemo-mcp/commit/d3944dde7bb71ef438d9e0ce833c67663eebcd7e))


## v1.8.0 (2026-03-17)

### Bug Fixes

- Add missing error test in server embedding initialization
  ([#203](https://github.com/n24q02m/mnemo-mcp/pull/203),
  [`0eb3ef5`](https://github.com/n24q02m/mnemo-mcp/commit/0eb3ef5b9d2dc4cb18541cb3a81c67e7416408d8))

- Add missing OSError test for chmod in token store
  ([#199](https://github.com/n24q02m/mnemo-mcp/pull/199),
  [`8d52eed`](https://github.com/n24q02m/mnemo-mcp/commit/8d52eed8a098645e5627ab8746fc3a4c0510add0))

- Disable mise runtime updates in Renovate
  ([`7f99704`](https://github.com/n24q02m/mnemo-mcp/commit/7f997046d02f35ea87e512c0ba7eb4a7444524e4))

- Fix Potential Command Injection in subprocess.run
  ([#204](https://github.com/n24q02m/mnemo-mcp/pull/204),
  [`c1a8012`](https://github.com/n24q02m/mnemo-mcp/commit/c1a8012f16fae3d60082eb6af346e44921e7c23f))

- Fix SQL injection vulnerability in vector table creation
  ([#208](https://github.com/n24q02m/mnemo-mcp/pull/208),
  [`7a95b37`](https://github.com/n24q02m/mnemo-mcp/commit/7a95b370a1cac8aafd5ec3c4867066e24f0455dc))

- Remove mcp-name entry from README
  ([`dfe85d7`](https://github.com/n24q02m/mnemo-mcp/commit/dfe85d75719057b54225ac738004f4e845400487))

- **ci**: Use pull_request_target for jobs requiring secrets
  ([`823944a`](https://github.com/n24q02m/mnemo-mcp/commit/823944a3117fa41b537897c736cdf94aa829d436))

- **deps**: Update dependency qwen3-embed to >=1.4.3
  ([#188](https://github.com/n24q02m/mnemo-mcp/pull/188),
  [`bad4d15`](https://github.com/n24q02m/mnemo-mcp/commit/bad4d15ca0b34ed5fc06457836f400df4bc571cd))

### Chores

- Add glama.json for Glama directory listing
  ([`6bdc37d`](https://github.com/n24q02m/mnemo-mcp/commit/6bdc37d7081472b421e6dc8253077d65b775791f))

- Standardize repo files across MCP server portfolio
  ([`ce4a6b7`](https://github.com/n24q02m/mnemo-mcp/commit/ce4a6b7b55f9b6d00b05870f07860ea853d836d3))

- **deps**: Lock file maintenance ([#190](https://github.com/n24q02m/mnemo-mcp/pull/190),
  [`b26ab14`](https://github.com/n24q02m/mnemo-mcp/commit/b26ab14756de2015d313863438fe8f2df4a26490))

- **deps**: Update actions/download-artifact digest to 3e5f45b
  ([#187](https://github.com/n24q02m/mnemo-mcp/pull/187),
  [`32e0d32`](https://github.com/n24q02m/mnemo-mcp/commit/32e0d3205cef5cce0e85350e04cd5c3d48884485))

- **deps**: Update astral-sh/setup-uv digest to 37802ad
  ([#194](https://github.com/n24q02m/mnemo-mcp/pull/194),
  [`2c0b989`](https://github.com/n24q02m/mnemo-mcp/commit/2c0b989929eddea70051515853a4885c8731f98f))

- **deps**: Update dawidd6/action-send-mail action to v15
  ([#209](https://github.com/n24q02m/mnemo-mcp/pull/209),
  [`ce2b5a5`](https://github.com/n24q02m/mnemo-mcp/commit/ce2b5a530fbd465e044ed2636c7f3d47c055e29b))

### Code Style

- Run ruff format to fix CI failure ([#202](https://github.com/n24q02m/mnemo-mcp/pull/202),
  [`e34c2f8`](https://github.com/n24q02m/mnemo-mcp/commit/e34c2f861e14e43725782e6587e0101b7ea79a7d))

### Documentation

- Add v1.8-v1.9 design spec
  ([`b19ed64`](https://github.com/n24q02m/mnemo-mcp/commit/b19ed64e7e9c0f8becf11bec9b692378c65fb1f6))

### Features

- Add better-telegram-mcp to Also by section and mcp-name
  ([`5aa65f0`](https://github.com/n24q02m/mnemo-mcp/commit/5aa65f0131f29c7df7ed81561df4083944ae31ff))

- Add Glama.ai badge to README
  ([`fb9981f`](https://github.com/n24q02m/mnemo-mcp/commit/fb9981f58afe8b9abf39bc272b4fa3eb7495266e))

- Add Jina AI embedding priority and dual-backend reranker
  ([`02f02cb`](https://github.com/n24q02m/mnemo-mcp/commit/02f02cb0b53cb4c00bf5a5abc9526ef94f0252c2))

- Add knowledge graph, importance scoring, archive, and dedup
  ([`57c44fb`](https://github.com/n24q02m/mnemo-mcp/commit/57c44fbf5bc8e574f841f79bfd12b5f8800df80c))

- Offload blocking SQLite I/O to thread in sync_full
  ([#202](https://github.com/n24q02m/mnemo-mcp/pull/202),
  [`e34c2f8`](https://github.com/n24q02m/mnemo-mcp/commit/e34c2f861e14e43725782e6587e0101b7ea79a7d))

- Testing improvement] Add test for invalid JSON token in setup_sync
  ([#200](https://github.com/n24q02m/mnemo-mcp/pull/200),
  [`e683697`](https://github.com/n24q02m/mnemo-mcp/commit/e68369707266b0a66f783cb2ee328c9df2c75a26))

- Wire intelligence features into server (graph, importance, archive, consolidate)
  ([`351475c`](https://github.com/n24q02m/mnemo-mcp/commit/351475c9e782633506512c32b3b49a617edcdde5))


## v1.7.0 (2026-03-11)


## v1.7.0-beta.1 (2026-03-11)

### Bug Fixes

- Pin runtime versions with allowedVersions, revert Python to 3.13
  ([`85eb454`](https://github.com/n24q02m/mnemo-mcp/commit/85eb454ec00b16b50b9d269bfe1a472029c64669))

- Run initial sync immediately on startup instead of after interval delay
  ([`df47c57`](https://github.com/n24q02m/mnemo-mcp/commit/df47c579bb1e1eef703ef1990fcf40c9cb85e1f4))

### Chores

- Fix ruff formatting
  ([`bd1571c`](https://github.com/n24q02m/mnemo-mcp/commit/bd1571cbae5e516972c82744e1833f38c4461ebf))

### Documentation

- Update README for auto-token management
  ([`5cdcfb8`](https://github.com/n24q02m/mnemo-mcp/commit/5cdcfb870ceed0acdfcc80b2e3c5c9ecd20f9673))

### Features

- Auto-token management, security hardening, coverage improvements
  ([`06aca9a`](https://github.com/n24q02m/mnemo-mcp/commit/06aca9a9435daf71acae9a0125e918bcf2b6e175))

- Fully automatic sync - no setup-sync or RCLONE_CONFIG vars needed
  ([`10e00ae`](https://github.com/n24q02m/mnemo-mcp/commit/10e00ae213936611ec5ccf8f09f3fb34a5ae1c0a))


## v1.6.0 (2026-03-10)

### Bug Fixes

- Add .jules/ and JULES.md to gitignore
  ([`0ee239a`](https://github.com/n24q02m/mnemo-mcp/commit/0ee239a2375cbf8d8a7285a76b6909bcf09aed8d))

- Align repo with skill audit findings
  ([`37ff520`](https://github.com/n24q02m/mnemo-mcp/commit/37ff520811dcf7a1fa641e4c7b4e59101fc2fe32))

- Correct Qodo PR Agent ignore_pr_authors config
  ([`284e6a2`](https://github.com/n24q02m/mnemo-mcp/commit/284e6a292034c5a0d7cf721dbf022e5efebf5fb2))

- Fix potential DoS via malformed JSON in tags
  ([#160](https://github.com/n24q02m/mnemo-mcp/pull/160),
  [`54f52a5`](https://github.com/n24q02m/mnemo-mcp/commit/54f52a50105e34501cee495614b074234b1160fb))

- Remove commit-message-check job
  ([`3b909d1`](https://github.com/n24q02m/mnemo-mcp/commit/3b909d1ee29d95cb6bd209dc568fda9ba30dc806))

- Remove unused type-ignore comments flagged by ty
  ([`f7aa31d`](https://github.com/n24q02m/mnemo-mcp/commit/f7aa31d85b97189ca93291f5d32af91e94ad662d))

- Standardize CI with PR title check, email notify, and templates
  ([`302f2d0`](https://github.com/n24q02m/mnemo-mcp/commit/302f2d0912a3fa8364735b39a8a052df8677ebc9))

- Sync CI/CD configs and standardize templates
  ([`f1a4d5b`](https://github.com/n24q02m/mnemo-mcp/commit/f1a4d5bedb3d94f50b33f3cae2c77e8148cc6de7))

- 🛡️ Sentinel: [HIGH] Fix potential DoS via malformed JSON in tags
  ([#160](https://github.com/n24q02m/mnemo-mcp/pull/160),
  [`54f52a5`](https://github.com/n24q02m/mnemo-mcp/commit/54f52a50105e34501cee495614b074234b1160fb))

- **ci**: Fix Qodo PR review for external contributors
  ([`1793d7a`](https://github.com/n24q02m/mnemo-mcp/commit/1793d7a4793b03545b97fda5ebaaaf4484f6a8c3))

- **ci**: Pin PSR v10, Python 3.13, Node 24, Java 21 in Renovate
  ([`1731103`](https://github.com/n24q02m/mnemo-mcp/commit/17311032937d2f4f9f6f339fbfb6f1140a3a0fd7))

- **security**: Prevent DoS via malformed JSON in tags
  ([#160](https://github.com/n24q02m/mnemo-mcp/pull/160),
  [`54f52a5`](https://github.com/n24q02m/mnemo-mcp/commit/54f52a50105e34501cee495614b074234b1160fb))

- **security**: 🛡️ Sentinel: [HIGH] Fix potential DoS via malformed JSON in tags
  ([#160](https://github.com/n24q02m/mnemo-mcp/pull/160),
  [`54f52a5`](https://github.com/n24q02m/mnemo-mcp/commit/54f52a50105e34501cee495614b074234b1160fb))

### Chores

- **deps**: Lock file maintenance ([#155](https://github.com/n24q02m/mnemo-mcp/pull/155),
  [`2af9c8c`](https://github.com/n24q02m/mnemo-mcp/commit/2af9c8cfb70db1b89e9a9d16976b46fb6222c452))

- **deps**: Pin dependencies ([#158](https://github.com/n24q02m/mnemo-mcp/pull/158),
  [`64db470`](https://github.com/n24q02m/mnemo-mcp/commit/64db470f332de77ea59f1830e510b7cc44a6c144))

- **deps**: Update actions/dependency-review-action digest to 3c4e3dc
  ([#162](https://github.com/n24q02m/mnemo-mcp/pull/162),
  [`2040dc3`](https://github.com/n24q02m/mnemo-mcp/commit/2040dc3c47e508c2b7bb7a48562ed647e1de4192))

- **deps**: Update dawidd6/action-send-mail action to v11
  ([#163](https://github.com/n24q02m/mnemo-mcp/pull/163),
  [`cd98132`](https://github.com/n24q02m/mnemo-mcp/commit/cd98132bb4ff22a4ba95c1811705d9c51e1d95f9))

- **deps**: Update rclone/rclone docker tag to v1.73.2
  ([#151](https://github.com/n24q02m/mnemo-mcp/pull/151),
  [`9e01d3e`](https://github.com/n24q02m/mnemo-mcp/commit/9e01d3e70f13c78064be41e9ddae8e608bf07cfc))

### Continuous Integration

- Improve PR checks and Qodo filtering ([#159](https://github.com/n24q02m/mnemo-mcp/pull/159),
  [`c11fe16`](https://github.com/n24q02m/mnemo-mcp/commit/c11fe16e96031380e95045185ca05015672b392b))

### Features

- Add coverage tests to reach 99% statement coverage
  ([`8d08e97`](https://github.com/n24q02m/mnemo-mcp/commit/8d08e978611339aba8076b25584fa6d65b0ebf0d))

- Optimize _is_retryable list allocation ([#164](https://github.com/n24q02m/mnemo-mcp/pull/164),
  [`9274b0b`](https://github.com/n24q02m/mnemo-mcp/commit/9274b0b4c7b6d3ee5fd4705e90698f666228fc4f))

- ⚡ Bolt: [performance improvement] Optimize `_is_retryable` list allocation
  ([#164](https://github.com/n24q02m/mnemo-mcp/pull/164),
  [`9274b0b`](https://github.com/n24q02m/mnemo-mcp/commit/9274b0b4c7b6d3ee5fd4705e90698f666228fc4f))

- **perf**: ⚡ Bolt: optimize `_is_retryable` list allocation
  ([#164](https://github.com/n24q02m/mnemo-mcp/pull/164),
  [`9274b0b`](https://github.com/n24q02m/mnemo-mcp/commit/9274b0b4c7b6d3ee5fd4705e90698f666228fc4f))

### Performance Improvements

- ⚡ Bolt: optimize `_is_retryable` list allocation
  ([#164](https://github.com/n24q02m/mnemo-mcp/pull/164),
  [`9274b0b`](https://github.com/n24q02m/mnemo-mcp/commit/9274b0b4c7b6d3ee5fd4705e90698f666228fc4f))


## v1.5.9 (2026-03-06)

### Bug Fixes

- Add Docker LABEL and re-add OCI package for MCP Registry
  ([`63ed8e6`](https://github.com/n24q02m/mnemo-mcp/commit/63ed8e628f4bf9d458e0d8e2a958f3d0c3ac2a3b))


## v1.5.8 (2026-03-06)

### Bug Fixes

- Remove OCI package from server.json until Docker LABEL annotation added
  ([`22a8eb3`](https://github.com/n24q02m/mnemo-mcp/commit/22a8eb38689d165989c2f4bbb4513925edf5b731))


## v1.5.7 (2026-03-06)

### Bug Fixes

- Keep OCI identifier as latest in MCP Registry publish
  ([`bdd4594`](https://github.com/n24q02m/mnemo-mcp/commit/bdd45940230de0c82c7e1317552db1da5710836c))

### Continuous Integration

- Skip Qodo AI review for bot-created PRs
  ([`350cc52`](https://github.com/n24q02m/mnemo-mcp/commit/350cc520cb229543993b0e0cea1478f91afbf6ff))


## v1.5.6 (2026-03-06)

### Bug Fixes

- Handle OCI package version in MCP Registry publish
  ([`5e76911`](https://github.com/n24q02m/mnemo-mcp/commit/5e769112d1e3012287503fa2f7e5ef68b96118fe))


## v1.5.5 (2026-03-06)

### Bug Fixes

- Update server.json version dynamically in MCP Registry publish job
  ([`08d6e57`](https://github.com/n24q02m/mnemo-mcp/commit/08d6e57cf71f230c3957455e80846808a542636e))


## v1.5.4 (2026-03-06)

### Bug Fixes

- Add mcp-name to README for MCP Registry ownership validation
  ([`5c58289`](https://github.com/n24q02m/mnemo-mcp/commit/5c58289e92e0b68df9e9a76e88054112bc0e7eea))


## v1.5.3 (2026-03-06)

### Bug Fixes

- Shorten server.json description to comply with MCP Registry 100-char limit
  ([`535612d`](https://github.com/n24q02m/mnemo-mcp/commit/535612d8b7999aad4059167fd5ea4227d2500ad1))

### Documentation

- Add compatible-with badges and cross-links to sibling MCP servers
  ([`c373ca2`](https://github.com/n24q02m/mnemo-mcp/commit/c373ca2bc3271d982ebfaeddc6f089c110431d54))

- Add MCP client keywords to pyproject.toml for PyPI discoverability
  ([`2ddeef3`](https://github.com/n24q02m/mnemo-mcp/commit/2ddeef30265398c2cca58ebb1fe93553b387ec49))

- Add server.json and MCP Registry publish step to CD workflow
  ([`ed4983d`](https://github.com/n24q02m/mnemo-mcp/commit/ed4983da554217eb86303468f76f5af1d4947b10))

- Update compatible-with badges - add Antigravity, Gemini CLI, Codex, OpenCode
  ([`97c8b29`](https://github.com/n24q02m/mnemo-mcp/commit/97c8b2994ae8e2f6430dc5149e743c8c921165fa))


## v1.5.2 (2026-03-06)

### Bug Fixes

- Revert Python requirement from 3.14 to 3.13
  ([`1578748`](https://github.com/n24q02m/mnemo-mcp/commit/1578748cda5196adaffd61eef7344c5aeee105a2))


## v1.5.1 (2026-03-06)

### Bug Fixes

- Remove auto-generated .jules/bolt.md
  ([`b573af2`](https://github.com/n24q02m/mnemo-mcp/commit/b573af2f1e6a2b54aff5aeb8386f788c4edd655d))

### Chores

- **deps**: Lock file maintenance ([#148](https://github.com/n24q02m/mnemo-mcp/pull/148),
  [`33b870b`](https://github.com/n24q02m/mnemo-mcp/commit/33b870b8b9df0afb79bd4969341e889ee91b8923))

- **deps**: Lock file maintenance ([#141](https://github.com/n24q02m/mnemo-mcp/pull/141),
  [`d3c5fa6`](https://github.com/n24q02m/mnemo-mcp/commit/d3c5fa6d3ea08ffea6f77d5cb8def76a1e20245c))

- **deps**: Pin dependencies ([#129](https://github.com/n24q02m/mnemo-mcp/pull/129),
  [`596587b`](https://github.com/n24q02m/mnemo-mcp/commit/596587b030b01153fc8c90969011fc7cf2ac42af))

- **deps**: Update docker/login-action to v4
  ([`88b287a`](https://github.com/n24q02m/mnemo-mcp/commit/88b287aaefba9829cc2ac771f82ef28673ae0932))

- **deps**: Update docker/setup-buildx-action action to v4
  ([#147](https://github.com/n24q02m/mnemo-mcp/pull/147),
  [`e8f30e6`](https://github.com/n24q02m/mnemo-mcp/commit/e8f30e6160d5733e76415156517bdf9969ed03de))

- **deps**: Update non-major dependencies ([#143](https://github.com/n24q02m/mnemo-mcp/pull/143),
  [`0880296`](https://github.com/n24q02m/mnemo-mcp/commit/08802962445e1752233d3ddd8b2d6175e965d73b))

### Code Style

- Fix import ordering in live test script
  ([`5908e48`](https://github.com/n24q02m/mnemo-mcp/commit/5908e4873e1c456e8825cfc9833639f14df3c97e))

### Continuous Integration

- Trigger CI run
  ([`ac2da9a`](https://github.com/n24q02m/mnemo-mcp/commit/ac2da9a1b64f9836a81290efc8eea52d3225cdaa))

### Performance Improvements

- **db**: Optimize export_jsonl with SQLite json_object()
  ([#149](https://github.com/n24q02m/mnemo-mcp/pull/149),
  [`b5ecd12`](https://github.com/n24q02m/mnemo-mcp/commit/b5ecd12491472b0ac16a9d70eafdcdb04e59b73a))

### Testing

- Add Phase 5 live MCP protocol test
  ([`bb6beb6`](https://github.com/n24q02m/mnemo-mcp/commit/bb6beb6bafb768633490da65baec0ca1d6790f9e))


## v1.5.0 (2026-03-05)

### Bug Fixes

- Correct cross-refs and use MCP JSON config format in docs
  ([`ec4dfe0`](https://github.com/n24q02m/mnemo-mcp/commit/ec4dfe0741d9f6a051a57f7bed1023dec2930b2e))

- Update Codecov badge in README.md
  ([`6b7484c`](https://github.com/n24q02m/mnemo-mcp/commit/6b7484cf4ade011a3e3b0918e377cac59e3b9e8e))

- **test**: Prevent rclone checksum test from being skipped by local binary
  ([`4582980`](https://github.com/n24q02m/mnemo-mcp/commit/4582980fd420bace88a71ff21632cee9eb2dec0c))

### Documentation

- Add related projects cross-references
  ([`1e99f97`](https://github.com/n24q02m/mnemo-mcp/commit/1e99f97b0b8433c73f7eb9a7eea337cfe506b74f))

- Document 3-mode embedding architecture (proxy/sdk/local)
  ([`e16cfae`](https://github.com/n24q02m/mnemo-mcp/commit/e16cfae43cba974cecc0afea38066a67b139bbe7))

- Move 3-mode env vars into Quick Start config blocks
  ([`bd4b24d`](https://github.com/n24q02m/mnemo-mcp/commit/bd4b24d0e6c41427637d3fedf8978c9e835f09f7))

### Features

- Implement 3-mode LLM architecture (proxy/sdk/local)
  ([`75bae16`](https://github.com/n24q02m/mnemo-mcp/commit/75bae169d00d93930acc9b14da481dd6a13dc0d4))


## v1.4.3 (2026-03-02)

### Bug Fixes

- Delete .jules directory
  ([`a68e6b6`](https://github.com/n24q02m/mnemo-mcp/commit/a68e6b660bbad1410a6d85bf0f46ddf59308f6ac))

- Lock python version to 3.13
  ([`f373b97`](https://github.com/n24q02m/mnemo-mcp/commit/f373b97a7adef913ba2ff7c3fe176ba34cc6a4f3))


## v1.4.2 (2026-03-01)

### Bug Fixes

- Allow uv to download python 3.14 during docker build
  ([`fa8fb17`](https://github.com/n24q02m/mnemo-mcp/commit/fa8fb17f9d6d4e61ced04142601602a54ab390dd))


## v1.4.1 (2026-03-01)

### Bug Fixes

- Remove --frozen from uv sync to allow lockfile updates during docker build
  ([`1731681`](https://github.com/n24q02m/mnemo-mcp/commit/17316819d0abdaa56676cab2af8a2e33ee62ba33))


## v1.4.0 (2026-03-01)

### Bug Fixes

- Integrate PRs #96, #92, #86, #80 (uuid randomness, dos protection, config security)
  ([`4cd8aca`](https://github.com/n24q02m/mnemo-mcp/commit/4cd8aca5bee79f4a4fc5662b82712d195e1a51a3))

- Multiple security and stability fixes (#120, #124, #125, #126)
  ([`5b8a4e0`](https://github.com/n24q02m/mnemo-mcp/commit/5b8a4e0d78394b17dea46b069479653da929013c))

- Update dependencies to address vulnerabilities
  ([`8b0c819`](https://github.com/n24q02m/mnemo-mcp/commit/8b0c8194e426c53f2e6b0b6c31a765a49464ac59))

- **db**: Optimize tag filtering with sql json_each
  ([`3ca620c`](https://github.com/n24q02m/mnemo-mcp/commit/3ca620c4c3a5e0dd2383966ace8eb142d6a1ba35))

- **deps**: Update non-major dependencies ([#130](https://github.com/n24q02m/mnemo-mcp/pull/130),
  [`2021e8f`](https://github.com/n24q02m/mnemo-mcp/commit/2021e8fa7c7fa8328d3ea82c86e5d35b7d5924fc))

### Chores

- Remove accidental .orig and .rej files
  ([`4b013eb`](https://github.com/n24q02m/mnemo-mcp/commit/4b013ebfd28f8293aa01da288791a10a498e3da8))

- **deps**: Update actions/checkout action to v6
  ([#134](https://github.com/n24q02m/mnemo-mcp/pull/134),
  [`36f1bd5`](https://github.com/n24q02m/mnemo-mcp/commit/36f1bd538eb934292ef05fc2abcb1876e04e563a))

- **deps**: Update astral-sh/setup-uv action to v7
  ([#131](https://github.com/n24q02m/mnemo-mcp/pull/131),
  [`795a29d`](https://github.com/n24q02m/mnemo-mcp/commit/795a29d5093a14d0f40e12c984a9754d04f6437e))

- **deps**: Update github artifact actions ([#135](https://github.com/n24q02m/mnemo-mcp/pull/135),
  [`41765de`](https://github.com/n24q02m/mnemo-mcp/commit/41765de616808345b3dc5628607bfc73e55f5a30))

- **deps**: Update rclone/rclone docker tag to v1.73.1
  ([#140](https://github.com/n24q02m/mnemo-mcp/pull/140),
  [`f629bf4`](https://github.com/n24q02m/mnemo-mcp/commit/f629bf46f01d4c09f675b845d7ae2333fdbdff02))

### Features

- **security**: Enforce SHA256 checksum verification for rclone downloads
  ([#133](https://github.com/n24q02m/mnemo-mcp/pull/133),
  [`d52039f`](https://github.com/n24q02m/mnemo-mcp/commit/d52039f90fdcd8d5ed839a0348c2a14d4be6dba0))

### Performance Improvements

- Optimize export_jsonl to use memory-efficient tuple stream
  ([#127](https://github.com/n24q02m/mnemo-mcp/pull/127),
  [`8e1b050`](https://github.com/n24q02m/mnemo-mcp/commit/8e1b050b1f4f385560fcd6e4cfc1072591e38e3c))

- **db**: Optimize `import_jsonl` with batched queries and bulk inserts
  ([#136](https://github.com/n24q02m/mnemo-mcp/pull/136),
  [`d946de8`](https://github.com/n24q02m/mnemo-mcp/commit/d946de87df6e1ef7082735a7dc88e5e7a379fabc))


## v1.3.0 (2026-02-28)

### Bug Fixes

- Standardize repo structure with enforce-commit hook
  ([`7c53d9d`](https://github.com/n24q02m/mnemo-mcp/commit/7c53d9df82e3e1cf562eef839fca7f773a12c7ed))

- Update README badges with Codecov, tech stack, and engineering standards
  ([`91e1adb`](https://github.com/n24q02m/mnemo-mcp/commit/91e1adb6ad0655abb0d877d6b11fae6166bc7f28))

- **ci**: Fix Qodo Merge env variable dot notation bug
  ([`b2bdfd3`](https://github.com/n24q02m/mnemo-mcp/commit/b2bdfd399c2182c4cbc0c58e27a834bbb72e1911))

- **ci**: Fix Qodo model to gemini-3-flash-preview
  ([`1405679`](https://github.com/n24q02m/mnemo-mcp/commit/14056790c41674d688d3884b16a0a8b34cb97c13))

- **ci**: Fix syntax errors and correctly configure Qodo + Gemini 3 Flash
  ([`e11aae0`](https://github.com/n24q02m/mnemo-mcp/commit/e11aae055c205c1596c5083e2540d97ba6f9cdb1))

- **ci**: Move pr-agent config to .pr_agent.toml
  ([`35ba50c`](https://github.com/n24q02m/mnemo-mcp/commit/35ba50cbf52c13f4835284e776f90d9fbddc9db2))

- **ci**: Remove invalid strict field from ty config
  ([`7148a86`](https://github.com/n24q02m/mnemo-mcp/commit/7148a86b605916e209b91702030247d06dc0bc57))

- **ci**: Update to supported Gemini 3 and 2.5 flash models
  ([`d9cbf84`](https://github.com/n24q02m/mnemo-mcp/commit/d9cbf84d3070ad008ba09a113d360281ecd8e2c6))

### Chores

- Add Gemini Code Assist style guide
  ([`bdccbd0`](https://github.com/n24q02m/mnemo-mcp/commit/bdccbd03055c23b9d9592c4171242d6ef2179636))

- Change Renovate schedule to daily 5am
  ([`8b180c7`](https://github.com/n24q02m/mnemo-mcp/commit/8b180c729ea292a61f6c99a9218d316fbe443acb))

- Migrate to 2025-2026 tech stack (uv/ty)
  ([`52506d3`](https://github.com/n24q02m/mnemo-mcp/commit/52506d31e38cefdaa1e7ccac042426aeaf7ea361))

- Remove CodeRabbit config, migrating to Gemini Code Assist
  ([`4085195`](https://github.com/n24q02m/mnemo-mcp/commit/408519594a5406236420d22c5283e6dcfc8446e7))

- Remove dependabot.yml in favor of Renovate
  ([`dd610b8`](https://github.com/n24q02m/mnemo-mcp/commit/dd610b8180790f3a7851c119a848980e00045b65))

- **config**: Migrate config renovate.json
  ([`109710b`](https://github.com/n24q02m/mnemo-mcp/commit/109710be4e23f5f454fceacc3836ad61eb103017))

### Documentation

- Add Contributing section and standardize License format
  ([`59b299e`](https://github.com/n24q02m/mnemo-mcp/commit/59b299ebc358f37ba6804e478e394245e382b1ea))

### Features

- Add Codecov coverage upload and CodeRabbit config
  ([`7eedfe4`](https://github.com/n24q02m/mnemo-mcp/commit/7eedfe4a16d80aca7f629875ff6e6a8d32b651ad))

- **ci**: Add Renovate config for automated dependency updates
  ([`3d3bdc2`](https://github.com/n24q02m/mnemo-mcp/commit/3d3bdc2599367054fe0457e7a38f12c3ddf56271))

- **ci**: Add StepSecurity Harden-Runner to all workflow jobs (audit mode)
  ([`7de2156`](https://github.com/n24q02m/mnemo-mcp/commit/7de2156e3032eaac7b0548c76248597d9b133417))

- **ci**: Migrate to Qodo Merge AI Review (Gemini 3 Flash)
  ([`2333c75`](https://github.com/n24q02m/mnemo-mcp/commit/2333c75b401f3f6d8eb7d250d63c1803fd35e6c0))


## v1.2.0 (2026-02-25)

### Features

- Add memory protection against poisoning attacks
  ([`4ae9862`](https://github.com/n24q02m/mnemo-mcp/commit/4ae9862f7701f5c3ab354b9597c32a61763c6597))


## v1.1.0 (2026-02-23)

### Bug Fixes

- Add CI status badge to README
  ([`fd3d768`](https://github.com/n24q02m/mnemo-mcp/commit/fd3d7688177d87df16e2c8705a37d44c06a7a508))

- Handle corrupted ONNX model cache in warmup (detect, clear, retry)
  ([`f2af9f7`](https://github.com/n24q02m/mnemo-mcp/commit/f2af9f7a850509a55f1df23ab40a8be3a467c03e))

### Features

- Add warmup subcommand and improve embedding startup
  ([`65c57bf`](https://github.com/n24q02m/mnemo-mcp/commit/65c57bfecdc61d7fee128b14e5f527a827906ced))


## v1.0.7 (2026-02-20)

### Bug Fixes

- Resolve MCP startup timeouts and stability issues
  ([`3d950bc`](https://github.com/n24q02m/mnemo-mcp/commit/3d950bca107c0262409d5e20545011a66b16a497))

### Chores

- **deps**: Bump actions/download-artifact from 4 to 7
  ([`0fd5e32`](https://github.com/n24q02m/mnemo-mcp/commit/0fd5e32f4b15f64fb80d6985ca24fe2decd08692))

- **deps**: Bump actions/upload-artifact from 4 to 6
  ([`8f9fbfe`](https://github.com/n24q02m/mnemo-mcp/commit/8f9fbfe5210f8f450d4c609eb4afc10d362808d6))

### Documentation

- Add AGENTS.md for AI coding agents
  ([`f8aeb16`](https://github.com/n24q02m/mnemo-mcp/commit/f8aeb161e43f104156bb7b5fb69a275ffac0d998))


## v1.0.6 (2026-02-19)

### Bug Fixes

- Correct docs defaults, update outdated config info, and fix destructiveHint
  ([`5d90d84`](https://github.com/n24q02m/mnemo-mcp/commit/5d90d84aa6232217b83c0d6bd9f88489ac63d584))

### Documentation

- Simplify quick start to uvx and docker options with full config
  ([`359d81f`](https://github.com/n24q02m/mnemo-mcp/commit/359d81f1d7674ac086eb4e5d465dae2959f6fa4c))


## v1.0.5 (2026-02-18)

### Bug Fixes

- Correct model identifiers to n24q02m/ namespace and bump qwen3-embed to v1.1.3
  ([`7e6e7d8`](https://github.com/n24q02m/mnemo-mcp/commit/7e6e7d8edd358bd0eb6b00edc75cf66ed3e26694))

### Documentation

- Restructure Quick Start with 4 config options
  ([`dd3ea1b`](https://github.com/n24q02m/mnemo-mcp/commit/dd3ea1b8d5d4ae09415cd01b8dde6285f8d615d0))

### Refactoring

- Make qwen3-embed core dep, cloud-first embedding
  ([`e4be7e8`](https://github.com/n24q02m/mnemo-mcp/commit/e4be7e8d34ceb7fa805952a2de661258543f99d1))


## v1.0.4 (2026-02-18)

### Bug Fixes

- Accept list/dict data in memory.import and add --name to Docker docs
  ([`a66ad0d`](https://github.com/n24q02m/mnemo-mcp/commit/a66ad0d0b9e9887b4cfa9616743ee680f162884c))

- Pass embedding_model to local backend, add gguf support, docker-compose
  ([`bcf06f2`](https://github.com/n24q02m/mnemo-mcp/commit/bcf06f248b7b6152500ef00acfa9cc10fd2006f1))

- Update qwen3-embed version pin and improve docs
  ([`8e48bf8`](https://github.com/n24q02m/mnemo-mcp/commit/8e48bf8552874bcb6c4900edf641be2d7d9c051d))

### Documentation

- Add resources, prompts sections and clarify import format
  ([`1c636c6`](https://github.com/n24q02m/mnemo-mcp/commit/1c636c6a69b078167eef8160965a691b11a84924))

- Fix EMBEDDING_DIMS default in README
  ([`ddda08e`](https://github.com/n24q02m/mnemo-mcp/commit/ddda08e3b7530eb543341d897c11384268ebe785))


## v1.0.3 (2026-02-17)

### Bug Fixes

- Correct MRL truncation and add query instruction prefix
  ([`aad080e`](https://github.com/n24q02m/mnemo-mcp/commit/aad080e300a851769d19a1df81d140b9dd4792d7))


## v1.0.2 (2026-02-17)


## v1.0.2-beta.1 (2026-02-17)

### Chores

- Standardize mise.toml, update release docs to PSR
  ([`cee1e09`](https://github.com/n24q02m/mnemo-mcp/commit/cee1e0993181f7189a564523498117b2319b7d16))

### Performance Improvements

- **server**: Wrap sync db operations in asyncio.to_thread
  ([`69009e5`](https://github.com/n24q02m/mnemo-mcp/commit/69009e582aff262ee3de94ca2ddeb3831a8df1db))


## v1.0.1 (2026-02-14)

### Bug Fixes

- **cd**: Add config_file for PSR + checkout for DockerHub description
  ([`b2a7bb5`](https://github.com/n24q02m/mnemo-mcp/commit/b2a7bb5a509e5784054cc261da58f5746a9f30a4))


## v1.0.0 (2026-02-14)

### Bug Fixes

- **cd**: Remove build_command from PSR config (not available in PSR container)
  ([`48b689e`](https://github.com/n24q02m/mnemo-mcp/commit/48b689ef28a6466d6605a9ccdccb1f7e7676fb76))

### Chores

- Migrate from release-please to python-semantic-release v10
  ([`fc67678`](https://github.com/n24q02m/mnemo-mcp/commit/fc67678908abd42ac4a05072c7cbeb32a94178e3))


## v0.1.5-beta.1 (2026-02-14)

### Bug Fixes

- Optimize Docker build with BuildKit cache and non-root user
  ([`e449e2d`](https://github.com/n24q02m/mnemo-mcp/commit/e449e2da5cb8ffbad4b7d2d0363d5b21ce274345))

- **cd**: Make scripts executable and clean working tree before promote merge
  ([`4135c2e`](https://github.com/n24q02m/mnemo-mcp/commit/4135c2e780d2a9fde73d38a24fae6cbfdc90cf70))

### Chores

- Sync beta manifest from stable [skip ci]
  ([`457f6d4`](https://github.com/n24q02m/mnemo-mcp/commit/457f6d42b6618b2925eaf50c5820200481bf7d48))

- **dev**: Release 0.1.5-beta ([#59](https://github.com/n24q02m/mnemo-mcp/pull/59),
  [`c6cdd7c`](https://github.com/n24q02m/mnemo-mcp/commit/c6cdd7c1c9ecb94e0158f01dfa46fdf47395daeb))

- **dev**: Release 0.1.5-beta.1 ([#60](https://github.com/n24q02m/mnemo-mcp/pull/60),
  [`8357440`](https://github.com/n24q02m/mnemo-mcp/commit/8357440b85865e389688bf5b27288da60e1c49be))

### Code Style

- Fix ruff format in server.py
  ([`6b7a905`](https://github.com/n24q02m/mnemo-mcp/commit/6b7a905d0a384a65d8502879cdaa8d64564a58f7))

### Features

- Refactor embedding tests and add dual-backend support
  ([`67e99a2`](https://github.com/n24q02m/mnemo-mcp/commit/67e99a2a6b2af2f7772977b6e21aa2761b17df31))


## v0.1.4 (2026-02-14)

### Chores

- Sync beta manifest from stable [skip ci]
  ([`7b95565`](https://github.com/n24q02m/mnemo-mcp/commit/7b95565a72c96d9a4b50ecbf6e6f0608dfef4e02))

- **dev**: Release 0.1.4-beta ([#56](https://github.com/n24q02m/mnemo-mcp/pull/56),
  [`6dad934`](https://github.com/n24q02m/mnemo-mcp/commit/6dad934156eddbef750a1621c77c732977f35c12))

- **main**: Release 0.1.4 ([#57](https://github.com/n24q02m/mnemo-mcp/pull/57),
  [`f0c9e0b`](https://github.com/n24q02m/mnemo-mcp/commit/f0c9e0b67381b38d3fa7b4abb82d98ee33a040d1))

### Features

- Add batch splitting and retry with exponential backoff to embedder
  ([#56](https://github.com/n24q02m/mnemo-mcp/pull/56),
  [`6dad934`](https://github.com/n24q02m/mnemo-mcp/commit/6dad934156eddbef750a1621c77c732977f35c12))

- Promote dev to main (v0.1.4-beta) ([#56](https://github.com/n24q02m/mnemo-mcp/pull/56),
  [`6dad934`](https://github.com/n24q02m/mnemo-mcp/commit/6dad934156eddbef750a1621c77c732977f35c12))


## v0.1.3 (2026-02-13)

### Bug Fixes

- Resolve ruff f-string format issues in db.py
  ([`ee05d15`](https://github.com/n24q02m/mnemo-mcp/commit/ee05d1538efb6136e43964a5c477be0b3af230fc))

### Chores

- **main**: Release 0.1.3
  ([`f742da9`](https://github.com/n24q02m/mnemo-mcp/commit/f742da9e3273584a71df76ef37fdaae925539b2d))


## v0.1.3-beta.1 (2026-02-13)

### Bug Fixes

- Correct changelog descriptions for FTS5 search overhaul
  ([`783d8a9`](https://github.com/n24q02m/mnemo-mcp/commit/783d8a9f2370997cb205c474e122d0b23ed4f907))

### Chores

- Sync beta manifest from stable [skip ci]
  ([`e12d3bd`](https://github.com/n24q02m/mnemo-mcp/commit/e12d3bdfcc396fbdf1cdf74398f22262a7bf2b15))

- **dev**: Release 0.1.3-beta ([#50](https://github.com/n24q02m/mnemo-mcp/pull/50),
  [`b229c7d`](https://github.com/n24q02m/mnemo-mcp/commit/b229c7dabd6dbc297c7283b415a949b56e5a1a1a))

- **dev**: Release 0.1.3-beta.1 ([#51](https://github.com/n24q02m/mnemo-mcp/pull/51),
  [`1524b09`](https://github.com/n24q02m/mnemo-mcp/commit/1524b09f00cd0595234ad94eb6a43a40a668bb11))

### Documentation

- Add optional/required annotations to sync config examples
  ([`52cf348`](https://github.com/n24q02m/mnemo-mcp/commit/52cf348af49894f63f9d0fc7cc9745598164df5d))

### Features

- Implement tiered FTS5 queries and add common stop words for improved search functionality
  ([`202dce4`](https://github.com/n24q02m/mnemo-mcp/commit/202dce47ee9e038c30b3a0017c058b836b847986))

### Refactoring

- Remove common stop words filtering from FTS queries for improved recall
  ([`d829f66`](https://github.com/n24q02m/mnemo-mcp/commit/d829f66726e87eb61e2afd633560318c1d6c9b8a))


## v0.1.2 (2026-02-13)

### Chores

- Add automated cleanup for stale release-please PRs
  ([`6c4a744`](https://github.com/n24q02m/mnemo-mcp/commit/6c4a744f83de257e55c022f677bab1aba1c0a7eb))

- Sync beta manifest from stable [skip ci]
  ([`6b7a33a`](https://github.com/n24q02m/mnemo-mcp/commit/6b7a33ac0c3d152befb62c2c6285829256b9c27c))

- **main**: Release 0.1.2 ([#21](https://github.com/n24q02m/mnemo-mcp/pull/21),
  [`e536acc`](https://github.com/n24q02m/mnemo-mcp/commit/e536acc9d46d96756ddd39dc3842db83b3e5217e))

### Documentation

- Add CODEOWNERS and README badges
  ([`ea971d4`](https://github.com/n24q02m/mnemo-mcp/commit/ea971d47a90896149c39444bd0af8461bc761953))


## v0.1.1 (2026-02-12)

### Bug Fixes

- Use dynamic version from package metadata instead of hardcoded string
  ([`245efc5`](https://github.com/n24q02m/mnemo-mcp/commit/245efc51c49adc3ac7c5465bdf2de341a2a95f0f))

### Chores

- Sync beta manifest from stable [skip ci]
  ([`7b396be`](https://github.com/n24q02m/mnemo-mcp/commit/7b396beb4571bf10f5f9e51b3b5865b6a7441b09))

- **main**: Release 0.1.1
  ([`ddbcdf8`](https://github.com/n24q02m/mnemo-mcp/commit/ddbcdf895c266c8605c66859ba3880c273973793))


## v0.1.0 (2026-02-12)

### Bug Fixes

- **cd**: Auto-resolve merge conflicts in promote workflow
  ([`05a5d4f`](https://github.com/n24q02m/mnemo-mcp/commit/05a5d4f764d9aea7456cf19db6c3d67645170977))

### Chores

- **main**: Release 0.1.0
  ([`4593f62`](https://github.com/n24q02m/mnemo-mcp/commit/4593f62571151cbf9cded892cc879b0e1a17c481))


## v0.1.0-beta.9 (2026-02-12)

### Chores

- **dev**: Release 0.1.0-beta.9 ([#12](https://github.com/n24q02m/mnemo-mcp/pull/12),
  [`66c0886`](https://github.com/n24q02m/mnemo-mcp/commit/66c08867bdac7fae051377da4da3c719f6bfc8e2))

### Features

- **sync**: Add SYNC_INTERVAL setting and simplify sync folder handling
  ([`fe3e281`](https://github.com/n24q02m/mnemo-mcp/commit/fe3e2813a48bcc10ac5895d2663fedc24d0b90dd))


## v0.1.0-beta.8 (2026-02-12)

### Chores

- **dev**: Release 0.1.0-beta.8 ([#11](https://github.com/n24q02m/mnemo-mcp/pull/11),
  [`33fcd0c`](https://github.com/n24q02m/mnemo-mcp/commit/33fcd0c297dab0fb441a93143ccd951a54e7d6c4))

### Features

- **sync**: Enhance setup_sync to support base64-encoded tokens and improve sync folder handling
  ([`7f3c92e`](https://github.com/n24q02m/mnemo-mcp/commit/7f3c92e27721401cfd19875a9b6a4a4bee7f8102))


## v0.1.0-beta.7 (2026-02-12)

### Chores

- **dev**: Release 0.1.0-beta.7 ([#10](https://github.com/n24q02m/mnemo-mcp/pull/10),
  [`328f6cb`](https://github.com/n24q02m/mnemo-mcp/commit/328f6cba66a6644ca7bd8164134699db076fa640))

### Features

- **sync**: Enhance setup_sync to auto-extract rclone token and output MCP config
  ([`0eec357`](https://github.com/n24q02m/mnemo-mcp/commit/0eec357400f73ea85f1b1caad269c63ba7fcaa5f))


## v0.1.0-beta.6 (2026-02-12)

### Chores

- **dev**: Release 0.1.0-beta.6 ([#9](https://github.com/n24q02m/mnemo-mcp/pull/9),
  [`ad52a1c`](https://github.com/n24q02m/mnemo-mcp/commit/ad52a1c4defcb47606431528e6fa022684cb3705))

### Features

- Implement sync setup command and update documentation; adjust embedding dimensions handling
  ([`f31eb8e`](https://github.com/n24q02m/mnemo-mcp/commit/f31eb8e71a6e104dee666f1bb520a1aeab19ab42))


## v0.1.0-beta.5 (2026-02-12)

### Bug Fixes

- **cd**: Add git config identity for sync-dev step
  ([`af060fe`](https://github.com/n24q02m/mnemo-mcp/commit/af060fe775bcdcf8c4e3a6a296bd0602f5dcbf85))

### Chores

- **dev**: Release 0.1.0-beta.5 ([#7](https://github.com/n24q02m/mnemo-mcp/pull/7),
  [`ae5bf36`](https://github.com/n24q02m/mnemo-mcp/commit/ae5bf361b9adfab4f8ef85a7f8f8baa2b85eb88d))


## v0.1.0-beta.4 (2026-02-12)

### Chores

- **dev**: Release 0.1.0-beta.4 ([#6](https://github.com/n24q02m/mnemo-mcp/pull/6),
  [`07ca80a`](https://github.com/n24q02m/mnemo-mcp/commit/07ca80a7cdfd61872ac4c164ea0b5ff387a4c851))

### Features

- Enhance embedding model detection and API key handling; update documentation and tests
  ([`ce394f7`](https://github.com/n24q02m/mnemo-mcp/commit/ce394f72edf96a1a0ba5a7ba731ec6e6cd3f9be3))


## v0.1.0-beta.3 (2026-02-12)

### Bug Fixes

- **release**: Reset stable manifest to 0.0.0 (no stable release yet)
  ([`829edca`](https://github.com/n24q02m/mnemo-mcp/commit/829edcac2580bd73dee4cf5e649b428bf756acc4))

### Chores

- **dev**: Release 0.1.0-beta.3 ([#2](https://github.com/n24q02m/mnemo-mcp/pull/2),
  [`184edcd`](https://github.com/n24q02m/mnemo-mcp/commit/184edcd15bf260885647788d8644eb39854715a6))


## v0.1.0-beta.2 (2026-02-12)

- Initial Release
