"use client";

import { ArrowLeft, ArrowUpRight, Play, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

type Course = {
  id: string;
  title: string;
  author: string;
  format: string;
  topics: string[];
  reason: string;
  note: string;
  verified_at?: string;
  source?: "curated_catalog" | "bilibili_search";
  watch_url: string;
  preview_url: string;
  platform: "bilibili" | "youtube";
  language: string;
  cover_url: string | null;
  duration_seconds: number | null;
  published_at: string | null;
  subtitle_status: string;
  metadata_checked_at?: string;
  metadata_notice?: string;
  chapters: {title: string; url: string; duration_seconds?: number}[];
};
type CourseResponse = {
  items: Course[];
  search_url: string;
  youtube_search_url: string;
  search_text: string;
  reason: string;
  notice: string;
  search_status?: "ok" | "unavailable" | "offline" | "not_requested";
  search_cached?: boolean;
  topics: { id: string; name: string }[];
};

export default function CourseRecommendations({
  initialKp = "",
  initialTopic = "",
  onBack,
  onAssess,
  notebookId = "",
}: {
  initialKp?: string;
  initialTopic?: string;
  onBack: () => void;
  onAssess: () => void;
  notebookId?: string;
}) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState("");
  const [kp, setKp] = useState(initialKp);
  const [data, setData] = useState<CourseResponse | null>(null);
  const [preview, setPreview] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setPreview("");
    apiGet<CourseResponse>(`/courses?${new URLSearchParams({ q: query, kp: query ? "" : kp, notebook_id: notebookId, platform, topic: query ? "" : initialTopic.trim().slice(0, 120) })}`)
      .then((response) => {
        if (active) setData(response);
      })
      .catch(() => {
        if (active) {
          setData(null);
          setError("课程加载失败，请重试，或使用上方的全站搜索。");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [query, kp, platform, initialTopic, retry, notebookId]);
  const searchText = query || (!loading && data?.search_text) || initialTopic.trim().slice(0, 120) || "公开课";
  const searchUrl = `https://search.bilibili.com/all?${new URLSearchParams({ keyword: searchText })}`;
  const youtubeUrl = `https://www.youtube.com/results?${new URLSearchParams({ search_query: searchText })}`;
  return (
    <div className="notebook-content-scroll course-panel" aria-busy={loading}>
      <div className="notebook-content-heading">
        <div>
          <span>WATCH · UNDERSTAND · PRACTISE</span>
          <h1>找你想学的课程</h1>
          <p>按主题、课程或老师搜索，不限当前书本。</p>
        </div>
        <button className="secondary-action" onClick={onBack}>
          <ArrowLeft size={15} />
          返回对话
        </button>
      </div>
      <div className="course-content">
        <div className="course-search-card">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setQuery(draft.trim());
              setKp("");
              setRetry((r) => r + 1);
            }}
          >
            <label className="sr-only" htmlFor="course-query">
              搜索课程
            </label>
            <Search size={19} />
            <input
              id="course-query"
              value={draft}
              maxLength={120}
              placeholder="例如：摄影入门、线性代数、Python、英语六级"
              onChange={(e) => setDraft(e.target.value)}
            />
            <button className="primary-action" type="submit">
              搜索
            </button>
          </form>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-2 whitespace-nowrap">
              视频来源
              <select className="!w-auto" value={platform} onChange={e => setPlatform(e.target.value)}>
                <option value="">全部来源</option>
                <option value="bilibili">B 站</option>
                <option value="youtube">YouTube · 已收录</option>
              </select>
            </label>
            <a href={searchUrl} target="_blank" rel="noopener noreferrer" className="secondary-action">B 站全站搜索 <ArrowUpRight size={14} /></a>
            <a href={youtubeUrl} target="_blank" rel="noopener noreferrer" className="secondary-action">YouTube 搜索 <ArrowUpRight size={14} /></a>
          </div>
          {!query && !!data?.topics.length && <details className="text-sm">
            <summary className="cursor-pointer text-emerald-800">按当前知识点筛选</summary>
            <label className="mt-3 block">
            当前知识点
            <select value={kp} onChange={(e) => setKp(e.target.value)}>
              <option value="">全部 · 按学习起点推荐</option>
              {data?.topics.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            </label>
          </details>}
        </div>
        <div className="course-reason">
          <span>{data?.reason || "从当前课程开始寻找讲解"}</span>
          <button onClick={onAssess}>
            完善起点测评 <ArrowUpRight size={14} />
          </button>
        </div>
        {!loading && data && <p className="mb-5 text-sm leading-6 text-slate-600" role="status">{data.notice}</p>}
        {error && (
          <p role="alert" className="entry-error">
            {error}
            <button onClick={() => setRetry((r) => r + 1)}>重试</button>
          </p>
        )}
        {loading ? (
          <p role="status" className="entry-loading">
            正在查找课程…
          </p>
        ) : data?.items.length ? (
          <div className="course-grid">
            {data.items.map((course, index) => (
              <article className="course-card" key={course.id}>
                {preview === course.id ? (
                  <div className="course-player">
                    <div className="course-player-bar">
                      <span>{course.platform === "youtube" ? "YouTube" : "B站"} 官方播放器</span>
                      <button
                        onClick={() => setPreview("")}
                        aria-label="关闭课程预览"
                      >
                        <X size={16} />
                      </button>
                    </div>
                    <iframe
                      src={course.preview_url}
                      title={`课程预览：${course.title}`}
                      allow="fullscreen; picture-in-picture"
                      allowFullScreen
                      referrerPolicy="strict-origin-when-cross-origin"
                    />
                    <p>
                      若未能播放，请使用下方来源链接。部分视频需要登录或受地区限制。
                    </p>
                  </div>
                ) : (
                  <button
                    className={`course-poster relative overflow-hidden tone-${index % 3}`}
                    onClick={() => setPreview(course.id)}
                    aria-label={`预览 ${course.title}`}
                  >
                    {course.cover_url && <img src={course.cover_url} alt={`${course.title} 视频封面`} loading="lazy" referrerPolicy="no-referrer" className="absolute inset-0 h-full w-full object-cover" onError={e=>{e.currentTarget.style.display="none";}}/>}
                    <span className="course-poster-label relative z-10 rounded-md bg-white/90 px-2 py-1 text-slate-800">
                      {course.format} · {course.platform === "youtube" ? "YOUTUBE" : "BILIBILI"}
                    </span>
                    {!!course.topics.length && <span className="course-poster-topic relative z-10 w-fit rounded-md bg-white/90 px-2 text-slate-800">
                      {course.topics.slice(0, 2).join(" / ")}
                    </span>}
                    <span className="course-play relative z-10">
                      <Play size={20} fill="currentColor" />
                      点击预览
                    </span>
                  </button>
                )}
                <div className="course-card-body">
                  <p className="course-author">{course.author}</p>
                  <h2>{course.title}</h2>
                  <p className="course-match">{course.reason}</p>
                  {course.note && <p className="course-description">{course.note}</p>}
                  <p className="my-3 text-xs leading-6 text-slate-600">
                    {course.duration_seconds ? `${Math.floor(course.duration_seconds / 3600)}小时${Math.floor(course.duration_seconds % 3600 / 60)}分` : "时长请见原站"}
                    {course.published_at && ` · ${course.published_at}`}
                    {course.language && ` · ${course.language}`}
                  </p>
                  {course.chapters?.length > 0 && <details className="mb-3 text-xs"><summary className="cursor-pointer font-semibold text-emerald-800">查看已收录章节（{course.chapters.length}）</summary><ol className="mt-2 max-h-60 space-y-2 overflow-auto">{course.chapters.map((c,i)=><li key={i}><a className="text-emerald-800 underline" href={c.url} target="_blank" rel="noopener noreferrer">{i+1}. {c.title}</a></li>)}</ol></details>}
                  <div className="course-card-footer">
                    <small>{course.source === "bilibili_search" ? (data.search_cached ? "B 站搜索 · 近期结果" : "B 站搜索结果") : `已收录 · ${course.verified_at || "原站信息"}`}</small>
                    <a
                      href={course.watch_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {course.platform === "youtube" ? "去 YouTube 观看" : "去 B 站观看"} <ArrowUpRight size={15} />
                    </a>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : error ? null : (
          <div className="course-empty">
            <Search size={28} />
            <h2>{data?.search_status === "unavailable" ? "暂时无法获取实时结果" : "暂未找到匹配课程"}</h2>
            <p>
              {data?.search_status === "unavailable" ? "可以使用上方的全站搜索，在原站继续查找" : "换个关键词，或使用上方的全站搜索继续查找"}“{searchText}”。
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
