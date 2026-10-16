"use client";

import StudyCoach, { type CoachAction } from "@/components/onboarding/StudyCoach";
import type { StudyStage } from "@/lib/learning-guidance";
import {
  AlertTriangle,
  BookMarked,
  BrainCircuit,
  ChartNoAxesColumn,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clapperboard,
  CreditCard,
  FileText,
  FolderOpen,
  Headphones,
  Music4,
  Network,
  PlaySquare,
  Presentation,
  Route,
  Sparkles,
  Star,
  Table2,
  Target,
} from "lucide-react";

type StudioPanelKey = "research" | "english" | "profile" | "path" | "resources" | "mistakes" | "assessment" | "courses";

/**
 * Every generator the workspace can start. The list is also used to resolve
 * suggestions and "next step" chips, so templates stay unique.
 */
export const GENERATORS = [
  {
    title: "讲解视频",
    desc: "小云雀概念动画 · 配套讲稿与语音讲解",
    icon: Clapperboard,
    tone: "green",
    goal: "请根据最近的学习对话识别我此刻正在学的内容，制作一段讲解视频：画面要和知识步骤一一对应，先讲直觉再讲机制，最后用一个例子和一个易错点收尾。",
    kinds: ["video"],
    template: "video",
  },
  {
    title: "一图看懂",
    desc: "复杂知识自动拆成 1~N 张图，逐张核对",
    icon: BrainCircuit,
    tone: "teal",
    goal: "请根据最近的学习对话和所选资料识别要讲的主题，生成“一图看懂”。一张图讲不清时合理拆成多张，确保内容全面、准确、直观易懂。",
    kinds: ["doc"],
    template: "one_page",
  },
  {
    title: "记忆歌曲",
    desc: "口诀 → 歌词 → AI 演唱，跟唱就能记住",
    icon: Music4,
    tone: "gold",
    goal: "请把最近学习的核心知识点编成口诀，再写成好记、准确的歌词，并由模型决定最适合记忆的曲风、节奏与演唱方式，生成一首记忆歌曲。",
    kinds: ["song"],
    template: "memory_song",
  },
  {
    title: "互动讲解",
    desc: "边听边问，回答后继续",
    icon: Headphones,
    tone: "green",
    goal: "请根据最近的学习对话识别我此刻正在学的内容，整理成适合零基础学习者收听的短讲解：先用一句白话给结论，再讲一个最小例子和一个易错点，方便我在播放中随时暂停提问。",
    kinds: ["doc"],
    template: "interactive_audio",
  },
  {
    title: "记忆闪卡",
    desc: "翻面回忆，按遗忘曲线复习",
    icon: CreditCard,
    tone: "rose",
    goal: "请根据最近的学习对话和所选资料生成一组主动回忆闪卡，每张卡只检查一个最小知识点，覆盖定义、机制、步骤、边界与易错点。",
    kinds: ["flashcards"],
    template: "flashcards",
  },
  {
    title: "框架导图",
    desc: "整合本次全部知识点",
    icon: Network,
    tone: "violet",
    goal: "请整合本次学习对话中出现的全部知识点：去重归类后，按从基础到进阶的先修关系组织，并结合所选资料生成一张完整的框架导图。不要只围绕最后一个问题。",
    kinds: ["mindmap"],
    template: "framework",
  },
  {
    title: "巩固测验",
    desc: "按薄弱点出新题",
    icon: CircleHelp,
    tone: "cyan",
    goal: "请根据最近的学习对话识别内容焦点，结合学习者的薄弱点和所选资料生成一组巩固测验。",
    kinds: ["quiz"],
    template: "quiz",
  },
  {
    title: "易错易混",
    desc: "错误原因与概念对照",
    icon: AlertTriangle,
    tone: "rose",
    goal: "请根据最近的学习对话识别内容焦点，整理其中的易错知识点和易混淆概念，包含错误表现、原因、改法和对照表。",
    kinds: ["doc"],
    template: "error_confusion",
  },
  {
    title: "学习笔记",
    desc: "定义、原理、步骤与例子",
    icon: BookMarked,
    tone: "sand",
    goal: "请根据最近的学习对话和所选资料，生成结构清楚、适合复习的完整学习笔记。",
    kinds: ["doc"],
    template: "complete_notes",
  },
  {
    title: "复习PPT",
    desc: "考前复习用的演示文稿",
    icon: Presentation,
    tone: "blue",
    goal: "请根据当前学习主题和所选资料生成一份约 8—10 页、结构清楚、适合考前复习的 PPT。只生成当前主题，不联网扩展。",
    kinds: ["ppt"],
    template: "review_ppt",
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
] as const;

type Generator = (typeof GENERATORS)[number];
type Template = Generator["template"];
const tool = (template: Template) => GENERATORS.find(item => item.template === template)!;

type ViewItem = { title: string; desc: string; icon: typeof Star; tone: string; panel: StudioPanelKey };

const STAGES: { index: number; title: string; hint: string; heroes: Template[]; tiles: Template[]; views: ViewItem[] }[] = [
  { index: 1, title: "看懂", hint: "先建立直觉与全局", heroes: ["video", "one_page"], tiles: ["interactive_audio"], views: [] },
  { index: 2, title: "记住", hint: "把要点变成记忆钩子", heroes: ["memory_song"], tiles: ["flashcards", "framework"], views: [] },
  { index: 3, title: "练会", hint: "独立作答才算会", heroes: [], tiles: ["quiz", "error_confusion"], views: [
    { title: "我的错题本", desc: "错因、收藏与随时重做", icon: Star, tone: "amber", panel: "mistakes" },
  ] },
  { index: 4, title: "复盘", hint: "沉淀成果，按时复习", heroes: [], tiles: ["complete_notes", "review_ppt"], views: [
    { title: "学习画像", desc: "掌握度、遗忘与错因", icon: ChartNoAxesColumn, tone: "indigo", panel: "profile" },
    { title: "知识关系", desc: "先修、解锁与下一步", icon: Route, tone: "emerald", panel: "path" },
    { title: "成果归档", desc: "生成过的图、视频、歌", icon: FolderOpen, tone: "slate", panel: "resources" },
  ] },
];

const MORE_VIEWS: ViewItem[] = [
  { title: "推荐网课", desc: "按知识点找课，先预览", icon: PlaySquare, tone: "emerald", panel: "courses" },
  { title: "深度研究", desc: "检索真实来源并对照证据", icon: Sparkles, tone: "indigo", panel: "research" },
  { title: "英语场景学习", desc: "影视字幕、词义与主动回忆", icon: Headphones, tone: "emerald", panel: "english" },
];

export default function StudioPanel({
  onGenerate,
  onOpen,
  disabled = false,
  stage = "start",
  sourceCount = 0,
  hasNotebook = false,
  courseKind = "",
  courseTitle = "",
  coachKey,
  onCoachAction,
}: {
  onGenerate: (label: string, goal: string, kinds: string[], template: string) => void;
  onOpen: (panel: StudioPanelKey) => void;
  disabled?: boolean;
  stage?: StudyStage;
  sourceCount?: number;
  hasNotebook?: boolean;
  courseKind?: string;
  courseTitle?: string;
  coachKey: string;
  onCoachAction: (action: CoachAction) => void;
}) {
  const englishCourse = courseKind === "cet6" || /英语|英文|雅思|托福|\b(?:english|ielts|toefl|cet[- ]?[46])\b/i.test(courseTitle);
  const run = (item: Generator) => onGenerate(item.title, item.goal, [...item.kinds], item.template);
  const view = (item: ViewItem) => {
    const Icon = item.icon;
    return (
      <button type="button" key={item.title} disabled={disabled} onClick={() => onOpen(item.panel)} className={`studio-view is-${item.tone} disabled:cursor-wait disabled:opacity-50`}>
        <span className="studio-view-icon"><Icon size={17} /></span>
        <span className="min-w-0 flex-1 text-left"><strong>{item.title}</strong><small>{item.desc}</small></span>
        <ChevronRight size={16} className="studio-view-arrow" aria-hidden />
      </button>
    );
  };
  return (
    <div className="notebook-column studio-panel flex h-full min-h-0 flex-col" aria-label="学习工坊">
      <div className="notebook-column-header">
        <div>
          <div className="notebook-column-kicker">LEARNING LOOP</div>
          <h2>学习工坊</h2>
        </div>
        <span className="studio-panel-heading-icon" aria-hidden>
          <FileText size={17} />
        </span>
      </div>

      <div className="studio-panel-body min-h-0 flex-1 overflow-y-auto p-3">
        <StudyCoach stage={stage} sourceCount={sourceCount} hasNotebook={hasNotebook} storageKey={coachKey} disabled={disabled} onAction={onCoachAction} />
        <div className="studio-learning-start">
          <button type="button" disabled={disabled} onClick={() => onOpen("assessment")}><span><Target size={20} /></span><span><strong>起点测评与计划</strong><small>找到起点，安排下一步</small></span><ChevronRight size={16} /></button>
        </div>

        {STAGES.map(stageItem => (
          <section key={stageItem.title} className="ll-stage" aria-label={`第 ${stageItem.index} 步：${stageItem.title}`}>
            <div className="ll-stage-head"><span className="ll-stage-index">{stageItem.index}</span><strong>{stageItem.title}</strong><small>{stageItem.hint}</small></div>
            {stageItem.heroes.map(template => {
              const item = tool(template);
              const Icon = item.icon;
              return (
                <button type="button" key={template} disabled={disabled} onClick={() => run(item)} className={`ll-hero-tile ${template === "memory_song" ? "is-song" : ""} disabled:cursor-wait disabled:opacity-60`}>
                  <span className="ll-hero-icon"><Icon size={20} /></span>
                  <span className="min-w-0"><strong>{item.title}{template === "memory_song" && <span className="ll-badge">NEW</span>}</strong><small>{item.desc}</small></span>
                  <ChevronRight size={18} aria-hidden />
                </button>
              );
            })}
            {stageItem.tiles.length > 0 && <div className="grid grid-cols-2 gap-2">
              {stageItem.tiles.map(template => {
                const item = tool(template);
                const Icon = item.icon;
                return (
                  <button type="button" key={template} disabled={disabled} onClick={() => run(item)} className={`studio-tile is-${item.tone} disabled:cursor-wait disabled:opacity-50`}>
                    <span className="studio-tile-icon"><Icon size={18} /></span>
                    <span className="studio-tile-content"><strong>{item.title}</strong><small>{item.desc}</small></span>
                  </button>
                );
              })}
            </div>}
            {stageItem.views.length > 0 && <div className="mt-2 space-y-2">{stageItem.views.map(view)}</div>}
          </section>
        ))}

        <details className="ll-more">
          <summary>更多工具<ChevronDown size={16} aria-hidden /></summary>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {(["data_table"] as Template[]).map(template => {
              const item = tool(template);
              const Icon = item.icon;
              return (
                <button type="button" key={template} disabled={disabled} onClick={() => run(item)} className={`studio-tile is-${item.tone} disabled:cursor-wait disabled:opacity-50`}>
                  <span className="studio-tile-icon"><Icon size={18} /></span>
                  <span className="studio-tile-content"><strong>{item.title}</strong><small>{item.desc}</small></span>
                </button>
              );
            })}
          </div>
          <div className="mt-2 space-y-2">{MORE_VIEWS.filter(item => item.panel !== "english" || englishCourse).map(view)}</div>
        </details>
      </div>
    </div>
  );
}
