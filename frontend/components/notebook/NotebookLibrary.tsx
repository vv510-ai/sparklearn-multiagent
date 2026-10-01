"use client";

import { BookOpen, LogOut, Plus, RefreshCw } from "lucide-react";
import type { LearningNotebook } from "@/lib/types";
import type { AuthUser } from "@/components/auth/AuthGate";


function notebookDate(value: string): string {
  if (!value) return "刚刚创建";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "最近更新";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}


export default function NotebookLibrary({
  user,
  notebooks,
  loading,
  error,
  openingId,
  onCreate,
  onOpen,
  onRefresh,
  onLogout,
}: {
  user: AuthUser;
  notebooks: LearningNotebook[];
  loading: boolean;
  error: string;
  openingId: string;
  onCreate: () => void;
  onOpen: (notebook: LearningNotebook) => void;
  onRefresh: () => void;
  onLogout: () => void;
}) {
  return (
    <main className="min-h-dvh bg-[#F4F5FA] text-[#242733]">
      <header className="sticky top-0 z-20 border-b border-[#E1E4EC] bg-white/90 backdrop-blur-xl">
        <div className="mx-auto flex h-[72px] w-full max-w-7xl items-center gap-3 px-4 sm:px-7">
          <span className="grid h-10 w-10 place-items-center rounded-2xl bg-[#0F6B50] text-white shadow-sm"><BookOpen size={20} /></span>
          <div className="min-w-0 flex-1">
            <div className="text-lg font-black tracking-tight">知行循证</div>
            <div className="text-[11px] text-[#7A8190]">我的科目书本</div>
          </div>
          <div className="hidden max-w-36 truncate text-sm font-semibold text-[#616978] sm:block" title={user.email}>{user.name}</div>
          <button type="button" onClick={onRefresh} disabled={loading} className="grid h-10 w-10 place-items-center rounded-full text-[#667080] transition hover:bg-[#F0F2F7] disabled:opacity-50" aria-label="刷新书本列表" title="刷新">
            <RefreshCw size={17} className={loading ? "animate-spin" : ""} />
          </button>
          <button type="button" onClick={onLogout} className="grid h-10 w-10 place-items-center rounded-full text-[#667080] transition hover:bg-[#F0F2F7]" aria-label="退出登录" title="退出登录"><LogOut size={17} /></button>
        </div>
      </header>

      <section className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-7 sm:py-12">
        <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-[11px] font-bold tracking-[0.2em] text-[#0F6B50]">NOTEBOOK LIBRARY</div>
            <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-4xl">选择一个科目，继续学习</h1>
            <p className="mt-2 text-sm leading-6 text-[#737B8B]">每本书拥有独立的资料、对话与学习产物，不会与其他科目混用。</p>
          </div>
          <button type="button" onClick={onCreate} className="inline-flex items-center gap-2 rounded-full bg-[#0F6B50] px-5 py-3 text-sm font-bold text-white shadow-[0_10px_28px_rgba(15,107,80,0.2)] transition hover:-translate-y-0.5 hover:bg-[#0B5C44]"><Plus size={18} />新建科目书本</button>
        </div>

        {error && <div className="mb-5 rounded-2xl border border-[#F1D6C9] bg-[#FFF6F1] px-4 py-3 text-sm text-[#9E4B2D]">{error}</div>}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <button type="button" onClick={onCreate} className="group flex min-h-[224px] flex-col items-center justify-center rounded-[24px] border-2 border-dashed border-[#CED4E1] bg-white/60 p-6 text-center transition hover:-translate-y-1 hover:border-[#84B9A7] hover:bg-white hover:shadow-[0_18px_45px_rgba(48,58,80,0.09)]">
            <span className="grid h-16 w-16 place-items-center rounded-full bg-[#EEF0F7] text-[#596171] transition group-hover:bg-[#E1F1EB] group-hover:text-[#0F6B50]"><Plus size={28} /></span>
            <strong className="mt-5 text-lg">Create new notebook</strong>
            <span className="mt-2 text-xs leading-5 text-[#858C9A]">为一门科目建立独立资料空间</span>
          </button>

          {notebooks.map((notebook) => (
            <button
              type="button"
              key={notebook.id}
              disabled={Boolean(openingId)}
              onClick={() => onOpen(notebook)}
              className="group relative flex min-h-[224px] flex-col rounded-[24px] border border-[#E1E4EC] bg-white p-6 text-left shadow-[0_2px_8px_rgba(32,39,55,0.04)] transition hover:-translate-y-1 hover:border-[#C9D7D1] hover:shadow-[0_18px_45px_rgba(48,58,80,0.1)] disabled:cursor-wait"
            >
              <span className="text-4xl" aria-hidden>{notebook.emoji || "📘"}</span>
              <strong className="mt-6 line-clamp-2 text-xl leading-7 tracking-tight text-[#242733]">{notebook.title}</strong>
              <span className="mt-auto pt-5 text-xs text-[#7C8492]">
                {openingId === notebook.id ? "正在打开…" : `${notebookDate(notebook.updated_at)} · ${notebook.source_count} 份资料`}
              </span>
              {notebook.message_count > 0 && <span className="mt-1 text-[11px] text-[#9AA0AB]">{Math.ceil(notebook.message_count / 2)} 轮学习对话</span>}
            </button>
          ))}
        </div>

        {!loading && notebooks.length === 0 && (
          <p className="mt-6 text-center text-sm text-[#858C9A]">还没有科目书本。先创建一本，再向里面添加讲义或笔记。</p>
        )}
      </section>
    </main>
  );
}
