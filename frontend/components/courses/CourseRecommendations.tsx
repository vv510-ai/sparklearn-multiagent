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
  verified_at: string;
  watch_url: string;
  preview_url: string;
};
type CourseResponse = {
  items: Course[];
  search_url: string;
  search_text: string;
  reason: string;
  notice: string;
  topics: { id: string; name: string }[];
};

export default function CourseRecommendations({
  initialKp = "",
  onBack,
  onAssess,
}: {
  initialKp?: string;
  onBack: () => void;
  onAssess: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
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
    apiGet<CourseResponse>(`/courses?${new URLSearchParams({ q: query, kp })}`)
      .then((response) => {
        if (active) setData(response);
      })
      .catch(() => {
        if (active) {
          setData(null);
          setError("课程资料库暂时无法读取。你仍可使用下面的 B 站全站搜索。");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [query, kp, retry]);
  const searchUrl =
    data?.search_url ||
    `https://search.bilibili.com/all?${new URLSearchParams({ keyword: query || "数据结构与算法 入门" })}`;
  return (
    <div className="notebook-content-scroll course-panel" aria-busy={loading}>
      <div className="notebook-content-heading">
        <div>
          <span>WATCH · UNDERSTAND · PRACTISE</span>
          <h1>找到适合这一步的网课</h1>
          <p>先试一道题，带着问题看，再合上视频做一道新题。</p>
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
            }}
          >
            <label className="sr-only" htmlFor="course-query">
              搜索课程资料库
            </label>
            <Search size={19} />
            <input
              id="course-query"
              value={draft}
              maxLength={120}
              placeholder="搜索知识点、课程或老师"
              onChange={(e) => setDraft(e.target.value)}
            />
            <button className="primary-action" type="submit">
              搜索
            </button>
          </form>
          <label>
            知识点
            <select value={kp} onChange={(e) => setKp(e.target.value)}>
              <option value="">全部 · 按学习起点推荐</option>
              {data?.topics.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="course-reason">
          <span>{data?.reason || "从当前课程开始寻找讲解"}</span>
          <button onClick={onAssess}>
            完善起点测评 <ArrowUpRight size={14} />
          </button>
        </div>
        {error && (
          <p role="alert" className="entry-error">
            {error}
            <button onClick={() => setRetry((r) => r + 1)}>重试</button>
          </p>
        )}
        {loading ? (
          <p role="status" className="entry-loading">
            正在匹配课程资料库…
          </p>
        ) : data?.items.length ? (
          <div className="course-grid">
            {data.items.map((course, index) => (
              <article className="course-card" key={course.id}>
                {preview === course.id ? (
                  <div className="course-player">
                    <div className="course-player-bar">
                      <span>B 站官方播放器</span>
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
                      若未能播放，请使用下方“去 B 站观看”；部分视频需登录或在 B
                      站内打开。
                    </p>
                  </div>
                ) : (
                  <button
                    className={`course-poster tone-${index % 3}`}
                    onClick={() => setPreview(course.id)}
                    aria-label={`预览 ${course.title}`}
                  >
                    <span className="course-poster-label">
                      {course.format} · BILIBILI
                    </span>
                    <span className="course-poster-topic">
                      {course.topics.slice(0, 2).join(" / ")}
                    </span>
                    <span className="course-play">
                      <Play size={20} fill="currentColor" />
                      点击预览
                    </span>
                  </button>
                )}
                <div className="course-card-body">
                  <p className="course-author">{course.author}</p>
                  <h2>{course.title}</h2>
                  <p className="course-match">{course.reason}</p>
                  <p className="course-description">{course.note}</p>
                  <div className="course-card-footer">
                    <small>公开页面核验于 {course.verified_at}</small>
                    <a
                      href={course.watch_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      去 B 站观看 <ArrowUpRight size={15} />
                    </a>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="course-empty">
            <Search size={28} />
            <h2>资料库中还没有对应课程</h2>
            <p>
              试试缩短关键词，或到 B 站继续搜索“
              {data?.search_text || query || "数据结构与算法"}”。
            </p>
          </div>
        )}
        <div className="course-external-search">
          <div>
            <h2>继续在 B 站找课程</h2>
            <p>打开实时搜索结果，自行比较讲解、目录与适用基础。</p>
          </div>
          <a
            href={searchUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="primary-action"
          >
            B 站全站搜索 <ArrowUpRight size={16} />
          </a>
        </div>
        <p className="entry-note">
          {data?.notice || "课程预览与观看服务由 B 站提供。"}
        </p>
      </div>
    </div>
  );
}
