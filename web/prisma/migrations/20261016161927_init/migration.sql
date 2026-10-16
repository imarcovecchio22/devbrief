-- CreateTable
CREATE TABLE "items" (
    "id" SERIAL NOT NULL,
    "url_canonica" TEXT NOT NULL,
    "titulo" TEXT NOT NULL,
    "contenido_resumido" TEXT NOT NULL DEFAULT '',
    "fecha_publicacion" TIMESTAMPTZ(6),
    "fecha_ingesta" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "puntaje" SMALLINT,
    "seccion" TEXT,
    "motivo" TEXT,
    "puntuado_en" TIMESTAMPTZ(6),
    "intentos_puntaje" SMALLINT NOT NULL DEFAULT 0,
    "diario_id" INTEGER,

    CONSTRAINT "items_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "item_fuentes" (
    "item_id" INTEGER NOT NULL,
    "fuente" TEXT NOT NULL,
    "url_original" TEXT NOT NULL,
    "senal" INTEGER,
    "visto_en" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "item_fuentes_pkey" PRIMARY KEY ("item_id","fuente")
);

-- CreateTable
CREATE TABLE "diarios" (
    "id" SERIAL NOT NULL,
    "fecha" DATE NOT NULL,
    "contenido" JSONB NOT NULL,
    "creado_en" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "diarios_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "corridas" (
    "id" SERIAL NOT NULL,
    "inicio" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "fin" TIMESTAMPTZ(6),
    "items_nuevos" INTEGER NOT NULL DEFAULT 0,
    "items_puntuados" INTEGER NOT NULL DEFAULT 0,
    "tokens_entrada" INTEGER NOT NULL DEFAULT 0,
    "tokens_salida" INTEGER NOT NULL DEFAULT 0,
    "errores" JSONB NOT NULL DEFAULT '[]',

    CONSTRAINT "corridas_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "items_url_canonica_key" ON "items"("url_canonica");

-- CreateIndex
CREATE INDEX "items_diario_id_puntaje_idx" ON "items"("diario_id", "puntaje");

-- CreateIndex
CREATE INDEX "items_puntaje_intentos_puntaje_idx" ON "items"("puntaje", "intentos_puntaje");

-- CreateIndex
CREATE UNIQUE INDEX "diarios_fecha_key" ON "diarios"("fecha");

-- AddForeignKey
ALTER TABLE "items" ADD CONSTRAINT "items_diario_id_fkey" FOREIGN KEY ("diario_id") REFERENCES "diarios"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "item_fuentes" ADD CONSTRAINT "item_fuentes_item_id_fkey" FOREIGN KEY ("item_id") REFERENCES "items"("id") ON DELETE CASCADE ON UPDATE CASCADE;
