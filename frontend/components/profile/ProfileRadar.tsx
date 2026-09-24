"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, EmptyState, Panel, PanelHeader, Stat, masteryTone } from "@/components/ui";
import { KP_NAME } from "@/lib/kp";
import type { StudentProfile } from "@/lib/types";

function asText(v: unknown, fallback = "未记录") {
  if (v == null || v === "") return fallback;
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  if (typeof v === "object") {
    const obj = v as Record<string, unknown>;
    const parts = [
      obj.daily_minutes != null ? `每日 ${obj.daily_minutes} 分钟` : null,
      obj.frequency ? `频率 ${obj.frequency}` : null,
      obj.focus ? `重点 ${obj.focus}` : null,
    ].filter(Boolean);
    if (parts.length) return parts.join(" / ");
  }
  return JSON.stringify(v);
}

function Radar({ data }: { data: { name: string; v: number }[] }) {
  const size = 220;
  const cx = size / 2;
  const cy = size / 2;
  const R = 78;
  const n = data.length;
  const pt = (i: number, r: number) => {
    const ang = (Math.PI * 2 * i) / n - Math.PI / 2;
    return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)] as const;
  };
  const poly = data.map((d, i) => pt(i, R * Math.max(0.04, d.v)).join(",")).join(" ");
  const rings = [0.33, 0.66, 1];

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="mx-auto block w-full max-w-[240px]">
      {rings.map((r) => (
        <polygon
          key={r}
          points={data.map((_, i) => pt(i, R * r).join(",")).join(" ")}
          fill="none"
          stroke="#dbe3ee"
          strokeWidth="1"
        />
      ))}
      {data.map((_, i) => {
        const [x, y] = pt(i, R);
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#dbe3ee" strokeWidth="1" />;
      })}
      <polygon points={poly} fill="rgba(15,107,80,.16)" stroke="#0F6B50" strokeWidth="1.8" />
      {data.map((d, i) => {
        const [x, y] = pt(i, R * Math.max(0.04, d.v));
        return <circle key={i} cx={x} cy={y} r="3" fill={d.v >= 0.8 ? "#059669" : d.v >= 0.5 ? "#0F6B50" : "#f97316"} />;
      })}
      {data.map((d, i) => {
        const [x, y] = pt(i, R + 20);
        return (
          <text key={i} x={x} y={y} textAnchor="middle" dominantBaseline="middle" fontSize="10.5" fill="#64748b">
            {d.name}
          </text>
        );
      })}
    </svg>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-slate-200 py-2 last:border-0">
      <span className="shrink-0 text-xs font-bold text-slate-500">{k}</span>
      <span className="truncate text-right text-xs font-medium text-slate-700">{v}</span>
    </div>
  );
}

export default function ProfileRadar({ profile }: { profile: StudentProfile | null }) {
  const prevMasteryRef = useRef<Record<string, number> | null>(null);
  const prevVersionRef = useRef<number | null>(null);
  const [deltas, setDeltas] = useState<Record<string, number>>({});
  const version = profile?._version ?? profile?.version ?? 0;

  const radar = useMemo(() => {
    const m = profile?.knowledge_mastery || {};
    return Object.entries(m)
      .sort((a, b) => a[1] - b[1])
      .slice(0, 6)
      .map(([k, v]) => ({ id: k, name: profile.knowledge_labels?.[k] || KP_NAME[k] || k, v: Number(v) }));
  }, [profile]);

  useEffect(() => {
    if (!profile) {
      prevMasteryRef.current = null;
      prevVersionRef.current = null;
      setDeltas({});
      return;
    }

    const mastery = profile.knowledge_mastery || {};
    const nextDeltas: Record<string, number> = {};
    const prev = prevMasteryRef.current;
    const versionChanged = prevVersionRef.current != null && prevVersionRef.current !== version;

    if (prev && versionChanged) {
      for (const kp of Object.keys(mastery)) {
        if (prev[kp] == null || mastery[kp] == null) continue;
        const delta = Math.round((Number(mastery[kp]) - Number(prev[kp])) * 100);
        if (delta !== 0) nextDeltas[kp] = delta;
      }
    }

    prevMasteryRef.current = { ...mastery };
    prevVersionRef.current = version;
    setDeltas(nextDeltas);
  }, [profile, version]);

  if (!profile) {
    return (
      <Panel className="p-5">
        <EmptyState title="暂无画像" desc="对话、生成资源或提交题组后，学习画像会在这里更新。" />
      </Panel>
    );
  }

  const pref = Object.entries(profile.resource_pref || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([k]) => ({ doc: "图文", video: "视频", quiz: "习题", mindmap: "脑图", code: "代码" }[k] || k))
    .join(" / ");
  const weakest = radar.slice(0, 2);
  const hasRadar = radar.length >= 3;

  return (
    <Panel className="p-4">
      <PanelHeader
        code={`PROFILE v${version}`}
        title="学习画像"
        desc="8 维画像随对话与答题实时更新;雷达展示最薄弱的 6 个知识点。"
        right={<Badge variant={Object.keys(deltas).length ? "info" : "neutral"}>{Object.keys(deltas).length ? "本轮已更新" : "实时同步"}</Badge>}
      />
      {hasRadar ? (
        <Radar data={radar} />
      ) : (
        <EmptyState className="py-8" title="画像维度不足" desc="继续答题后会生成完整雷达图。" />
      )}
      <div className="mt-2 grid grid-cols-2 gap-2">
        {weakest.map(item => <div key={item.id} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <Stat label={item.name} value={`${Math.round(item.v * 100)}%`} tone={masteryTone(item.v)} delta={deltas[item.id]} deltaUnit="%" />
        </div>)}
      </div>
      <div className="mt-2">
        <Row k="讲解偏好" v={({ "视觉型": "偏好图示（自述）", "语言型": "偏好文字（自述）", "动手型": "偏好操作（自述）" } as Record<string, string>)[asText(profile.cognitive_style)] || "尚未记录"} />
        <Row k="学习目标" v={asText(profile.goal)} />
        <Row k="学习节奏" v={asText(profile.pace, "常规节奏")} />
        <Row k="难度偏好" v={asText(profile.difficulty_pref, "循序渐进")} />
        <Row k="资源偏好" v={pref || "未记录"} />
        <Row
          k="错因标签"
          v={
            profile.error_prone?.length ? (
              <span className="text-orange-700">{profile.error_prone.slice(0, 3).join(" / ")}</span>
            ) : (
              "暂无错因"
            )
          }
        />
      </div>
    </Panel>
  );
}
