import { diaDeLaSemana, diaYMes } from "@/lib/fechas";
import type { ContenidoDiario, EntradaRadar, Nota } from "@/lib/tipos";
import { contarNotas } from "@/lib/tipos";

// Nombres de sección para agrupar el Radar. Copia de
// pipeline/src/diario/secciones.py: el Radar solo guarda la clave.
const NOMBRES_SECCION: Record<string, string> = {
  ia: "IA aplicada",
  ia_global: "Avances en IA",
  robotica: "Robótica",
  espacio: "Satélites y espacio",
  dotnet: ".NET y C#",
  python: "Python",
  web: "Stack web",
  repos: "Repos y herramientas",
  general: "Desarrollo en general",
  php: "PHP y Laravel",
  gamedev: "Game dev web",
  automatizaciones: "Automatizaciones",
  trading: "Trading algorítmico",
  impresion3d: "Impresión 3D",
};

function plural(n: number, singular: string, pluralForma: string): string {
  return `${n} ${n === 1 ? singular : pluralForma}`;
}

export function Diario({ diario }: { diario: ContenidoDiario }) {
  const notas = contarNotas(diario);
  const radar = diario.radar.length;

  return (
    <article>
      <header className="mt-14 sm:mt-20">
        <p className="font-sans text-xl text-tenue sm:text-2xl">{diaDeLaSemana(diario.fecha)}</p>
        <h1 className="font-sans text-[clamp(3rem,16vw,5.75rem)] leading-[0.92] font-bold tracking-[-0.035em] text-balance">
          {diaYMes(diario.fecha)}
        </h1>
        <p className="mt-5 text-tenue">
          {plural(notas, "nota", "notas")}
          {radar > 0 && <> y {plural(radar, "novedad más", "novedades más")} en el radar</>}.
        </p>
        <nav aria-label="Secciones" className="mt-6 font-sans text-[0.95rem]">
          <ul className="flex flex-wrap gap-x-5 gap-y-1.5">
            {diario.secciones.map((s) => (
              <li key={s.clave}>
                <a href={`#${s.clave}`} className="underline decoration-linea underline-offset-4 hover:decoration-tinta">
                  {s.nombre}
                </a>
              </li>
            ))}
            {radar > 0 && (
              <li>
                <a href="#radar" className="underline decoration-linea underline-offset-4 hover:decoration-tinta">
                  Radar
                </a>
              </li>
            )}
          </ul>
        </nav>
      </header>

      {diario.secciones.map((seccion) => (
        <section key={seccion.clave} id={seccion.clave} aria-labelledby={`t-${seccion.clave}`} className="mt-16">
          <h2
            id={`t-${seccion.clave}`}
            className="font-sans text-[1.65rem] leading-tight font-semibold tracking-[-0.015em]"
          >
            {seccion.nombre}
          </h2>
          <div className="mt-7 space-y-11">
            {seccion.notas.map((nota) => (
              <NotaDelDiario key={nota.item_ids[0]} nota={nota} />
            ))}
          </div>
        </section>
      ))}

      {radar > 0 && <Radar entradas={diario.radar} />}
    </article>
  );
}

function NotaDelDiario({ nota }: { nota: Nota }) {
  return (
    <div>
      <h3 className="font-sans text-[1.3rem] leading-[1.25] font-semibold tracking-[-0.01em] text-pretty">
        <a
          href={nota.url}
          target="_blank"
          rel="noopener noreferrer"
          className="underline decoration-transparent underline-offset-[5px] hover:decoration-current"
        >
          {nota.titular}
        </a>
      </h3>
      <p className="mt-2.5 text-pretty">{nota.resumen}</p>
      <p className="mt-3.5 border-l-[3px] border-sodio pl-4 text-pretty">
        <span className="font-sans text-[0.95rem] font-semibold text-sodio-texto">Por qué te sirve. </span>
        {nota.por_que_te_sirve}
      </p>
      <Fuentes fuentes={nota.fuentes} className="mt-3" />
    </div>
  );
}

function Fuentes({ fuentes, className = "" }: { fuentes: string[]; className?: string }) {
  if (fuentes.length === 0) return null;
  return (
    <p className={`font-sans text-sm text-tenue ${className}`}>
      {fuentes.length === 1 ? "Fuente" : "Fuentes"}: {fuentes.join(", ")}
    </p>
  );
}

function Radar({ entradas }: { entradas: EntradaRadar[] }) {
  // Agrupa respetando el orden en que vienen (el pipeline ya las ordena por sección).
  const grupos = new Map<string, EntradaRadar[]>();
  for (const entrada of entradas) {
    grupos.set(entrada.seccion, [...(grupos.get(entrada.seccion) ?? []), entrada]);
  }

  return (
    <section id="radar" aria-labelledby="t-radar" className="mt-20">
      <h2 id="t-radar" className="font-sans text-[1.65rem] leading-tight font-semibold tracking-[-0.015em]">
        Radar
      </h2>
      <p className="mt-2 text-tenue">
        El resto de lo que pasó en IA, robótica y espacio, en una línea cada cosa.
      </p>
      <div className="mt-6 border-t border-linea">
        {[...grupos].map(([seccion, items]) => (
          <details key={seccion} className="group border-b border-linea">
            <summary className="flex cursor-pointer items-baseline gap-3 py-3.5 font-sans">
              <span
                aria-hidden
                className="inline-block text-tenue transition-transform motion-reduce:transition-none group-open:rotate-90"
              >
                ▸
              </span>
              <span className="font-semibold">{NOMBRES_SECCION[seccion] ?? seccion}</span>
              <span className="text-tenue">{items.length}</span>
            </summary>
            <ul className="space-y-3.5 pb-5 pl-7">
              {items.map((item) => (
                <li key={item.item_ids[0]} className="text-[1rem] leading-[1.55] text-pretty">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline decoration-linea underline-offset-4 hover:decoration-tinta"
                  >
                    {item.linea}
                  </a>
                  <span className="ml-2 font-sans text-sm text-tenue">{item.fuentes.join(", ")}</span>
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>
    </section>
  );
}
