import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "aws-cost-optimizer",
  description:
    "Find wasted AWS spend in 60 seconds. Local-first. Your credentials never leave your laptop.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-gray-950 text-gray-200">{children}</body>
    </html>
  );
}
