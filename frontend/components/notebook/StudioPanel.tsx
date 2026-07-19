"use client";

import {
  AlertTriangle,
  BookMarked,
  BrainCircuit,
  ChartNoAxesColumn,
  ChevronRight,
  CircleHelp,
  CreditCard,
  FileText,
  FolderOpen,
  Headphones,
  Network,
  PlaySquare,
  Presentation,
  Route,
  Sparkles,
  Star,
  Table2,
} from "lucide-react";

type StudioPanelKey = "profile" | "path" | "resources" | "mistakes";

const GENERATORS = [
  {
    title: "互动讲解",
    desc: "边听边问，回答后继续",
    icon: Headphones,
    tone: "green",
    goal: "请根据最近的学习对话识别我此刻正在学的内容，整理成适合零基础学习者收听的短讲解：先用一句白话给结论，再讲一个最小例子和一个易错点。内容必须基于所选资料，方便我在播放中随时暂停提问。",
    kinds: ["doc"],
    template: "interactive_audio",
  },
  {
    title: "一图看懂",
    desc: "一张知识图串起整节课",
    icon: BrainCircuit,
    tone: "blue",
    goal: "请根据最近的学习对话和所选资料自动识别内容焦点，生成一图看懂：用一张横版知识图串起全局框架、学习主线、核心概念、运行机制、公式或代码、最小例子、易错点与记忆钩子；严格忠于所选资料并优先保证中文清晰可读。",
    kinds: ["doc"],
    template: "one_page",
  },
  {
    title: "框架导图",
    desc: "整合本次全部知识点",
    icon: Network,
    tone: "violet",
    goal: "请整合本次学习对话中出现的全部知识点：去重归类后，按照从基础到进阶的先修关系组织，并结合所选资料生成一张完整的框架导图。不要只围绕最后一个问题。",
    kinds: ["mindmap"],
    template: "framework",
  },
  {
    title: "学习笔记",
    desc: "定义、原理与步骤",
    icon: BookMarked,
    tone: "sand",
    goal: "请根据最近的学习对话和所选资料，自动识别需要整理的内容，生成结构清楚、适合复习的完整学习笔记。",
    kinds: ["doc"],
    template: "complete_notes",
  },
  {
    title: "易错易混",
    desc: "错误原因与概念对照",
    icon: AlertTriangle,
    tone: "rose",
    goal: "请根据最近的学习对话自动识别内容焦点，整理其中的易错知识点和易混淆概念，包含错误表现、原因、改法和对照表。",
    kinds: ["doc"],
    template: "error_confusion",
  },
  {
    title: "巩固测验",
    desc: "按薄弱点出题",
    icon: CircleHelp,
    tone: "cyan",
    goal: "请根据最近的学习对话自动识别内容焦点，结合学习者薄弱点和所选资料生成一组巩固测验。",
    kinds: ["quiz"],
    template: "quiz",
  },
  {
    title: "记忆闪卡",
    desc: "翻面回忆并标记掌握",
    icon: CreditCard,
    tone: "rose",
    goal: "请根据最近的学习对话和所选资料生成一组主动回忆闪卡，每张卡只检查一个最小知识点，覆盖定义、机制、步骤、边界与易错点。",
    kinds: ["flashcards"],
    template: "flashcards",
  },
  {
    title: "学习信息图",
    desc: "结论、过程与边界一图串起",
    icon: Sparkles,
    tone: "violet",
    goal: "请把最近的学习主题整理成一张来源约束的学习信息图：先给一句话结论，再按定义、结构、过程、边界组织视觉区块。",
    kinds: ["infographic"],
    template: "infographic",
  },
  {
    title: "知识数据表",
    desc: "对照、筛选并复制 CSV",
    icon: Table2,
    tone: "cyan",
    goal: "请把最近的学习主题和所选资料整理成知识数据表，突出可比较的概念、适用条件、核心步骤和易错提醒。",
    kinds: ["data_table"],
    template: "data_table",
  },
  {
    title: "复习PPT",
    desc: "明确需要时再生成",
    icon: Presentation,
    tone: "blue",
    goal: "请根据当前学习主题和所选资料生成一份约 8—10 页、结构清楚、适合考前复习的 PPT。只生成当前主题，不联网扩展；普通问答时不要自动生成。",
    kinds: ["ppt"],
    template: "review_ppt",
  },
  {
    title: "讲解视频",
    desc: "形成分镜与讲稿",
    icon: PlaySquare,
    tone: "green",
    goal: "请根据最近的学习对话自动识别内容焦点，生成一份简洁清楚的讲解视频脚本与可用的降级讲稿。",
    kinds: ["video"],
    template: "video",
  },
] as const;

const VIEWS = [
  { title: "学习画像", desc: "掌握度与错因", icon: ChartNoAxesColumn, tone: "indigo", panel: "profile" },
  { title: "知识关系", desc: "先修、解锁与顺序", icon: Route, tone: "emerald", panel: "path" },
  { title: "资料归档", desc: "继续上次的内容", icon: FolderOpen, tone: "slate", panel: "resources" },
  { title: "我的错题本", desc: "错因、收藏与随时重做", icon: Star, tone: "amber", panel: "mistakes" },
] as const;

export default function StudioPanel({
  onGenerate,
  onOpen,
  disabled = false,
}: {
  onGenerate: (label: string, goal: string, kinds: string[], template: string) => void;
  onOpen: (panel: StudioPanelKey) => void;
  disabled?: boolean;
}) {
  return (
    <div className="notebook-column studio-panel flex h-full min-h-0 flex-col" aria-label="学习工坊">
      <div className="notebook-column-header">
        <div>
          <div className="notebook-column-kicker">LEARNING STUDIO</div>
          <h2>学习工坊</h2>
        </div>
        <span className="studio-panel-heading-icon" aria-hidden>
          <FileText size={17} />
        </span>
      </div>

      <div className="studio-panel-body min-h-0 flex-1 overflow-y-auto p-3">
        <div className="grid grid-cols-2 gap-2">
          {GENERATORS.map((tool) => {
            const Icon = tool.icon;
            return (
              <button type="button" key={tool.title} disabled={disabled} onClick={() => onGenerate(tool.title, tool.goal, [...tool.kinds], tool.template)} className={`studio-tile is-${tool.tone} disabled:cursor-wait disabled:opacity-50`}>
                <span className="studio-tile-icon"><Icon size={18} /></span>
                <span className="studio-tile-content">
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
              <button type="button" key={item.title} disabled={disabled} onClick={() => onOpen(item.panel)} className={`studio-view is-${item.tone} disabled:cursor-wait disabled:opacity-50`}>
                <span className="studio-view-icon"><Icon size={17} /></span>
                <span className="min-w-0 flex-1 text-left">
                  <strong>{item.title}</strong>
                  <small>{item.desc}</small>
                </span>
                <ChevronRight size={16} className="studio-view-arrow" aria-hidden />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
