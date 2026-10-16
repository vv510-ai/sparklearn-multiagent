"use client";

import { ArrowRight, Clapperboard, Eye, EyeOff, Images, LockKeyhole, Mail, Music4, Sparkles, UserRound } from "lucide-react";
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
    <main className="ll-auth">
      <CinematicBackground />

      <div className="ll-auth-inner">
        <section className="hidden lg:block" aria-label="知行循证 LearnLoop 简介">
          <div className="ll-auth-brand">
            <span className="ll-logo"><Sparkles size={20} /></span>
            <div><strong className="block text-lg font-black tracking-tight">知行循证 LearnLoop</strong><span className="text-xs text-[#9ff0cd]">多模态 AI 学习机</span></div>
          </div>
          <p className="ll-auth-kicker mt-10">LEARN · SEE · REMEMBER · PRACTICE</p>
          <h1 className="ll-auth-title">任何知识，<br />都能被<em>看懂、记住、练会</em></h1>
          <p className="ll-auth-lead">上传资料或说出想学的主题，AI 为你生成一图看懂、讲解视频和记忆歌曲，再用练习与间隔复习确认真的学会；每一步都有依据可查。</p>
          <div className="ll-auth-features">
            <div className="ll-auth-feature"><Images size={22} /><strong>一图看懂</strong><small>复杂知识自动拆成 1~N 张图，逐张核对</small></div>
            <div className="ll-auth-feature"><Clapperboard size={22} /><strong>讲解视频</strong><small>动画、配音、字幕一次生成 1080P 成片</small></div>
            <div className="ll-auth-feature"><Music4 size={22} /><strong>记忆歌曲</strong><small>口诀写成歌，跟唱填空也能复习</small></div>
          </div>
          <div className="ll-auth-loop" aria-label="学习闭环"><span>看懂</span><ArrowRight size={14} /><span>记住</span><ArrowRight size={14} /><span>练会</span><ArrowRight size={14} /><span>复盘</span></div>
        </section>

        <section className="ll-auth-card">
          <div className="ll-auth-card-body">
            <div className="mb-7 flex items-center gap-2.5">
              <span className="ll-logo" style={{ width: 38, height: 38, borderRadius: 12 }}><Sparkles size={18} /></span>
              <div><strong className="block text-lg font-black">知行循证</strong><span className="text-xs text-[#69837a]">LearnLoop · 看懂 · 记住 · 练会</span></div>
            </div>
            <div className="mb-5 text-xs text-[#0F6B50]"><a href="/review" className="underline underline-offset-4">先体验一次练习</a></div>

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
                {mode === "login" ? "继续上一次的学习进度。" : "注册后会先问你几道短问题，帮你找到适合自己的第一步；答案之后随时可以修改。"}
              </p>
            </div>

            <form onSubmit={submit} className="space-y-4">
              {mode === "register" && (
                <label className="block">
                  <span className="mb-1.5 block text-xs font-semibold text-[#5D6470]">称呼</span>
                  <span className="auth-input-shell flex items-center gap-2.5 rounded-xl border border-[#DDE1E7] px-3.5">
                    <UserRound size={17} className="text-[#959BA5]" />
                    <input required maxLength={80} autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} placeholder="怎么称呼你" className="min-w-0 flex-1 bg-transparent py-3.5 text-sm placeholder:text-[#A8ADB5]" />
                  </span>
                </label>
              )}

              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold text-[#5D6470]">邮箱</span>
                <span className="auth-input-shell flex items-center gap-2.5 rounded-xl border border-[#DDE1E7] px-3.5">
                  <Mail size={17} className="text-[#959BA5]" />
                  <input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" className="min-w-0 flex-1 bg-transparent py-3.5 text-sm placeholder:text-[#A8ADB5]" />
                </span>
              </label>

              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold text-[#5D6470]">密码</span>
                <span className="auth-input-shell flex items-center gap-2.5 rounded-xl border border-[#DDE1E7] px-3.5">
                  <LockKeyhole size={17} className="text-[#959BA5]" />
                  <input required minLength={8} maxLength={128} type={showPassword ? "text" : "password"} autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="至少 8 位" className="min-w-0 flex-1 bg-transparent py-3.5 text-sm placeholder:text-[#A8ADB5]" />
                  <button type="button" onClick={() => setShowPassword((visible) => !visible)} className="text-[#8B929C]" aria-label={showPassword ? "隐藏密码" : "显示密码"}>
                    {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </span>
              </label>

              {error && <div role="alert" className="rounded-xl border border-[#F0D0C5] bg-[#FFF5F1] px-3.5 py-3 text-sm leading-5 text-[#A0442C]">{error}</div>}

              <button disabled={submitting} className="primary-action flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3.5 text-sm font-bold disabled:cursor-wait disabled:opacity-60">
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
