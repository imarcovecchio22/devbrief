import path from "node:path";
import { config } from "dotenv";
import { defineConfig } from "prisma/config";

// Un solo .env para todo el repo, en la raíz (lo comparte con el pipeline).
// En Vercel y en GitHub Actions las variables vienen del entorno.
config({ path: path.resolve(process.cwd(), "../.env"), quiet: true });

/**
 * Las migraciones usan conexión directa: el pooler de Neon (PgBouncer en modo
 * transacción) no se lleva bien con los locks que toma `prisma migrate`.
 * En Neon el host directo es el mismo que el del pooler sin "-pooler".
 */
function urlParaMigraciones(): string | undefined {
  if (process.env.DIRECT_URL) return process.env.DIRECT_URL;
  if (!process.env.DATABASE_URL) return undefined;

  const url = new URL(process.env.DATABASE_URL);
  url.hostname = url.hostname.replace("-pooler.", ".");
  // La conexión directa puede tardar más en abrir (y Neon puede estar
  // despertando el compute): el default de 5 s de Prisma se queda corto.
  if (!url.searchParams.has("connect_timeout")) url.searchParams.set("connect_timeout", "30");
  return url.toString();
}

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: {
    path: "prisma/migrations",
  },
  datasource: {
    url: urlParaMigraciones(),
  },
});
