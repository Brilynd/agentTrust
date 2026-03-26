import "./globals.css";

import type { ReactNode } from "react";

export const metadata = {
  title: "AgentTrust Control Plane",
  description: "Centralized multi-agent dashboard for AgentTrust"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
