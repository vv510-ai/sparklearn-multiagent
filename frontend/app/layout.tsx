import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SparkLearn 星火学伴 · 学习的左膀右臂",
  description: "讯飞星火驱动的智能学习机:一句话整理讲解、练习、路线和可追溯出处。",
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
