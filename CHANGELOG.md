# Changelog

## [0.1.3-beta](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.2...v0.1.3-beta) (2026-02-13)


### Features

* overhaul FTS5 search engine with BM25 column weights, tiered AND-to-OR queries, min-max normalization, RRF fusion, chunk quality scoring, language-agnostic stop word handling via BM25 IDF, and category SQL pre-filtering ([202dce4](https://github.com/n24q02m/mnemo-mcp/commit/202dce47ee9e038c30b3a0017c058b836b847986))

## [0.1.2](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.1...v0.1.2) (2026-02-13)


### Documentation

* add CODEOWNERS and README badges ([ea971d4](https://github.com/n24q02m/mnemo-mcp/commit/ea971d47a90896149c39444bd0af8461bc761953))

## [0.1.1](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.0...v0.1.1) (2026-02-12)


### Bug Fixes

* use dynamic version from package metadata instead of hardcoded string ([245efc5](https://github.com/n24q02m/mnemo-mcp/commit/245efc51c49adc3ac7c5465bdf2de341a2a95f0f))

## 0.1.0 (2026-02-12)


### Features

* Add comprehensive tests for mnemo_mcp module components ([0f1d179](https://github.com/n24q02m/mnemo-mcp/commit/0f1d179456415ccfdf228b36aded6a89fc7809fb))
* Enhance embedding model detection and API key handling; update documentation and tests ([ce394f7](https://github.com/n24q02m/mnemo-mcp/commit/ce394f72edf96a1a0ba5a7ba731ec6e6cd3f9be3))
* Implement sync setup command and update documentation; adjust embedding dimensions handling ([f31eb8e](https://github.com/n24q02m/mnemo-mcp/commit/f31eb8e71a6e104dee666f1bb520a1aeab19ab42))
* promote dev to main ([aee7a4c](https://github.com/n24q02m/mnemo-mcp/commit/aee7a4c511d20170326dd0421ab5644c2872b258))
* promote dev to main (v0.1.0-beta.2) ([#3](https://github.com/n24q02m/mnemo-mcp/issues/3)) ([6039e3e](https://github.com/n24q02m/mnemo-mcp/commit/6039e3ebcc0f89de12acf75277a4754fd589ea80))
* promote dev to main (v0.1.0-beta.9) ([411ff4c](https://github.com/n24q02m/mnemo-mcp/commit/411ff4c96985ca8f58128bbb5b1888f85e026fe7))
* **sync:** add SYNC_INTERVAL setting and simplify sync folder handling ([fe3e281](https://github.com/n24q02m/mnemo-mcp/commit/fe3e2813a48bcc10ac5895d2663fedc24d0b90dd))
* **sync:** enhance setup_sync to auto-extract rclone token and output MCP config ([0eec357](https://github.com/n24q02m/mnemo-mcp/commit/0eec357400f73ea85f1b1caad269c63ba7fcaa5f))
* **sync:** enhance setup_sync to support base64-encoded tokens and improve sync folder handling ([7f3c92e](https://github.com/n24q02m/mnemo-mcp/commit/7f3c92e27721401cfd19875a9b6a4a4bee7f8102))


### Bug Fixes

* **cd:** add git config identity for sync-dev step ([a795851](https://github.com/n24q02m/mnemo-mcp/commit/a7958510fcb6de58621dd5d6bd93dd5b1a58ff55))
* **cd:** add git config identity for sync-dev step ([af060fe](https://github.com/n24q02m/mnemo-mcp/commit/af060fe775bcdcf8c4e3a6a296bd0602f5dcbf85))
* **cd:** auto-resolve merge conflicts in promote workflow ([05a5d4f](https://github.com/n24q02m/mnemo-mcp/commit/05a5d4f764d9aea7456cf19db6c3d67645170977))
* **release:** reset stable manifest to 0.0.0 (no stable release yet) ([829edca](https://github.com/n24q02m/mnemo-mcp/commit/829edcac2580bd73dee4cf5e649b428bf756acc4))

## [0.1.0-beta.9](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.0-beta.8...v0.1.0-beta.9) (2026-02-12)


### Features

* **sync:** add SYNC_INTERVAL setting and simplify sync folder handling ([fe3e281](https://github.com/n24q02m/mnemo-mcp/commit/fe3e2813a48bcc10ac5895d2663fedc24d0b90dd))

## [0.1.0-beta.8](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.0-beta.7...v0.1.0-beta.8) (2026-02-12)


### Features

* **sync:** enhance setup_sync to support base64-encoded tokens and improve sync folder handling ([7f3c92e](https://github.com/n24q02m/mnemo-mcp/commit/7f3c92e27721401cfd19875a9b6a4a4bee7f8102))

## [0.1.0-beta.7](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.0-beta.6...v0.1.0-beta.7) (2026-02-12)


### Features

* **sync:** enhance setup_sync to auto-extract rclone token and output MCP config ([0eec357](https://github.com/n24q02m/mnemo-mcp/commit/0eec357400f73ea85f1b1caad269c63ba7fcaa5f))

## [0.1.0-beta.6](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.0-beta.5...v0.1.0-beta.6) (2026-02-12)


### Features

* Implement sync setup command and update documentation; adjust embedding dimensions handling ([f31eb8e](https://github.com/n24q02m/mnemo-mcp/commit/f31eb8e71a6e104dee666f1bb520a1aeab19ab42))

## [0.1.0-beta.5](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.0-beta.4...v0.1.0-beta.5) (2026-02-12)


### Bug Fixes

* **cd:** add git config identity for sync-dev step ([af060fe](https://github.com/n24q02m/mnemo-mcp/commit/af060fe775bcdcf8c4e3a6a296bd0602f5dcbf85))

## [0.1.0-beta.4](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.0-beta.3...v0.1.0-beta.4) (2026-02-12)


### Features

* Enhance embedding model detection and API key handling; update documentation and tests ([ce394f7](https://github.com/n24q02m/mnemo-mcp/commit/ce394f72edf96a1a0ba5a7ba731ec6e6cd3f9be3))

## [0.1.0-beta.3](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.0-beta.2...v0.1.0-beta.3) (2026-02-12)


### Bug Fixes

* **release:** reset stable manifest to 0.0.0 (no stable release yet) ([829edca](https://github.com/n24q02m/mnemo-mcp/commit/829edcac2580bd73dee4cf5e649b428bf756acc4))

## [0.1.0-beta.2](https://github.com/n24q02m/mnemo-mcp/compare/v0.1.0-beta.1...v0.1.0-beta.2) (2026-02-12)


### Features

* Add comprehensive tests for mnemo_mcp module components ([0f1d179](https://github.com/n24q02m/mnemo-mcp/commit/0f1d179456415ccfdf228b36aded6a89fc7809fb))
