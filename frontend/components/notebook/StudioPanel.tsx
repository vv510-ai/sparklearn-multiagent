"use client";

import {
  AlertTriangle,
  BookMarked,
  BrainCircuit,
  ChartNoAxesColumn,
  CircleHelp,
  FileText,
  FolderOpen,
  Headphones,
  Network,
  PlaySquare,
  Route,
} from "lucide-react";

type StudioPanelKey = "profile" | "path" | "resources";

const GENERATORS = [
  {
    title: "互动讲解",
    desc: "边听边问，回答后继续",
    icon: Headphones,
    tone: "green",
    goal: "请把当前学习主题整理成适合零基础学习者收听的短讲解：先用一句白话给结论，再讲一个最小例子和一个易错点。内容必须基于所选资料，方便我在播放中随时暂停提问。",
    kinds: ["doc"],
    template: "interactive_audio",
  },
  {
    title: "一页看懂",
    desc: "先结论，再看框架",
    icon: BrainCircuit,
    tone: "blue",
    goal: "请把当前学习主题整理成一份一页看懂：先给直接结论，再给知识框架、核心步骤和三分钟回顾。",
    kinds: ["doc"],
    template: "one_page",
  },
  {
    title: "框架导图",
    desc: "从先修到后续",
    icon: Network,
    tone: "violet",
    goal: "请为当前学习主题生成一张基于知识图谱骨架和所选资料的框架导图。",
    kinds: ["mindmap"],
    template: "framework",
  },
  {
    title: "学习笔记",
    desc: "定义、原理与步骤",
    icon: BookMarked,
    tone: "sand",
    goal: "请根据当前问题和所选资料生成结构清楚、适合复习的完整学习笔记。",
    kinds: ["doc"],
    template: "complete_notes",
  },
  {
    title: "易错易混",
    desc: "错误原因与概念对照",
    icon: AlertTriangle,
    tone: "rose",
    goal: "请聚焦当前主题的易错知识点和易混淆概念，用错误表现、原因、改法和对照表整理。",
    kinds: ["doc"],
    template: "error_confusion",
  },
  {
    title: "巩固测验",
    desc: "按薄弱点出题",
    icon: CircleHelp,
    tone: "cyan",
    goal: "请根据当前学习主题、学习者薄弱点和所选资料生成一组巩固测验。",
    kinds: ["quiz"],
    template: "quiz",
  },
  {
    title: "讲解视频",
    desc: "形成分镜与讲稿",
    icon: PlaySquare,
    tone: "green",
    goal: "请为当前学习主题生成一份简洁清楚的讲解视频脚本与可用的降级讲稿。",
    kinds: ["video"],
    template: "video",
  },
] as const;

const VIEWS = [
  { title: "学习画像", desc: "掌握度与错因", icon: ChartNoAxesColumn, tone: "indigo", panel: "profile" },
  { title: "知识关系", desc: "先修、解锁与顺序", icon: Route, tone: "emerald", panel: "path" },
  { title: "资料归档", desc: "继续上次的内容", icon: FolderOpen, tone: "slate", panel: "resources" },
] as const;

export default function StudioPanel({
  onGenerate,
  onOpen,
}: {
  onGenerate: (goal: string, kinds: string[], template: string) => void;
  onOpen: (panel: StudioPanelKey) => void;
}) {
  return (
    <div className="notebook-column flex h-full min-h-0 flex-col" aria-label="学习工坊">
      <div className="notebook-column-header">
        <div>
          <div className="notebook-column-kicker">LEARNING STUDIO</div>
          <h2>学习工坊</h2>
        </div>
        <FileText size={18} className="text-[#747B88]" />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <div className="grid grid-cols-2 gap-2">
          {GENERATORS.map((tool) => {
            const Icon = tool.icon;
            return (
              <button key={tool.title} onClick={() => onGenerate(tool.goal, [...tool.kinds], tool.template)} className={`studio-tile is-${tool.tone}`}>
                <span className="studio-tile-icon"><Icon size={18} /></span>
                <span>
                  <strong>{tool.title}</strong>
                  <small>{tool.desc}</small>
                </span>
              </button>
            );
          })}
        </div>

        <div className="studio-divider"><span>持续学习</span></div>

        <div className="space-y-2">
          {VIEWS.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.title} onClick={() => onOpen(item.panel)} className={`studio-view is-${item.tone}`}>
                <span className="studio-view-icon"><Icon size={17} /></span>
                <span className="min-w-0 flex-1 text-left">
                  <strong>{item.title}</strong>
                  <small>{item.desc}</small>
                </span>
                <span aria-hidden>→</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
