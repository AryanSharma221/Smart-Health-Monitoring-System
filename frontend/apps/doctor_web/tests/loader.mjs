import { existsSync, statSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (err) {
    if (err.code === 'ERR_MODULE_NOT_FOUND' && (specifier.startsWith('./') || specifier.startsWith('../'))) {
      const extensions = ['.ts', '.tsx', '.js', '/index.ts', '/index.js'];
      
      for (const ext of extensions) {
        const target = fileURLToPath(new URL(specifier + ext, context.parentURL));
        if (existsSync(target) && !statSync(target).isDirectory()) {
          return nextResolve(pathToFileURL(target).href, context);
        }
      }
    }
    throw err;
  }
}
