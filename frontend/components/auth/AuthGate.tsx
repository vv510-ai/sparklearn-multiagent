"use client";

import { ArrowRight, Eye, EyeOff, LockKeyhole, Mail, Sparkles, UserRound } from "lucide-react";
import { FormEvent, useState } from "react";
import CinematicBackground from "@/components/ui/CinematicBackground";
import { apiPost } from "@/lib/api";

export type AuthUser = {
  id: string;
  email: string;
  name: string;
  demo?: boolean;
};

export default function AuthGate({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const response = await apiPost<{ user: AuthUser }>(
        mode === "login" ? "/auth/login" : "/auth/register",
        mode === "login" ? { email, password } : { name, email, password },
      );
      onAuthenticated(response.user);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message.replace(/^POST\s+\/auth\/(?:login|register)\s+→\s+\d+:\s*/, ""));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="relative min-h-dvh overflow-hidden bg-[#062B38] text-white">
      <CinematicBackground subdued />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_22%_25%,rgba(54,185,139,0.20),transparent_34%),linear-gradient(110deg,rgba(3,34,45,0.88),rgba(4,33,45,0.55))]" />

      <div className="relative z-10 mx-auto grid min-h-dvh w-full max-w-6xl items-center gap-12 px-5 py-10 lg:grid-cols-[1.05fr_0.8fr] lg:px-10">
        <section className="hidden max-w-xl lg:block">
          <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-4 py-2 text-sm text-white/80 backdrop-blur-xl">
            <Sparkles size={15} className="text-[#9DE5B9]" /> 你的学习空间，只属于你
          </div>
          <h1 className="text-6xl font-normal leading-[1.02]" style={{ fontFamily: "var(--font-display)" }}>
            学习会积累，<br /><span className="text-white/55">进步有证据。</span>
          </h1>
          <p className="mt-6 max-w-lg text-base leading-8 text-white/65">
            登录后，你上传的资料、学习记录、测验结果与知识路径会安全地保存在自己的账户中。
          </p>
        </section>

        <section className="mx-auto w-full max-w-[430px] rounded-[28px] border border-white/20 bg-white/[0.12] p-3 shadow-[0_35px_100px_rgba(0,12,22,0.38)] backdrop-blur-2xl">
          <div className="rounded-[22px] bg-white px-6 py-7 text-[#1D2028] sm:px-8 sm:py-8">
            <div className="mb-7 flex items-center gap-2.5">
              <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#0F6B50] text-white"><Sparkles size={18} /></span>
              <div><strong className="block text-lg">SparkLearn</strong><span className="text-xs text-[#7C8491]">星火学伴</span></div>
            </div>

            <div className="mb-6 grid grid-cols-2 rounded-xl bg-[#F0F2F5] p-1" role="tablist" aria-label="登录方式">
              {(["login", "register"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={mode === item}
                  onClick={() => { setMode(item); setError(""); }}
                  className={`rounded-[9px] px-3 py-2.5 text-sm font-semibold transition ${mode === item ? "bg-white text-[#143D34] shadow-sm" : "text-[#78808D]"}`}
                >
                  {item === "login" ? "登录" : "创建账户"}
                </button>
              ))}
            </div>

            <div className="mb-6">
              <h2 className="text-2xl font-bold">{mode === "login" ? "欢迎回来" : "建立你的学习档案"}</h2>
              <p className="mt-1.5 text-sm leading-6 text-[#7A818D]">
                {mode === "login" ? "继续上一次的学习进度。" : "以后每一次学习都会归档到这个账户。"}
              </p>
            </div>

            <form onSubmit={submit} className="space-y-4">
              {mode === "register" && (
                <label className="block">
                  <span className="mb-1.5 block text-xs font-semibold text-[#5D6470]">称呼</span>
                  <span className="flex items-center gap-2.5 rounded-xl border border-[#DDE1E7] px-3.5 focus-within:border-[#0F6B50] focus-within:ring-2 focus-within:ring-[#0F6B50]/10">
                    <UserRound size={17} className="text-[#959BA5]" />
                    <input required maxLength={80} autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} placeholder="怎么称呼你" className="min-w-0 flex-1 bg-transparent py-3.5 text-sm outline-none placeholder:text-[#A8ADB5]" />
                  </span>
                </label>
              )}

              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold text-[#5D6470]">邮箱</span>
                <span className="flex items-center gap-2.5 rounded-xl border border-[#DDE1E7] px-3.5 focus-within:border-[#0F6B50] focus-within:ring-2 focus-within:ring-[#0F6B50]/10">
                  <Mail size={17} className="text-[#959BA5]" />
                  <input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" className="min-w-0 flex-1 bg-transparent py-3.5 text-sm outline-none placeholder:text-[#A8ADB5]" />
                </span>
              </label>

              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold text-[#5D6470]">密码</span>
                <span className="flex items-center gap-2.5 rounded-xl border border-[#DDE1E7] px-3.5 focus-within:border-[#0F6B50] focus-within:ring-2 focus-within:ring-[#0F6B50]/10">
                  <LockKeyhole size={17} className="text-[#959BA5]" />
                  <input required minLength={8} maxLength={128} type={showPassword ? "text" : "password"} autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="至少 8 位" className="min-w-0 flex-1 bg-transparent py-3.5 text-sm outline-none placeholder:text-[#A8ADB5]" />
                  <button type="button" onClick={() => setShowPassword((visible) => !visible)} className="text-[#8B929C]" aria-label={showPassword ? "隐藏密码" : "显示密码"}>
                    {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </span>
              </label>

              {error && <div role="alert" className="rounded-xl border border-[#F0D0C5] bg-[#FFF5F1] px-3.5 py-3 text-sm leading-5 text-[#A0442C]">{error}</div>}

              <button disabled={submitting} className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#0F6B50] px-4 py-3.5 text-sm font-bold text-white transition hover:bg-[#0B5C44] disabled:cursor-wait disabled:opacity-60">
                {submitting ? "正在验证…" : mode === "login" ? "登录并继续" : "创建账户"}
                {!submitting && <ArrowRight size={17} />}
              </button>
            </form>

            <p className="mt-5 text-center text-[11px] leading-5 text-[#9298A2]">密码只保存为不可逆哈希，登录令牌不会暴露给网页脚本。</p>
          </div>
        </section>
      </div>
    </main>
  );
}
