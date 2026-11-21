import type { Metadata } from "next";
import Image from "next/image";
import { DM_Sans, JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";

import { Providers } from "@/components/providers";
import { SiteHeader } from "@/components/site-header";

import "./globals.css";

const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

// Títulos: geométrica redondeada, cercana a la letra del logo.
const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
  weight: ["600", "700", "800"],
});

export const metadata: Metadata = {
  title: "Cumple&Cobra",
  description: "Pago verificado para código. Si cumple lo acordado, cobras.",
  icons: { icon: "/brand/logo-mark.png" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${dmSans.variable} ${jetbrainsMono.variable} ${jakarta.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <Providers>
          <SiteHeader />
          <main className="mx-auto w-full max-w-[1248px] flex-1 px-5 py-10 sm:px-8 lg:py-14">{children}</main>
          <footer className="border-t bg-card">
            <div className="mx-auto flex w-full max-w-[1248px] flex-wrap items-center justify-between gap-4 px-5 py-7 text-sm leading-relaxed text-muted-foreground sm:px-8">
              <span className="flex items-center gap-3">
                <Image src="/brand/logo-mark.png" alt="" width={28} height={25} />
                Cumple&amp;Cobra · Pago verificado para código
              </span>
              <span>Motor de Análisis Estático de Código basado en LLM · Testnet de Stellar</span>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
