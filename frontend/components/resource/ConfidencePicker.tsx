"use client";

export type ConfidenceLevel = "guess" | "unsure" | "confident";

const OPTIONS: { value: ConfidenceLevel; label: string; hint: string }[] = [
  { value: "guess", label: "在猜", hint: "只是试一试" },
  { value: "unsure", label: "有点把握", hint: "思路还不稳" },
  { value: "confident", label: "很确定", hint: "愿意据此判断" },
];

export function calibrationSignalText(signal?: string): string {
  if (signal === "confident_wrong") return "自信误判：优先复盘概念边界";
  if (signal === "uncertain_correct") return "答对但不稳：建议再做一次独立回忆";
  if (signal === "confident_correct") return "判断与结果一致";
  if (signal === "uncertainty_matched") return "不确定且答错：判断较准确，继续补知识";
  if (signal === "unsure_wrong") return "把握不足且答错：需要继续巩固";
  if (signal === "supported") return "本题使用了学习支持，信心仅作记录，不进入校准";
  return "";
}

export default function ConfidencePicker({
  value,
  onChange,
  disabled = false,
}: {
  value?: ConfidenceLevel;
  onChange: (value: ConfidenceLevel) => void;
  disabled?: boolean;
}) {
  return (
    <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs font-bold text-violet-900">提交前，你对这个答案有多大把握？</div>
          <div className="mt-0.5 text-[11px] text-violet-700">先记录当时判断，再获取提示或查看结果。</div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {OPTIONS.map((option) => {
            const selected = value === option.value;
            return (
              <button
                key={option.value}
                type="button"
                title={option.hint}
                disabled={disabled}
                onClick={() => onChange(option.value)}
                className={`rounded-md border px-2.5 py-1 text-[11px] font-bold transition ${
                  selected
                    ? "border-violet-500 bg-violet-600 text-white"
                    : "border-violet-200 bg-white text-violet-700 hover:border-violet-400"
                } disabled:cursor-not-allowed disabled:opacity-60`}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
