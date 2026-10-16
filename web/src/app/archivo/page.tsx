import type { Metadata } from "next";
import Link from "next/link";
import { listarDiarios } from "@/lib/diarios";
import { diaCorto, mesYAnio } from "@/lib/fechas";
import type { ResumenDiario } from "@/lib/tipos";

export const metadata: Metadata = { title: "Archivo" };

export default async function Archivo() {
  const diarios = await listarDiarios();

  // Agrupa por mes respetando el orden (del más nuevo al más viejo).
  const porMes = new Map<string, ResumenDiario[]>();
  for (const d of diarios) {
    const mes = mesYAnio(d.fecha);
    porMes.set(mes, [...(porMes.get(mes) ?? []), d]);
  }

  return (
    <div>
      <h1 className="mt-14 font-sans text-[clamp(2.75rem,12vw,4.5rem)] leading-[0.95] font-bold tracking-[-0.03em] sm:mt-20">
        Archivo
      </h1>
      {diarios.length === 0 ? (
        <p className="mt-6 text-tenue">Todavía no hay diarios anteriores.</p>
      ) : (
        [...porMes].map(([mes, delMes]) => (
          <section key={mes} aria-label={mes} className="mt-12">
            <h2 className="font-sans text-xl font-semibold first-letter:uppercase">{mes}</h2>
            <ul className="mt-3 border-t border-linea">
              {delMes.map((d) => (
                <li key={d.fecha} className="border-b border-linea">
                  <Link
                    href={`/diario/${d.fecha}`}
                    className="flex items-baseline justify-between gap-4 py-3 hover:text-tenue"
                  >
                    <span className="font-sans font-semibold">{diaCorto(d.fecha)}</span>
                    <span className="text-[0.95rem] text-tenue">
                      {d.notas} notas{d.radar > 0 && `, ${d.radar} en el radar`}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
