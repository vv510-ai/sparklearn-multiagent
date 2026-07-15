TASK=video_script

请为知识点“{{kp}}”设计一段 60 秒、零基础也能听懂的讲解短视频分镜。

旁白顺序必须是：一句话结论 → 一个连贯生活类比 → 最小例子 → 正式概念还原 → 易错边界 → 记忆钩子。

画面只呈现资料中已有的对象、关系和步骤，不用装饰性画面冒充知识图。

只输出 JSON：

{"title":"...","narration":"完整旁白（220 字内）","scenes":[{"t":"0-10s","visual":"画面描述","caption":"屏幕字幕"}],"video_prompt":"English prompt for a clear educational animation"}

用户目标：{{goal}}

{{source_rules}}

{{beginner_rules}}

参考资料：
{{context}}
