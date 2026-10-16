"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Download, ExternalLink, Maximize2, X } from "lucide-react";
import { apiAssetUrl } from "@/lib/api";
import type { OnePageVisualData } from "@/lib/types";

const STATUS = {
  passed: { label: "已核对", tone: "is-passed" },
  unverified: { label: "待核对", tone: "is-unverified" },
  failed: { label: "发现问题", tone: "is-failed" },
} as const;

/** Multi-picture 一图看懂: one request may come back as a reasoned set of pictures. */
export default function OnePageGallery({ visual }: { visual: OnePageVisualData }) {
  const images = (visual.images || []).filter(image => image.url);
  const [current, setCurrent] = useState(0);
  const [zoomed, setZoomed] = useState(false);
  const image = images[current];
  useEffect(() => {
    if (!zoomed) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setZoomed(false);
      if (event.key === "ArrowRight") setCurrent(index => Math.min(images.length - 1, index + 1));
      if (event.key === "ArrowLeft") setCurrent(index => Math.max(0, index - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomed, images.length]);
  if (!image) return null;
  const overall = STATUS[(visual.verification?.status || "unverified") as keyof typeof STATUS] || STATUS.unverified;
  const imageStatus = STATUS[(image.verification?.status || "unverified") as keyof typeof STATUS] || STATUS.unverified;
  const url = apiAssetUrl(image.url);
  const downloadAll = () => images.forEach((item, index) => {
    const link = document.createElement("a");
    link.href = apiAssetUrl(item.url) || item.url;
    link.download = `${visual.title || "一图看懂"}-${index + 1}.png`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  });
  return (
    <figure className="ll-gallery mb-4" aria-label={`${visual.title || "当前主题"}一图看懂，共 ${images.length} 张`}>
      <div className="ll-gallery-head">
        <div className="min-w-0">
          <div className="ll-gallery-kicker">一图看懂 · {images.length > 1 ? `共 ${images.length} 张` : "1 张"}</div>
          <h3 className="truncate">{visual.title || "知识图"}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`ll-status ${overall.tone}`} title="整组图的准确性与覆盖度核对结果">{overall.label}</span>
          <button type="button" className="secondary-action !min-h-[34px] !px-3 !py-1 text-xs" onClick={downloadAll}><Download size={14} />下载全部</button>
        </div>
      </div>
      <div className="ll-gallery-stage">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={`一图看懂${visual.title || ""} 第 ${current + 1} 张${image.title ? `：${image.title}` : ""}`} onClick={() => setZoomed(true)} />
        {images.length > 1 && <>
          <button type="button" className="ll-gallery-nav is-prev" aria-label="上一张" disabled={current === 0} onClick={() => setCurrent(index => Math.max(0, index - 1))}><ChevronLeft size={20} /></button>
          <button type="button" className="ll-gallery-nav is-next" aria-label="下一张" disabled={current === images.length - 1} onClick={() => setCurrent(index => Math.min(images.length - 1, index + 1))}><ChevronRight size={20} /></button>
        </>}
        <button type="button" className="ll-gallery-nav is-next" style={{ top: 26, transform: "none" }} aria-label="放大查看" onClick={() => setZoomed(true)}><Maximize2 size={17} /></button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[rgba(14,122,90,0.12)] px-4 py-3">
        <div className="min-w-0 text-sm font-bold text-[#0f241c]">第 {current + 1} 张{image.title ? ` · ${image.title}` : ""}</div>
        <span className={`ll-status ${imageStatus.tone}`}>{imageStatus.label}</span>
      </div>
      {!!image.verification?.issues?.length && image.verification.status !== "passed" && (
        <ul className="mx-4 mb-3 list-disc space-y-1 rounded-xl bg-[#fffaf0] py-2 pl-8 pr-3 text-xs leading-5 text-[#7a5310]">
          {image.verification.issues.map((issue, index) => <li key={index}>{issue}</li>)}
        </ul>
      )}
      {images.length > 1 && (
        <div className="ll-gallery-thumbs" role="tablist" aria-label="选择图片">
          {images.map((item, index) => (
            <button key={item.index} type="button" role="tab" aria-selected={index === current} aria-current={index === current} onClick={() => setCurrent(index)} title={item.title || `第 ${index + 1} 张`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={apiAssetUrl(item.url)} alt="" />
              <span>{index + 1}</span>
            </button>
          ))}
        </div>
      )}
      <figcaption className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-xs text-[#69837a]">
        <span>由 ChatGPT 按主题自动决定拆分张数；每张图经独立读图核对准确性，文字版见下方。</span>
        {visual.conversation_url && <a className="inline-flex items-center gap-1 text-[#0e7a5a] underline-offset-2 hover:underline" href={visual.conversation_url} target="_blank" rel="noreferrer">在 ChatGPT 中继续修改<ExternalLink size={12} /></a>}
      </figcaption>
      {zoomed && (
        <div className="ll-lightbox" role="dialog" aria-modal="true" aria-label="放大查看一图看懂" onClick={() => setZoomed(false)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={url} alt="" onClick={event => event.stopPropagation()} />
          <button type="button" aria-label="关闭放大" onClick={() => setZoomed(false)}><X size={20} /></button>
        </div>
      )}
    </figure>
  );
}
