import type { Metadata } from "next";
import { DM_Sans, JetBrains_Mono } from "next/font/google";

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

export const metadata: Metadata = {
  title: "Cumple&Cobra",
  description: "El acuerdo verificable para trabajo de código. Si cumple lo acordado, cobras.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${dmSans.variable} ${jetbrainsMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <Providers>
          <SiteHeader />
          <main className="mx-auto w-full max-w-[1248px] flex-1 px-5 py-10 sm:px-8 lg:py-14">{children}</main>
          <footer className="mx-auto w-full max-w-[1248px] border-t px-5 py-7 text-center text-sm leading-relaxed text-muted-foreground sm:px-8">
            Cumple&amp;Cobra · Motor de Análisis Estático de Código basado en LLM · Testnet de Stellar
          </footer>
        </Providers>
      </body>
    </html>
  );
}
