import type { Metadata, Viewport } from "next";
import { Archivo, IBM_Plex_Mono, Instrument_Sans } from "next/font/google";
import "./globals.css";

// Three roles, three faces — docs/03-DESIGN-SYSTEM.md.
// Display: section headers, the symbol under focus. Body: prose, gate reasons,
// model rationale. Data: every number, every contract symbol, the audit log.
const archivo = Archivo({
  subsets: ["latin"],
  weight: ["600", "700"],
  variable: "--font-archivo",
  display: "swap",
});

const instrument = Instrument_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-instrument",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "SKEW — autonomous volatility desk",
  description:
    "An options agent that never predicts price direction. It measures the gap between " +
    "implied and realized volatility and takes defined-risk positions into it, with every " +
    "trade gated by a deterministic stress test. Paper trading only.",
};

export const viewport: Viewport = {
  themeColor: "#0B0E1A",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${archivo.variable} ${instrument.variable} ${plexMono.variable}`}>
      <body className="min-h-screen bg-ground text-text antialiased">{children}</body>
    </html>
  );
}
