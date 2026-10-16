# Diario Técnico Personal

## Qué es
Un sistema que junta novedades técnicas de muchas fuentes, las filtra con
un LLM según mi perfil de intereses y genera un "diario" de 10-15 notas por
día. Reemplaza estar scrolleando Twitter/Reddit. También es proyecto de
portfolio, así que el código, la estructura y el README tienen que estar
prolijos.

## Arquitectura
- `pipeline/` — Python 3.12+, gestionado con uv. Corre una vez por día.
  1. Ingesta: lee `config/fuentes.yaml` y trae items (RSS/Atom, Reddit
     JSON, API de Algolia de HN, GitHub Trending scrapeado). Solo las
     fuentes con `activa: true`.
  2. Normalización y dedupe: misma URL canónica = mismo item. Agrupar
     también por similitud de título. Guardar todas las fuentes donde
     apareció (es señal de relevancia).
  3. Puntaje: cada item nuevo pasa por un modelo chico (Claude Haiku) con
     `config/perfil.md` como contexto. Devuelve JSON:
     {"puntaje": int 0-10, "seccion": str, "motivo": str}
  4. Redacción: los 10-15 mejores (puntaje >= 7) van a un modelo mejor
     (Claude Sonnet), que escribe el diario según el formato del perfil.
  5. Guarda el diario en la base.
- `web/` — Next.js (App Router) en Vercel. Muestra el diario del día y
  el archivo de diarios anteriores. Lee directo de la base.
- Base: PostgreSQL en Neon. Python accede con SQLAlchemy o psycopg,
  Next.js con Prisma. El esquema lo define una sola fuente de verdad
  (proponé cuál y justificalo).
- Ejecución diaria: GitHub Actions con cron, a las 6:00 hora Argentina.

## Datos mínimos
- items: id, url_canonica, titulo, contenido_resumido, fuente(s),
  fecha_publicacion, fecha_ingesta, puntaje, seccion, motivo
- diarios: id, fecha, contenido (JSON con secciones y notas)
- Más adelante: feedback (item_id, voto, comentario)

## Reglas
- Todo idempotente: correr el pipeline dos veces el mismo día no duplica
  nada ni gasta tokens de más (no repuntuar items ya puntuados).
- Recortar el contenido de cada item antes de mandarlo al LLM para
  controlar costos. Loguear tokens usados por corrida.
- Si una fuente falla, se loguea y se sigue con las demás.
- Las URLs marcadas con "verificar" en fuentes.yaml pueden estar mal:
  incluir un comando que pruebe cada fuente e informe cuáles fallan.
- Secrets por variables de entorno (ANTHROPIC_API_KEY, DATABASE_URL).
  Nunca en el repo.
- Verificar en la documentación de Anthropic los nombres actuales de los
  modelos antes de usarlos.
- Tests para normalización, dedupe y parseo de la respuesta del LLM.
- Código y comentarios en español está bien; nombres de variables en
  inglés.

## Fases
- MVP: pipeline completo con las fuentes activas, diario visible en web.
- V2: todas las fuentes, envío por mail o Telegram a la mañana, búsqueda
  en el archivo.
- V3: 👍/👎 por nota que alimenta el perfil, resumen semanal, sección
  diaria "Probalo hoy".
