import type { Metadata, Viewport } from "next";
import { Geist_Mono, Manrope } from "next/font/google";
import "./globals.css";

// Two roles, two faces.
// Manrope carries everything human — headlines, labels, prose — one premium
// variable family from 96px displays down to 13px captions. Geist Mono carries
// everything machine: figures, contract symbols, log lines.
const sans = Manrope({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-sans",
  display: "swap",
});

const mono = Geist_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-geist-mono",
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
    { media: "(prefers-color-scheme: dark)", color: "#09090B" },
    { media: "(prefers-color-scheme: light)", color: "#FFFFFF" },
  ],
  width: "device-width",
  initialScale: 1,
};

// Runs before paint: localStorage first, prefers-color-scheme as the default.
// Inline so there is no flash of the wrong theme; try/catch because storage
// access can throw in private windows.
const THEME_BOOT = `(function(){document.documentElement.classList.add("js");try{var q=location.search.match(/[?&]theme=(dark|light)/);var t=q?q[1]:localStorage.getItem("skew-theme");if(t!=="dark"&&t!=="light"){t=window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";}document.documentElement.setAttribute("data-theme",t);}catch(e){document.documentElement.setAttribute("data-theme","dark");}})();`;

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
      className={`${sans.variable} ${mono.variable}`}
    >
      <body className="min-h-screen bg-ground text-text antialiased">
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
        {children}
      </body>
    </html>
  );
}
