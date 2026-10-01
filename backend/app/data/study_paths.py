"""Reviewed reading/assignment locations. Directions are not a question bank.

External originals stay with their publishers. IDs are stable progress keys;
substantive changes to an assignment require a new unit ID.
"""
VERSION = "2026-10-01-v1"


def unit(id, group, title, material, location, task, check, *, url="", minutes=25, sections=()):
    return dict(id=id, group=group, title=title, material_id=material, location=location,
                task=task, check=check, url=url, minutes=minutes, sections=list(sections))


CET6 = [
    unit("exam-map", "认识考试", "题型与时间安排", "cet6-format", "六级笔试内容结构", "查看四部分题型与考试时间，记录自己目前最想改善的一项。", "回到考试院原表核对；后面的时间是学习建议，不是考试规定。", minutes=10),
    unit("vocab-context", "词汇与句子", "在真题中理解词义", "cet6-202406-1", "Reading Comprehension · Section C 第一篇", "先通读第一篇阅读，记下影响理解的词及其题目位置，再回原句判断意思。", "结合上下文与词典核对；保留例句位置，明天遮住释义回忆。"),
    unit("word-class", "词汇与句子", "词性与搭配", "cet6-202406-1", "Reading Comprehension · Section A", "完成选词填空，逐空记录需要的词性与搭配依据。", "对照该套解析订正，区分词义不懂、词性判断错和搭配不熟。"),
    unit("sentence", "词汇与句子", "长句主干与修饰", "cet6-202406-2", "Reading Comprehension · Section C 第一篇", "选择妨碍理解的三个长句，标主干、从句和转折，写出整句含义。", "用上下句核对指代和逻辑，标出仍无法解释的位置。"),
    unit("paraphrase", "词汇与句子", "同义替换", "cet6-202406-2", "Reading Comprehension · Section C 题干与原文", "完成第一篇题目，将答案证据句与选项中的对应表达配对。", "依据原文和解析核对，不把词语相似直接当作意思一致。"),
    unit("listen-dialogue", "听力", "长对话：人物与目的", "cet6-archive", "2024年6月六级 · 对应试卷的长对话", "从原站选择同一考期的试卷和原音，先核对匹配，再完成长对话题。", "用同套听力原文与答案订正；若题序或内容不符，停止并更换配套资料。", minutes=30),
    unit("listen-detail", "听力", "长对话：细节与转折", "cet6-archive", "上一节同套长对话的错误题", "重听错题所在片段，记录否定、转折、时间和行动安排。", "对照听力原文定位漏听处，记录是没听清还是没理解。"),
    unit("listen-passage", "听力", "短文：主旨与结构", "cet6-archive", "2024年6月六级 · 同套听力篇章", "先不看文字稿完成篇章题，再按段落写下大意。", "对照该套原文和答案核对主旨与细节。", minutes=30),
    unit("listen-lecture", "听力", "讲座：观点与例证", "cet6-archive", "2024年6月六级 · 同套讲话、报道或讲座", "完成该部分题目，区分主要观点、原因与例子。", "根据原文核对答案的证据位置，不用合成音频代替原音。", minutes=30),
    unit("listen-replay", "听力", "精听订正与隔日复听", "cet6-archive", "此前错题对应的原音片段", "选三处错题，听写关键句，再跟随原音复读；第二天不看稿再听。", "记录仍听不出的词组，原题重做不当作新的测评成绩。"),
    unit("cloze", "阅读", "选词填空：句子与篇章", "cet6-202312-1", "Reading Comprehension · Section A", "独立完成整组选词填空，先填有把握的空，再结合篇章处理剩余项。", "按该套答案核对每空，写下至少一个判断依据。"),
    unit("matching-skim", "阅读", "长篇匹配：段落结构", "cet6-202312-1", "Reading Comprehension · Section B", "先读长篇各段，为每段写简短主题，再完成匹配题。", "核对答案及原文证据，区分主题相关和信息完全对应。", minutes=30),
    unit("matching-detail", "阅读", "长篇匹配：信息定位", "cet6-202312-2", "Reading Comprehension · Section B", "圈题干中的人物、时间和逻辑关系，在文中定位对应段落。", "对照解析订正，把关键词的同义表达记在错题旁。", minutes=30),
    unit("reading-evidence", "阅读", "仔细阅读：事实与证据", "cet6-202406-3", "Reading Comprehension · Section C 第一篇", "独立完成第一篇五题，每题标出支持所选答案的原句位置。", "核对原题解析；答对但找不到证据的题也加入复习。"),
    unit("reading-infer", "阅读", "仔细阅读：推断与态度", "cet6-202406-3", "Reading Comprehension · Section C 第二篇", "完成第二篇，检查涉及推断、观点的题目，记录选项比原文多说了什么。", "按原文及解析检查推断范围，不能只凭常识选答案。"),
    unit("reading-traps", "阅读", "仔细阅读：干扰项", "cet6-reading-explained-2", "原站模拟阅读题与详解", "先独立做题，再比较正确项与自己误选项的差别。", "使用机构解析归纳错误，明确这是模拟题。"),
    unit("reading-transfer", "阅读", "阅读专项：换题检查", "cet6-reading-explained-3", "原站模拟阅读题与详解", "不看解析完成一组新题，记录时间与需要回读的位置。", "核对答案，比较上次错误是否再次出现。"),
    unit("write-prompt", "写作", "审题与提纲", "cet6-202406-1", "Writing 原题", "阅读写作题目与字数要求，列出自己的观点、理由与例子。", "逐项检查是否回应题目要求，参考范文只作为表达参考。"),
    unit("write-draft", "写作", "独立完成一篇作文", "cet6-202406-1", "上一节 Writing 原题", "先不看范文完成初稿，保留全文与实际用时。", "核对任务、段落、衔接与语法，再对照机构参考范文修改。", minutes=30),
    unit("write-revise", "写作", "论证与语言修改", "cet6-202406-2", "Writing 原题及参考范文", "完成新题的提纲和一段论证，再检查理由与例子的关系。", "把自己的原稿与修改稿分别保留，记录修改原因。"),
    unit("write-timed", "写作", "限时写作与自查", "cet6-202406-3", "Writing 原题", "依照原题要求限时完成作文，最后留时间检查。", "对照题目与参考范文订正；自查不换算六级分数。", minutes=30),
    unit("translate-structure", "翻译", "信息单位与句子主干", "cet6-202312-1", "Translation 原题", "拆分中文信息单位，先译句子主干，再补修饰成分。", "对照机构参考译文核对信息是否遗漏，译法不只一种。"),
    unit("translate-link", "翻译", "时态与逻辑连接", "cet6-202312-2", "Translation 原题", "独立翻译全文，检查时间背景、主语和句间关系。", "对照参考译文，记录准确性问题和可替换表达。", minutes=30),
    unit("translate-expression", "翻译", "文化词语与表达", "cet6-202312-3", "Translation 原题", "完成翻译，标出不确定的文化词语和搭配。", "核对该套参考译文与词典，避免逐字拼接。", minutes=30),
    unit("translate-timed", "翻译", "限时段落翻译", "cet6-202406-1", "Translation 原题", "按考试该部分时间完成段落翻译，保存未经修改的初稿。", "按信息完整、语法和表达三项订正。", minutes=30),
    unit("paper-one", "整卷与复盘", "第一套限时练习", "cet6-202506-1", "整套题面；听力需另核对同套原音", "先确认题面、答案与原音配套，再分四部分完成整卷并记录实际用时。", "来源已提示音频可能存在标题问题；不能匹配时改用手头正版配套卷，不记录未完成的听力。", minutes=130),
    unit("paper-review", "整卷与复盘", "按错因回到专项", "cet6-202506-1", "上一节试卷的错误与不确定题", "把问题归到词汇、听辨、定位、推断或表达，选最集中的一类回看对应单元。", "订正时记录原题位置与依据，安排隔日复习。", minutes=40),
    unit("paper-two", "整卷与复盘", "第二套检查改进", "cet6-202506-2", "整套题面；先确认配套原音", "完成另一套未做过的试卷，比较用时和重复错因。", "核对机构答案，不把原始正确率直接换算为官方报道分。", minutes=130),
]

PYTHON = []
for i, (title, location, sections) in enumerate([
    ("函数、变量与输入输出", "Week 0 · Functions, Variables；Problem Set 0", ["numbers", "text", "defining-functions"]),
    ("条件判断", "Week 1 · Conditionals；Problem Set 1", ["if-statements", "more-on-conditions"]),
    ("循环与容器", "Week 2 · Loops；Problem Set 2", ["lists", "for-statements", "the-range-function"]),
    ("异常处理", "Week 3 · Exceptions；Problem Set 3", []),
    ("库与模块", "Week 4 · Libraries；Problem Set 4", []),
    ("单元测试", "Week 5 · Unit Tests；Problem Set 5", []),
    ("文件读写", "Week 6 · File I/O；Problem Set 6", []),
    ("正则表达式", "Week 7 · Regular Expressions；Problem Set 7", []),
    ("面向对象", "Week 8 · Object-Oriented Programming；Problem Set 8", []),
]):
    PYTHON.append(unit(f"week-{i}", "基础" if i < 3 else "进阶", title, "cs50-python-psets", location,
        "阅读对应周的官方课程，再从该周原题集中选一道题，按原题要求编写并运行程序。",
        "使用题目提供的测试方式核对；在下方记录题名、代码运行结果与失败用例。",
        url=f"https://cs50.harvard.edu/python/psets/{i}/", minutes=40, sections=sections))
PYTHON.append(unit("project", "综合练习", "完成原课程项目", "cs50-python", "Final Project", "按 CS50P Final Project 的要求选题、实现并编写测试。", "对照原课程提交要求自查，记录实际运行结果；本站保存记录，不替代代码评测。", minutes=60))

ALGO = []
for slug, title, chapter in [
    ("computational_complexity", "复杂度与递归", "第2章"), ("array_and_linkedlist", "数组与链表", "第4章"),
    ("stack_and_queue", "栈与队列", "第5章"), ("hashing", "哈希表", "第6章"), ("tree", "树与遍历", "第7章"),
    ("heap", "堆与优先队列", "第8章"), ("graph", "图与遍历", "第9章"), ("searching", "二分与搜索", "第10章"),
    ("sorting", "排序", "第11章"), ("divide_and_conquer", "分治", "第12章"), ("backtracking", "回溯", "第13章"),
    ("dynamic_programming", "动态规划", "第14章"), ("greedy", "贪心", "第15章")]:
    ALGO.append(unit(slug, "结构与基础" if len(ALGO) < 7 else "算法方法", title, "hello-algo", f"《Hello 算法》{chapter}及章末练习",
        "阅读本章，手动推演一个原书示例，运行对应代码，再完成章末练习中的一道原题。",
        "按书中讲解与练习提示核对，保存推演过程、边界情况或运行结果。",
        url=f"https://www.hello-algo.com/chapter_{slug}/", minutes=40))
ALGO.append(unit("mit-problems", "综合练习", "大学课程作业", "mit-algo-assignments", "MIT 6.006 Assignments：选择与已学主题对应的 Problem Set", "先读题目要求，独立完成一道相关题，再打开同题参考解答。", "逐步核对复杂度、证明和实现，MIT课程为英文且难度高于入门教材。", minutes=45))

CALCULUS = []
for group, title, path in [
    ("微分", "导数、极限与连续", "1.-differentiation/part-a-definition-and-basic-rules"),
    ("微分", "隐函数与反函数求导", "1.-differentiation/part-b-implicit-differentiation-and-inverse-functions"),
    ("导数应用", "近似与函数图像", "unit-2-applications-of-differentiation/part-a-approximation-and-curve-sketching"),
    ("导数应用", "最优化与相关变化率", "unit-2-applications-of-differentiation/part-b-optimization-related-rates-and-newtons-method"),
    ("导数应用", "中值定理与原函数", "unit-2-applications-of-differentiation/part-c-mean-value-theorem-antiderivatives-and-differential-equations"),
    ("积分", "定积分与基本定理", "unit-3-the-definite-integral-and-its-applications/part-a-definition-of-the-definite-integral-and-first-fundamental-theorem"),
    ("积分", "面积与体积", "unit-3-the-definite-integral-and-its-applications/part-b-second-fundamental-theorem-areas-volumes"),
    ("积分", "平均值与数值积分", "unit-3-the-definite-integral-and-its-applications/part-c-average-value-probability-and-numerical-integration"),
    ("积分方法", "三角代换", "unit-4-techniques-of-integration/part-a-trigonometric-powers-trigonometric-substitution-and-completing-the-square"),
    ("积分方法", "分部积分与部分分式", "unit-4-techniques-of-integration/part-b-partial-fractions-integration-by-parts-arc-length-and-surface-area"),
    ("积分方法", "参数方程与极坐标", "unit-4-techniques-of-integration/part-c-parametric-equations-and-polar-coordinates"),
    ("极限与级数", "洛必达法则与反常积分", "unit-5-exploring-the-infinite/part-a-lhospitals-rule-and-improper-integrals"),
    ("极限与级数", "泰勒级数", "unit-5-exploring-the-infinite/part-b-taylor-series"),
]:
    CALCULUS.append(unit(path.split('/')[-1], group, title, "mit-calculus", "MIT 18.01SC · 对应单元下的 Sessions 与 Problem Set",
        "打开该单元，逐节学习讲义和 Worked Examples，再独立完成同单元作业中的两道题。",
        "打开原课程对应 Solutions，逐行核对推导，记录最早出现分歧的一步。",
        url=f"https://ocw.mit.edu/courses/18-01sc-single-variable-calculus-fall-2010/pages/{path}/", minutes=45))
CALCULUS.append(unit("final-exam", "综合练习", "期末试卷与复盘", "mit-calculus-final", "Final Exam 与 Solutions", "先完成已学范围对应的题目，记录步骤和用时，再查看解答。", "原课程覆盖单变量微积分；未学内容留待后续，不算已完成。", minutes=60))

ENGLISH = [unit(slug, "A2 听力", title, "bc-listening", f"{en} · Preparation、Audio、Task 1 / Task 2",
    "先做 Preparation，再听原音并完成 Task 1 和 Task 2，最后展开 Transcript 精听。",
    "使用原站练习核对答案，记录一处听错的句子；次日不看稿再听。",
    url=f"https://learnenglish.britishcouncil.org/free-resources/listening/a2/{slug}")
    for slug,title,en in [("morning-briefing", "听懂工作安排", "A morning briefing"),
        ("invitation-party", "听懂邀请与路线", "An invitation to a party"),
        ("changing-meeting-time", "听懂时间变更", "Changing a meeting time")]]
ENGLISH.extend([
    unit("reading-friend", "A2 阅读", "读懂朋友的信息", "bc-reading", "A message to a new friend · Preparation、Reading text、Task 1 / Task 2", "先做准备练习，再读正文并独立完成两项任务。", "使用原站核对答案，把题目与正文的证据对应起来。", url="https://learnenglish.britishcouncil.org/free-resources/reading/a2/message-new-friend"),
    unit("daily-routine", "主题词汇", "日常活动与时间表达", "bc-vocabulary", "Daily routine vocabulary · 原站示例与六项练习", "阅读原站例句，完成词汇、时间与日常活动的配套练习。", "用原站答案核对，再不看例句描述自己的日常安排。", url="https://learnenglish.britishcouncil.org/free-resources/vocabulary/a1-a2/daily-routine-vocabulary-a1-beginner-english-vocabulary-lesson"),
    unit("jobs", "主题词汇", "职业词汇与发音", "bc-vocabulary", "Jobs 1 · 原站词汇活动与 Task 1–5", "听词汇发音，完成五项配套练习，再用学到的词语介绍一种工作。", "核对原站答案，记录拼写、发音或词义上的错误。", url="https://learnenglish.britishcouncil.org/free-resources/vocabulary/a1-a2/jobs-1"),
])


PATHS = {
    "cet6": dict(title="大学英语六级", subtitle="真题专项 → 整卷练习 → 错题复习", units=CET6),
    "python": dict(title="Python 编程", subtitle="官方教程与 CS50P 原题 · 需要自己运行代码", units=PYTHON),
    "ds_algo": dict(title="数据结构与算法", subtitle="中文教材 → 推演与实现 → 章末练习", units=ALGO),
    "calculus": dict(title="高等数学", subtitle="单变量微积分 · MIT 原讲义、作业与解答（英文）", units=CALCULUS),
    "english": dict(title="日常英语", subtitle="British Council 原声与配套练习 · 从 A2 开始", units=ENGLISH),
}
