import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Instrument_Serif } from "next/font/google";
import "./globals.css";

// Three roles, three faces.
// Display: Instrument Serif — hero numerals and headlines, read as values on a
// dial. UI: IBM Plex Sans — labels, prose, gate reasons. Data: IBM Plex Mono,
// tabular — every figure, contract symbol and log line.
const serif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-serif",
  display: "swap",
});

const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
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
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#101318" },
    { media: "(prefers-color-scheme: light)", color: "#EDEBE6" },
  ],
  width: "device-width",
  initialScale: 1,
};

// Runs before paint: localStorage first, prefers-color-scheme as the default.
// Inline so there is no flash of the wrong theme; try/catch because storage
// access can throw in private windows.
const THEME_BOOT = `(function(){try{var t=localStorage.getItem("skew-theme");if(t!=="dark"&&t!=="light"){t=window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";}document.documentElement.setAttribute("data-theme",t);}catch(e){document.documentElement.setAttribute("data-theme","dark");}})();`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning: the boot script rewrites data-theme before
    // hydration, and that one attribute diff is deliberate.
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${serif.variable} ${sans.variable} ${plexMono.variable}`}
    >
      <body className="min-h-screen bg-ground text-text antialiased">
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
        {children}
      </body>
    </html>
  );
}
