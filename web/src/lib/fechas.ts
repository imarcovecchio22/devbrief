const FORMATO_FECHA = /^\d{4}-\d{2}-\d{2}$/;

export function esFechaValida(texto: string): boolean {
  if (!FORMATO_FECHA.test(texto)) return false;
  const fecha = new Date(`${texto}T00:00:00Z`);
  return !Number.isNaN(fecha.getTime()) && fecha.toISOString().startsWith(texto);
}

// Las fechas del diario son días sin hora: se formatean en UTC para que la
// zona horaria del servidor no las corra un día.
function formatear(fecha: string, opciones: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat("es-AR", { timeZone: "UTC", ...opciones }).format(
    new Date(`${fecha}T00:00:00Z`),
  );
}

/** "viernes" */
export const diaDeLaSemana = (fecha: string) => formatear(fecha, { weekday: "long" });

/** "16 de octubre" */
export const diaYMes = (fecha: string) => formatear(fecha, { day: "numeric", month: "long" });

/** "viernes 16 de octubre de 2026" */
export const fechaCompleta = (fecha: string) =>
  formatear(fecha, { weekday: "long", day: "numeric", month: "long", year: "numeric" });

/** "octubre de 2026" */
export const mesYAnio = (fecha: string) => formatear(fecha, { month: "long", year: "numeric" });

/** "vie 16" */
export const diaCorto = (fecha: string) =>
  formatear(fecha, { weekday: "short", day: "numeric" }).replace(".", "");
