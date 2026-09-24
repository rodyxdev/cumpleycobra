import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { SiteHeader } from "@/components/site-header";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Cumple&Cobra",
  description: "El acuerdo verificable para trabajo de código. Si cumple lo acordado, cobras.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-muted/30">
        <Providers>
          <SiteHeader />
          <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">{children}</main>
          <footer className="border-t py-4 text-center text-xs text-muted-foreground">
            Cumple&amp;Cobra · Motor de Análisis Estático de Código basado en LLM · Testnet de Stellar
          </footer>
        </Providers>
      </body>
    </html>
  );
}
