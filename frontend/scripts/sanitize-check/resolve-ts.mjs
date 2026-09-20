// Lets `node --experimental-strip-types` resolve "@/…" and extensionless relative imports
// (the same hook as scripts/record-copy). Used by `npm run check:sanitize`.
import { register } from "node:module";
register("./resolve-hooks.mjs", import.meta.url);
