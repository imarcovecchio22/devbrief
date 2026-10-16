import { Diario } from "@/components/diario";
import { obtenerUltimoDiario } from "@/lib/diarios";

export default async function Portada() {
  const diario = await obtenerUltimoDiario();

  if (!diario) {
    return (
      <div className="mt-20">
        <h1 className="font-sans text-4xl font-bold tracking-tight">Todavía no hay diarios</h1>
        <p className="mt-4 text-tenue">
          El primero aparece acá cuando corra el pipeline: <code>uv run diario run</code> en la
          carpeta <code>pipeline</code>.
        </p>
      </div>
    );
  }

  return <Diario diario={diario} />;
}
