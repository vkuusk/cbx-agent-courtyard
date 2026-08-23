# Vendored front-end library

`htm-preact-standalone.module.js` — one ES module bundling **Preact 10.29.8** (MIT) and
**htm 3.1.1** (Apache-2.0): `html`, `render`, `Component`, and the hooks. Copied verbatim
from `https://unpkg.com/htm@3.1.1/preact/standalone.module.js` (design D18).

No build step, no package manager: the hub serves this file like any other static asset and
`webui/js/*.js` import it directly. To update, download the same path for a newer htm
release and replace the file; nothing else changes.
