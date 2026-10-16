import path from "node:path";
import { config } from "dotenv";
import type { NextConfig } from "next";

// Un solo .env para todo el repo, en la raíz (lo comparte con el pipeline).
// Se carga acá, antes de que Next lance sus workers, para que lo hereden.
// (@next/env no sirve: ya cargó la carpeta web/ y cachea el resultado.)
// En Vercel las variables vienen de la configuración del proyecto.
config({ path: path.resolve(process.cwd(), "../.env"), quiet: true });

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
