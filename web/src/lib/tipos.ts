// Forma de diarios.contenido. La escribe el pipeline de Python
// (pipeline/src/diario/llm/redaccion.py, modelo `Diario`): si cambia allá,
// cambia acá.

export type Nota = {
  item_ids: number[];
  titular: string;
  resumen: string;
  por_que_te_sirve: string;
  url: string;
  fuentes: string[];
};

export type Seccion = {
  clave: string;
  nombre: string;
  notas: Nota[];
};

export type EntradaRadar = {
  item_ids: number[];
  linea: string;
  url: string;
  fuentes: string[];
  seccion: string;
};

export type ContenidoDiario = {
  fecha: string; // YYYY-MM-DD
  secciones: Seccion[];
  radar: EntradaRadar[];
};

export type ResumenDiario = {
  fecha: string;
  notas: number;
  radar: number;
};

function esObjeto(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === "object" && valor !== null;
}

/**
 * Chequeo mínimo de la forma del JSON antes de renderizarlo: si el pipeline
 * guardara algo roto, preferimos un error claro a una página a medias.
 */
export function aContenidoDiario(valor: unknown): ContenidoDiario {
  if (
    !esObjeto(valor) ||
    typeof valor.fecha !== "string" ||
    !Array.isArray(valor.secciones) ||
    !Array.isArray(valor.radar)
  ) {
    throw new Error("El contenido del diario no tiene el formato esperado.");
  }
  return valor as ContenidoDiario;
}

export function contarNotas(contenido: ContenidoDiario): number {
  return contenido.secciones.reduce((total, s) => total + s.notas.length, 0);
}
