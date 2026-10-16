"""Acceso a la base. Todo el SQL del pipeline vive acá.

El esquema lo define web/prisma/schema.prisma; este módulo solo usa sus
tablas. La conexión está en autocommit y las operaciones que tienen que ser
atómicas abren su propia transacción.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Self

import psycopg
from psycopg.types.json import Jsonb

from diario.dedupe import Grupo, Referencia
from diario.normalizacion import recortar


@dataclass(frozen=True, slots=True)
class ResultadoGuardado:
    items_nuevos: int
    apariciones_nuevas: int


class Repositorio:
    def __init__(self, conexion: psycopg.Connection[Any]) -> None:
        self._db = conexion

    @classmethod
    @contextmanager
    def conectar(cls, url: str) -> Iterator[Self]:
        with psycopg.connect(url, autocommit=True, connect_timeout=30) as conexion:
            yield cls(conexion)

    # ---------- items ----------

    def referencias_recientes(self, dias: int) -> list[Referencia]:
        """Items ingresados en los últimos `dias`, para deduplicar contra ellos."""
        filas = self._db.execute(
            """
            SELECT i.url_canonica, i.titulo, array_agg(f.fuente)
            FROM items i
            JOIN item_fuentes f ON f.item_id = i.id
            WHERE i.fecha_ingesta >= now() - make_interval(days => %s)
            GROUP BY i.id
            """,
            (dias,),
        ).fetchall()
        return [Referencia(url, titulo, frozenset(fuentes)) for url, titulo, fuentes in filas]

    def guardar_grupos(self, grupos: Sequence[Grupo], max_contenido: int) -> ResultadoGuardado:
        """Inserta los items nuevos y suma las apariciones nuevas a los existentes.

        Idempotente: guardar dos veces lo mismo no cambia nada (salvo subir la
        `senal` si creció, por ejemplo los puntos de HN).
        """
        if not grupos:
            return ResultadoGuardado(items_nuevos=0, apariciones_nuevas=0)

        # Todo por lotes: executemany usa el pipeline mode de Postgres y manda
        # las consultas sin esperar cada respuesta. Con la base lejos, hacerlo
        # fila por fila serían cientos de idas y vueltas.
        with self._db.transaction(), self._db.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO items (url_canonica, titulo, contenido_resumido, fecha_publicacion)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (url_canonica) DO NOTHING
                """,
                [
                    (
                        g.url_canonica,
                        g.titulo,
                        recortar(g.contenido, max_contenido) if g.contenido else "",
                        g.fecha_publicacion,
                    )
                    for g in grupos
                ],
            )
            items_nuevos = cur.rowcount

            ids: dict[str, int] = dict(
                cur.execute(
                    "SELECT url_canonica, id FROM items WHERE url_canonica = ANY(%s)",
                    ([g.url_canonica for g in grupos],),
                ).fetchall()
            )
            apariciones = [
                (ids[g.url_canonica], a.fuente, a.url, a.senal)
                for g in grupos
                for a in g.apariciones
            ]

            cur.executemany(
                """
                INSERT INTO item_fuentes (item_id, fuente, url_original, senal)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (item_id, fuente) DO NOTHING
                """,
                apariciones,
            )
            apariciones_nuevas = cur.rowcount

            # La señal (ej. puntos de HN) sigue creciendo entre corridas.
            cur.executemany(
                """
                UPDATE item_fuentes SET senal = %(senal)s
                WHERE item_id = %(item_id)s AND fuente = %(fuente)s
                  AND (senal IS NULL OR senal < %(senal)s)
                """,
                [
                    {"item_id": item_id, "fuente": fuente, "senal": senal}
                    for item_id, fuente, _, senal in apariciones
                    if senal is not None
                ],
            )

        return ResultadoGuardado(items_nuevos=items_nuevos, apariciones_nuevas=apariciones_nuevas)

    # ---------- corridas ----------

    def iniciar_corrida(self) -> int:
        fila = self._db.execute("INSERT INTO corridas DEFAULT VALUES RETURNING id").fetchone()
        assert fila is not None
        return int(fila[0])

    def cerrar_corrida(
        self,
        corrida_id: int,
        *,
        items_nuevos: int = 0,
        items_puntuados: int = 0,
        tokens_entrada: int = 0,
        tokens_salida: int = 0,
        errores: Sequence[dict[str, str]] = (),
    ) -> None:
        self._db.execute(
            """
            UPDATE corridas SET
                fin = now(),
                items_nuevos = %s,
                items_puntuados = %s,
                tokens_entrada = %s,
                tokens_salida = %s,
                errores = %s
            WHERE id = %s
            """,
            (
                items_nuevos,
                items_puntuados,
                tokens_entrada,
                tokens_salida,
                Jsonb(list(errores)),
                corrida_id,
            ),
        )
