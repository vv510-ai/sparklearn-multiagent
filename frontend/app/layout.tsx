import type { Metadata } from "next";
import "./globals.css";
import "./learning-upgrade.css";

export const metadata: Metadata = {
  title: "知行循证 LearnLoop · 让学习发生，有据可循",
  description: "面向高校专业课程的可验证个性化学习平台：从资料、诊断和独立作答，到有依据的下一步学习。",
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
