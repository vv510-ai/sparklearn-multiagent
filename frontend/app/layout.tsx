import type { Metadata } from "next";
import { BRAND } from "@/lib/brand";
import "katex/dist/katex.min.css";
import "./globals.css";
import "./learning-upgrade.css";
import "./learning-intake.css";
import "driver.js/dist/driver.css";
import "./learning-guide.css";

export const metadata: Metadata = {
  title: "知行循证 LearnLoop · 让学习发生，有据可循",
  description: `${BRAND.title}。${BRAND.promise}`,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-emerald-700 focus:px-4 focus:py-2 focus:text-sm focus:font-bold focus:text-white"
        >
          跳到主内容
        </a>

        <div id="main">
          {children}
        </div>
      </body>
    </html>
  );
}
