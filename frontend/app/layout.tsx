import type { Metadata } from "next";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000",
  ),
  title: "ShipBounty — Automated PR Reviews & Bounties",
  description:
    "Reliable GitHub ingestion, evidence-backed contribution review, and auditable rewards.",
  openGraph: {
    title: "ShipBounty — Automated PR Reviews & Bounties",
    description: "Reliable ingestion. Evidence-backed rewards.",
    type: "website",
    images: [
      {
        url: "/shipbounty-logo.png",
        width: 512,
        height: 512,
        alt: "ShipBounty evidence-backed reviews and auditable rewards operations",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "ShipBounty — Automated PR Reviews & Bounties",
    description: "Reliable ingestion. Evidence-backed rewards.",
    images: ["/shipbounty-logo.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className="h-full antialiased"
      data-scroll-behavior="smooth"
    >
      <body className="min-h-full bg-background text-foreground">
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
