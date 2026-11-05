import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Morrow Supply — Thoughtful everyday tech",
  description: "Considered tech essentials for your desk, your commute, and everywhere in between.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
