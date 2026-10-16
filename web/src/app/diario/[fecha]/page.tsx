import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Diario } from "@/components/diario";
import { fechasRecientes, obtenerDiario } from "@/lib/diarios";
import { esFechaValida, fechaCompleta } from "@/lib/fechas";

// Se prerenderizan los diarios de la última semana; los más viejos se
// generan en la primera visita y quedan en caché.
export async function generateStaticParams() {
  const fechas = await fechasRecientes(7);
  // Con Cache Components hace falta al menos un parámetro: si todavía no hay
  // diarios, uno inválido que termina en 404.
  return fechas.length > 0 ? fechas.map((fecha) => ({ fecha })) : [{ fecha: "sin-diarios" }];
}

export async function generateMetadata(props: PageProps<"/diario/[fecha]">): Promise<Metadata> {
  const { fecha } = await props.params;
  return { title: esFechaValida(fecha) ? fechaCompleta(fecha) : "Diario no encontrado" };
}

export default function PaginaDiario(props: PageProps<"/diario/[fecha]">) {
  return (
    <Suspense fallback={<p className="mt-20 text-tenue">Cargando el diario…</p>}>
      <DiarioDeLaFecha params={props.params} />
    </Suspense>
  );
}

async function DiarioDeLaFecha({ params }: Pick<PageProps<"/diario/[fecha]">, "params">) {
  const { fecha } = await params;
  if (!esFechaValida(fecha)) notFound();

  const diario = await obtenerDiario(fecha);
  if (!diario) notFound();

  return <Diario diario={diario} />;
}
