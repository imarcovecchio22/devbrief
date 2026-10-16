import { cacheLife } from "next/cache";
import { prisma } from "@/lib/db";
import {
  aContenidoDiario,
  contarNotas,
  type ContenidoDiario,
  type ResumenDiario,
} from "@/lib/tipos";

// El pipeline publica un diario por día, a las 6:00. Con revalidación por
// minutos, el diario nuevo aparece enseguida sin consultar la base en cada visita.

/** "YYYY-MM-DD" de una columna DATE (Prisma la trae como medianoche UTC). */
function aFechaIso(fecha: Date): string {
  return fecha.toISOString().slice(0, 10);
}

export async function obtenerUltimoDiario(): Promise<ContenidoDiario | null> {
  "use cache";
  cacheLife("minutes");

  const diario = await prisma.diario.findFirst({ orderBy: { fecha: "desc" } });
  return diario ? aContenidoDiario(diario.contenido) : null;
}

export async function obtenerDiario(fecha: string): Promise<ContenidoDiario | null> {
  "use cache";
  cacheLife("hours");

  const diario = await prisma.diario.findUnique({
    where: { fecha: new Date(`${fecha}T00:00:00Z`) },
  });
  return diario ? aContenidoDiario(diario.contenido) : null;
}

export async function listarDiarios(): Promise<ResumenDiario[]> {
  "use cache";
  cacheLife("minutes");

  const diarios = await prisma.diario.findMany({
    orderBy: { fecha: "desc" },
    select: { fecha: true, contenido: true },
  });
  return diarios.map((d) => {
    const contenido = aContenidoDiario(d.contenido);
    return {
      fecha: aFechaIso(d.fecha),
      notas: contarNotas(contenido),
      radar: contenido.radar.length,
    };
  });
}

export async function fechasRecientes(cantidad: number): Promise<string[]> {
  "use cache";
  cacheLife("minutes");

  const diarios = await prisma.diario.findMany({
    orderBy: { fecha: "desc" },
    take: cantidad,
    select: { fecha: true },
  });
  return diarios.map((d) => aFechaIso(d.fecha));
}
