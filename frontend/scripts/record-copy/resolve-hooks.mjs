import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
export async function resolve(specifier, context, next) {
  let spec = specifier;
  if (spec.startsWith("@/")) spec = pathToFileURL(path.join(ROOT, spec.slice(2))).href;
  const rel = spec.startsWith("./") || spec.startsWith("../") || spec.startsWith("file:");
  if (rel && !/\.[cm]?[jt]sx?$|\.json$/.test(spec)) {
    const base = context.parentURL ? new URL(spec, context.parentURL) : new URL(spec);
    for (const ext of [".ts", "/index.ts"]) {
      const u = new URL(base.href + ext);
      if (existsSync(fileURLToPath(u))) return next(u.href, context);
    }
  }
  return next(spec, context);
}
