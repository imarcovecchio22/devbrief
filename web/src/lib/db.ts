import { PrismaNeon } from "@prisma/adapter-neon";
import { PrismaClient } from "@/generated/prisma/client";

function crearCliente(): PrismaClient {
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    throw new Error("Falta DATABASE_URL (ver .env.example en la raíz del repo).");
  }
  // Driver serverless de Neon: conexiones por WebSocket, pensado para Vercel.
  return new PrismaClient({ adapter: new PrismaNeon({ connectionString }) });
}

// En desarrollo, el hot reload re-evalúa los módulos: guardamos el cliente en
// globalThis para no abrir una conexión nueva en cada cambio.
const global = globalThis as unknown as { prisma?: PrismaClient };

export const prisma = global.prisma ?? crearCliente();
if (process.env.NODE_ENV !== "production") global.prisma = prisma;
