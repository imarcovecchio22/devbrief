# web

La parte visible de [devbrief](../README.md): Next.js 16 (App Router con Cache
Components), Prisma 7 sobre Neon y Tailwind 4.

- `/`: el diario más reciente.
- `/diario/AAAA-MM-DD`: un diario puntual.
- `/archivo`: todos los diarios, por mes.

Las lecturas de la base están en [`src/lib/diarios.ts`](src/lib/diarios.ts) como funciones
`'use cache'`: el diario del día se revalida cada minuto y los viejos, cada hora.

```bash
npm install          # también genera el cliente de Prisma
npm run dev          # http://localhost:3000 (lee DATABASE_URL del .env de la raíz)
npm run lint
npm run typecheck
npm run db:migrate   # nueva migración después de cambiar prisma/schema.prisma
```

El esquema de [`prisma/schema.prisma`](prisma/schema.prisma) es la fuente de verdad de la
base para todo el proyecto: el pipeline de Python escribe sobre las mismas tablas.
