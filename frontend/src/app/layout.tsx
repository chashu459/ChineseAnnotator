import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Annotator Frontend",
  description: "Next.js frontend for the Annotator backend",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // suppressHydrationWarning: mobile browsers/webviews (e.g. Chrome iOS
  // internals) may inject attributes like __gcrremoteframetoken into <html>
  // before hydration; the server can never match those.
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <body className="min-h-full bg-slate-100 text-slate-950">
        {children}
      </body>
    </html>
  );
}
