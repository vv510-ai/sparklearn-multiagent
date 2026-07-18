TASK=video_script

请为知识点“{{kp}}”设计一段约 2 分钟、零基础也能跟上的讲解视频分镜；供应商生成的 10 秒概念动画只承载最关键画面，完整学习体验由六段分镜与连续旁白共同呈现。

旁白顺序必须是：一句话结论 → 一个连贯生活类比 → 最小例子的初始状态 → 逐步推演且每步解释原因 → 正式概念还原 → 易错边界 → 记忆钩子。不能默认学习者已经知道术语。

画面只呈现资料中已有的对象、关系和步骤，不用装饰性画面冒充知识图。

画面、字幕和旁白不得展示源码、伪代码、函数定义、程序语句或开发工具界面；把实现过程转成对象移动、状态变化和自然语言步骤。

只输出 JSON：

{"title":"...","narration":"完整旁白（650—820 字，短句、自然停顿、适合稍慢语速朗读）","scenes":[{"t":"0-20s","visual":"画面描述","caption":"屏幕字幕"}],"video_prompt":"English prompt for a clear 10-second educational concept animation showing the single most important visual"}

用户目标：{{goal}}

{{source_rules}}

{{beginner_rules}}

参考资料：
{{context}}
