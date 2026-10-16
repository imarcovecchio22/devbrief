import type { Metadata, Viewport } from "next";
import { Literata, Schibsted_Grotesk } from "next/font/google";
import Link from "next/link";
import "./globals.css";

// Grotesca de origen periodístico para titulares e interfaz; serif diseñada
// para leer en pantalla para el cuerpo.
const grotesca = Schibsted_Grotesk({
  subsets: ["latin"],
  variable: "--fuente-grotesca",
  display: "swap",
});

const serif = Literata({
  subsets: ["latin"],
  variable: "--fuente-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Diario", template: "%s | Diario" },
  description:
    "Las novedades técnicas del día, elegidas y resumidas cada mañana: IA, robótica, espacio y desarrollo.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#eef1f5" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1a2b" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${grotesca.variable} ${serif.variable}`}>
      <body className="min-h-dvh">
        <div className="mx-auto max-w-[38rem] px-5 pt-6 pb-16 sm:px-6 sm:pt-10">
          <header className="flex items-baseline justify-between font-sans text-[0.95rem]">
            <Link href="/" className="font-semibold tracking-tight">
              Diario
            </Link>
            <nav aria-label="Principal">
              <Link
                href="/archivo"
                className="text-tenue underline-offset-4 hover:text-tinta hover:underline"
              >
                Archivo
              </Link>
            </nav>
          </header>
          {children}
          <footer className="mt-20 font-sans text-sm text-tenue">
            Se arma solo cada mañana a las 6, con noticias de decenas de fuentes elegidas y
            resumidas por Claude.
          </footer>
        </div>
      </body>
    </html>
  );
}
