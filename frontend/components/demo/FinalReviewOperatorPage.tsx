"use client";

import { ArrowLeft, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import AuthGate, { type AuthUser } from "@/components/auth/AuthGate";
import FinalReviewPanel from "@/components/demo/FinalReviewPanel";
import CinematicBackground from "@/components/ui/CinematicBackground";
import { apiGet } from "@/lib/api";

export default function FinalReviewOperatorPage() {
  const [status, setStatus] = useState<"loading" | "authenticated" | "anonymous">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    let active = true;
    void apiGet<AuthUser>("/auth/me")
      .then((current) => {
        if (!active) return;
        setUser(current);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active) return;
        setUser(null);
        setStatus("anonymous");
      });
    return () => { active = false; };
  }, []);

  if (status === "loading") {
    return (
      <main className="relative grid min-h-dvh place-items-center overflow-hidden bg-[#062B38] text-white">
        <CinematicBackground subdued />
        <div className="relative z-10 flex items-center gap-3 rounded-full border border-white/15 bg-white/10 px-5 py-3 text-sm backdrop-blur-xl">
          <ShieldCheck size={18} /> 正在验证操作账号…
        </div>
      </main>
    );
  }

  if (status === "anonymous" || !user) {
    return <AuthGate onAuthenticated={(current) => { setUser(current); setStatus("authenticated"); }} />;
  }

  return (
    <main className="min-h-dvh bg-[#F5F7F6] px-4 py-8 text-[#1D2028] sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[10px] font-bold tracking-[0.2em] text-[#0F6B50]">OPERATOR ONLY · UNLINKED</div>
            <h1 className="mt-2 text-2xl font-bold">演示准备与恢复</h1>
            <p className="mt-1 text-sm text-[#717986]">本页只供演示人员在录制前使用，不会出现在学习者的学习工坊。</p>
          </div>
          <Link href="/" className="secondary-action inline-flex items-center gap-2">
            <ArrowLeft size={15} /> 返回学习界面
          </Link>
        </div>
        <FinalReviewPanel />
      </div>
    </main>
  );
}
