"""Original CET-6 starter teaching material; not past papers or calibrated scores.

Exam facts are paraphrased from NEEA. All examples, passages and questions below
are authored for this course. Listening recordings use the same pinned scripts.
"""
from __future__ import annotations

import hashlib
import json

TITLE = "大学英语六级（CET-6）"
VERSION = "2026-09-v1"
OFFICIAL_URL = "https://cet.neea.edu.cn/html1/report/16123/201-1.htm"
GUIDE_URL = "http://47.121.24.54/courses/cet6-guide-v1.html"
BOUNDARY = "本站原创六级起点训练，非历年真题或完整模拟卷，不预测六级分数。听力使用合成英语音频；写作与翻译选择题只检查基础辨析，完整输出能力仍需实际写作与翻译任务核对。"
DESCRIPTION = "6 个训练模块，18 道起点题；含音频听力、阅读、写作与翻译训练"
ALIASES = {
    "cet6_vocab": ["六级词汇", "词汇", "单词", "同义改写"],
    "cet6_reading": ["六级阅读", "仔细阅读", "阅读理解", "阅读推断", "相关当因果", "相关与因果"],
    "cet6_matching": ["段落匹配", "长篇阅读", "匹配题"],
    "cet6_listening": ["六级听力", "听力", "听音频"],
    "cet6_writing": ["六级写作", "作文", "写作", "英文原稿"],
    "cet6_translation": ["六级翻译", "翻译", "汉译英"],
}

TOPICS = [
    ("cet6_vocab", "词汇与语境", "vocabulary", "根据词性、搭配与上下文选择词义，保留语气强弱"),
    ("cet6_reading", "仔细阅读与推断", "reading", "定位证据，区分事实、推断、相关与因果"),
    ("cet6_matching", "段落匹配与长篇阅读", "matching", "先概括段落功能，再用同义表达核对信息"),
    ("cet6_listening", "听力信息提取", "listening", "听英语音频，辨别主旨、转折与行动安排"),
    ("cet6_writing", "写作结构辨析", "writing", "检查论点、衔接与证据；另以短文训练实际表达"),
    ("cet6_translation", "翻译句法辨析", "translation", "辨析时态、逻辑与信息完整性；另以段落训练输出"),
]

LESSONS = {
    "cet6_vocab": """先读整句，再找空格需要的词性；最后检查搭配和上下文。不要只凭一个熟悉的中文释义选词。

例：The trial produced promising results, but further evidence is needed. promising 表示“有希望的”，不是已经证明有效；but 后面的限制必须保留。The policy may reduce waste 中的 may 也不能改写为 will certainly。

步骤：①圈出转折和因果词；②判断词性；③用候选词替换；④重读整句检查意义。每天从资料中挑 5 个词，记录原句、搭配和自己造的句子，隔天遮住释义回忆。记住词表不等于能在阅读中识别同义改写。

自练：用 substantial、sustainable、reluctant 各写一句话，解释为什么适合该语境。核对名词、动词与形容词的位置。""",
    "cet6_reading": """仔细阅读先找题干对应的证据句，再读前后句，特别检查转折、限定词和比较对象。推断只能比原文多走一小步。

例：Students who joined the reading club reported less stress. However, they had volunteered for the programme. 这里只观察到参加者报告压力较低；自愿加入意味着两组可能原本不同，不能据此断言社团导致减压，也不能推断所有学生都适用。

排除三类干扰：把 some 扩大为 all；把相关改成因果；把作者讨论的一种可能说成唯一解释。态度题要依据评价措辞，不凭个人赞成与否。限时训练之前先练“选项—证据句—排除理由”三列表。

自练：读一段英文科普，分别写一句主旨、一个可直接定位的事实和一个仍不能确定的结论。""",
    "cet6_matching": """长篇阅读匹配先快速扫读每段首尾句，给段落写功能标签，例如“问题、机制、例证、限制、方案”。随后以题干中的信息关系寻找同义表达。

例：[A] Food waste raises disposal costs. [B] A campus trial put smaller plates in the dining hall; waste fell during that week. [C] Staff warn that holiday attendance may explain part of the reduction. “对结果提出其他解释”对应 C；“描述一次具体干预”对应 B。出现相同单词不等于信息相同。

步骤：①读题干并标出人物、时间与关系；②找可能段落；③对照整条陈述，排除只匹配一半的段落；④保留证据句。本站用三段短材料练习这一过程，长度和压力不同于正式长篇阅读。

自练：给一篇英文文章逐段写 5–8 个英文词的标签，再把文章的三个事实分别定位到段落。""",
    "cet6_listening": """先看问题和选项，预测需要听什么：原因、态度、数字还是下一步行动。播放时记内容词和转折关系，不逐词翻译。

例：The original plan was to open on Monday. However, repairs mean that visitors must wait until Thursday. 问实际开放日，应抓 however 后的 Thursday，而不是最先听到的 Monday。听到听不懂的词先继续，避免错过后面的证据。

本课提供原创合成英语短音频。先完整听一遍再答；提交后查看文字稿和解析，再做一句一句的复听、跟读。音频故障时跳过，保留待测，不能把播放失败算成听不懂。合成短音频不能代表正式六级全部长对话、篇章与讲座表现。

自练：一次听音记录主旨和三个要点，随后对照文字稿，把问题归为词汇未知、语音未识别或推理偏差，再闭稿复听。""",
    "cet6_writing": """选择题只检查句子和段落辨析。真正写作需要亲自组织语言：先界定题目，再给中心观点，以理由和具体例子展开，最后回到问题。

例：Flexible library hours can help students with part-time jobs. A student who finishes work at eight may otherwise have no quiet place to study. 观点是开放时间的用途，例子解释为何有用。不要凭空编造“研究证明”或百分比；用清楚的假设性例子也能展开论证。

衔接要表达真实关系：however 表转折；therefore 需要前文能支持结论；for example 引出例证。承认限制后说明处理办法，比使用 always、everyone 等绝对词更准确。检查主谓一致、句子边界和代词指代。

输出练习（本站练习长度，不是考试评分）：写 120–150 词，讨论大学是否应该提供安静的协作学习空间。自查：是否回应题目、是否有明确观点、理由是否展开、例子是否具体、是否有一句考虑限制。把原稿交给小知逐句反馈后自己改写；选择题答对不代表整篇作文达标。""",
    "cet6_translation": """汉译英先提取信息单位：谁、做什么、何时、为什么。先保证主干完整，再处理定语、状语和连接关系；不要逐字拼接。

例：“近年来，这座城市改善了公共交通，使居民出行更加方便。”可译为 In recent years, the city has improved its public transport, making travel more convenient for residents. has improved 对应持续到现在的近期变化；making 连接结果。也可拆成两句，只要关系和信息保留。

核对四件事：①主语和谓语；②时间与时态；③否定、数量和逻辑关系；④地名、文化概念是否准确。不要增加原文没有的最高级、保证或因果。多种译法可以同时成立，参考译文并非唯一答案。

输出练习：把“近年来，越来越多的大学向公众开放图书馆。读者不仅可以借阅图书，还可以参加文化活动。这些服务有助于促进终身学习。”译成英文。先标三个信息单位再翻译，自查现在完成时是否合适、not only… but also…是否平行、是否保留了‘有助于’的语气。提交原稿给小知说明信息遗漏和可选表达，再自行修订。""",
}

# Each row starts with the correct option. _question rotates positions so the
# interface never teaches an answer-position pattern. These are original items.
ITEMS = {
"cet6_vocab": [
    ("The measure is intended to alleviate pressure on local hospitals. alleviate 最接近：", ["reduce", "measure", "transfer", "ignore"], "alleviate 是减轻；这里减轻医院承受的压力，不是测量或忽视压力。"),
    ("A feasible solution must work with the money and staff available. feasible 指：", ["practical", "expensive", "popular", "temporary"], "预算和人员限制说明方案必须可实施，未必昂贵、受欢迎或临时。"),
    ("Which expression preserves the caution in 'The change may improve access'?", ["The change could make access easier.", "The change will certainly solve every access problem.", "The change has already improved access everywhere.", "The change cannot affect access."], "may 和 could 都保留可能性；其他选项擅自增加确定性、已发生事实或否定。"),
    ("The committee was reluctant to approve a plan without cost estimates. reluctant 表示：", ["unwilling", "unable to read", "eager", "officially required"], "缺少成本估计使委员会不愿批准，不等于没有能力或受到命令。"),
    ("The two accounts are inconsistent: one says ten people attended, the other says twenty. inconsistent 指：", ["not in agreement", "equally detailed", "both confidential", "written together"], "人数描述冲突，说明两份叙述不一致。"),
    ("The grant enabled the team to purchase equipment. enabled 最接近：", ["made it possible for", "prevented", "forced", "reminded"], "资助让购买设备成为可能；不表示强迫购买。"),
    ("The sample is too small to yield a reliable conclusion. yield 在此指：", ["produce", "surrender", "delay", "replace"], "yield a conclusion 指产生结论；要根据搭配选择词义。"),
    ("The new design is more economical because it uses less fuel. economical 指：", ["saving resources", "related only to national trade", "very large", "recently invented"], "uses less fuel 提供语境，economical 在此指节省资源。"),
    ("Attendance declined despite the advertising campaign. 哪项保留原意？", ["Fewer people came although the event was advertised.", "More people came because of advertising.", "Nobody saw the advertisements.", "The campaign was cancelled."], "despite 是让步，declined 指减少；原文没有说没人看广告或活动取消。"),
    ("A substantial proportion of respondents preferred evening classes. substantial 表示：", ["considerable", "exactly half", "negligible", "unchanging"], "substantial 是相当大的，但不给出精确比例。"),
    ("The results are preliminary and require further testing. preliminary 指：", ["initial", "final", "irrelevant", "fabricated"], "仍需测试说明是初步结果，不意味着造假或毫无关系。"),
    ("A sustainable policy can continue without exhausting its resources. sustainable 强调：", ["long-term viability", "immediate popularity", "zero cost", "rapid expansion"], "资源不被耗尽支持可持续的长期运作，不保证零成本或快速增长。"),
],
"cet6_reading": [
    ("A survey found that regular cyclists reported better sleep. The researchers did not assign anyone to cycle. What can be concluded?", ["Cycling and reported sleep quality were associated in this sample.", "Cycling certainly caused better sleep.", "All cyclists sleep well.", "Non-cyclists cannot improve their sleep."], "观察性调查支持样本中的相关关系，不能排除其他因素并确认因果。"),
    ("Online meetings reduce travel costs. Yet teams may miss informal conversations that generate ideas. What is the main point?", ["Online meetings offer savings but involve a trade-off.", "Online meetings should always replace office work.", "Travel costs have no effect on organisations.", "Ideas only emerge during travel."], "前后两句同时给出收益和代价，yet 引导限制。"),
    ("The author calls the trial 'encouraging but too small to justify a national policy'. The attitude is：", ["cautiously positive", "completely dismissive", "unconditionally supportive", "unconcerned"], "encouraging 表示肯定，but 后限制证据强度，体现谨慎乐观。"),
    ("A town extended bus services on weekends. Passenger numbers rose, but petrol prices also increased. Which claim goes beyond the evidence?", ["The extended service alone caused the entire increase.", "Passenger numbers increased.", "Petrol prices increased.", "More than one factor could be relevant."], "alone 和 entire 排除了其他可能因素，原文没有提供这种因果证据。"),
    ("Researchers tested a reminder app with volunteers at one university. Why should its results be applied cautiously?", ["The participants may not represent other populations.", "Volunteers always provide false answers.", "Apps cannot change behaviour.", "University research is never useful."], "单校自愿样本的代表性有限，不能推断所有志愿者不诚实或研究无用。"),
    ("The archive will digitise rare books first because fragile pages make physical access risky. Why are rare books prioritised?", ["Digital access can reduce handling of fragile originals.", "They are the easiest books to sell.", "All modern books are already online.", "Visitors dislike printed books."], "because 后明确说明纸页脆弱、实体使用存在风险。"),
    ("Although the device is cheap to buy, replacing its batteries frequently is costly. What does the writer suggest considering?", ["Costs over the device's lifetime", "Only its purchase price", "The colour of its packaging", "The price of unrelated devices"], "购买便宜与后续电池费用高形成对比，应考虑总使用成本。"),
    ("Some participants completed the course faster after using the tool. Their final test scores, however, did not improve. Which statement is supported?", ["Faster completion did not coincide with higher scores here.", "Everyone learned more with the tool.", "The tool made all students perform worse.", "Test scores were not collected."], "区分效率与学习结果，原文只说部分人更快且最终分数未提高。"),
    ("The article first describes urban heat, then explains reflective roofs as one possible response. The second part mainly：", ["presents a potential remedy", "denies the initial problem", "provides an unrelated biography", "proves that no alternatives exist"], "文章从问题转向一种应对方案，one possible 不排除其他方案。"),
    ("The museum offers free entry on Fridays, except during special exhibitions. Which visitor is guaranteed free entry by this rule?", ["A visitor on a Friday with no special exhibition", "Every visitor on every Friday", "Anyone attending a special exhibition", "A visitor on any weekday"], "except 限制周五免费规则，只有排除特别展览的周五符合给定条件。"),
    ("A writer praises the plan's clear aims but asks how progress will be measured. What is the unresolved issue?", ["How to evaluate whether the aims are achieved", "Whether the plan has any aims", "Who printed the report", "Whether all measurement is impossible"], "明确目标已经获得肯定，尚待解决的是评估达成情况。"),
    ("Most surveyed workers wanted flexibility; a minority preferred fixed hours. What would distort the finding?", ["Every worker wants flexible hours.", "Preferences differed among respondents.", "Flexibility was preferred by the majority surveyed.", "Some respondents favoured fixed hours."], "从 most 到 every 是过度概括，还把调查样本扩大为所有劳动者。"),
],
"cet6_matching": [
    ("[A] The town faces rising summer temperatures. [B] Trees cool streets through shade and evaporation. [C] A pilot planted trees beside two schools.\nWhich paragraph explains a mechanism?", ["B", "A", "C", "None"], "B 说明树如何降温；A 是问题，C 是具体行动。"),
    ("[A] A library introduced online booking. [B] Users without internet access found booking difficult. [C] Staff added telephone reservations.\nWhere is an access barrier described?", ["B", "A", "C", "All three"], "B 说明没有网络的用户受到阻碍；C 提供补救。"),
    ("[A] Refill stations aim to reduce plastic waste. [B] At one campus, students returned bottles at collection points. [C] Reliable cleaning is necessary for expansion.\nWhich paragraph states a condition for scaling up?", ["C", "A", "B", "None"], "C 的 necessary for expansion 明确给出推广所需条件。"),
    ("[A] Food scraps add to disposal costs. [B] The dining hall offered smaller portions. [C] The trial's short duration limits firm conclusions.\nWhere is a limitation of the evidence?", ["C", "A", "B", "All three"], "C 的 short duration 和 limits 指证据局限。"),
    ("[A] Volunteers helped residents complete digital forms. [B] Digital exclusion affects access to services. [C] Funding for the programme remains uncertain.\nWhich paragraph describes direct assistance?", ["A", "B", "C", "None"], "A 具体描述志愿者帮助填写表格。"),
    ("[A] Researchers counted birds in spring. [B] The same sites were revisited in autumn. [C] Counts differed between the two seasons.\nWhich paragraph reports a result?", ["C", "A", "B", "None"], "A、B 是过程；C 是两季计数不同的结果。"),
    ("[A] Electronic labels cost more initially. [B] They can be updated without replacing paper. [C] Savings depend on how often prices change.\nWhere is a benefit explained?", ["B", "A", "C", "None"], "B 说明免换纸即可更新；C 是收益成立的条件。"),
    ("[A] The city repaired a disused railway. [B] It became a walking route linking several neighbourhoods. [C] Similar routes are planned elsewhere.\nWhich paragraph describes a future proposal?", ["C", "A", "B", "All three"], "planned elsewhere 对应未来提议；另外两段描述已发生的变化。"),
    ("[A] Screens can distract readers. [B] Notifications interrupt concentration. [C] One student disabled alerts while reading.\nWhich paragraph offers an individual example?", ["C", "A", "B", "None"], "One student 引入具体个人例子。"),
    ("[A] Some classes use group projects. [B] Supporters say they build cooperation. [C] Critics worry that contributions are unequal.\nWhere is an objection raised?", ["C", "A", "B", "None"], "Critics worry 引导反对意见，内容是贡献不均。"),
    ("[A] Repair cafes bring tools and volunteers together. [B] Visitors learn to mend household objects. [C] Organisers must find a permanent venue.\nWhich paragraph identifies an organisational challenge?", ["C", "A", "B", "All three"], "寻找固定场地是组织实施面临的具体困难。"),
    ("[A] Water meters record consumption. [B] Real-time displays let households spot unusual use quickly. [C] Devices need regular maintenance.\nWhich paragraph links information speed with a user benefit?", ["B", "A", "C", "None"], "real-time 与 quickly 明确关联即时信息和及时发现异常的好处。"),
],
"cet6_writing": [
    ("Choose the clearest thesis for an essay about university volunteering.", ["Universities should offer flexible volunteering opportunities so students can contribute without neglecting coursework.", "Volunteering is a word with many letters.", "Everything in society is always good.", "This essay has several sentences."], "中心论点应直接回应题目并给出可展开的立场与理由。"),
    ("Which sentence best supports 'Quiet study rooms help students who share crowded homes'?", ["They provide a place where those students can read without frequent interruptions.", "Libraries have existed for centuries.", "Some buildings have red walls.", "All students get perfect marks in quiet rooms."], "支持句要解释观点中的机制，不能转移话题或承诺完美成绩。"),
    ("The service is convenient. ___, it excludes people without smartphones. Choose the logical connector.", ["However", "Therefore", "For example", "Similarly"], "方便与排斥部分用户构成转折，不能用因此或例如替代。"),
    ("Which revision avoids an unsupported absolute claim: 'Online courses always meet everyone's needs'?", ["Online courses can meet some learners' needs when suitable support is available.", "All online courses are perfect.", "No learner ever needs support.", "Everyone certainly learns at the same pace."], "can、some 和条件限制让表达与可能证据的范围一致。"),
    ("Choose the grammatically complete sentence.", ["Although the project was expensive, it improved access.", "Although the project was expensive.", "The project expensive access.", "Because improved access."], "although 从句需要主句，第一项提供完整结构。"),
    ("A paragraph argues that practical workshops help learning. Which detail best develops this point?", ["Students apply a concept, observe the result, and correct mistakes during the workshop.", "Workshops are spelled with nine letters.", "There are many buildings on campus.", "Learning is important, important, and important."], "展开需要解释如何帮助学习，而不是重复空泛判断。"),
    ("Choose the sentence with subject–verb agreement.", ["The benefits of regular revision are clear.", "The benefits of regular revision is clear.", "The benefit of regular revision are clear.", "The benefits of regular revision be clear."], "主语中心词 benefits 是复数，应与 are 搭配。"),
    ("An essay supports shared bikes but recognises maintenance costs. Which response best addresses that limitation?", ["A maintenance budget and regular inspections could reduce the problem.", "Costs do not exist.", "All transport problems will disappear.", "The colour of bikes proves the policy works."], "承认限制并提出相关可行措施，不能否认问题或许诺万能。"),
    ("Which conclusion follows an essay about teaching source evaluation?", ["Teaching students to check evidence and authorship can support more informed use of information.", "In conclusion, a completely unrelated sport is exciting.", "Thus all online information must be true.", "Therefore students never need to read sources."], "结尾应综合已讨论的中心观点，避免跳到无关主题或相反结论。"),
    ("Which use of evidence is responsible in an essay without research data?", ["Use a clearly hypothetical example to explain a possible benefit.", "Invent a university study and a precise percentage.", "Claim all experts agree without a source.", "Present a guess as a measured national result."], "假设例子可以说明机制，但不能冒充真实数据或研究。"),
    ("Choose the clearest revision of 'The tutor spoke to the student after she submitted the draft' when the student submitted it.", ["After the student submitted the draft, the tutor spoke to her.", "She spoke to her after she submitted it.", "The tutor submitted it, although the student did.", "The draft spoke to the tutor."], "明确主语 student 后再用代词，消除 she 指代谁的歧义。"),
    ("Which sentence uses parallel structure?", ["The course aims to improve reading, develop listening skills, and build confidence.", "The course aims to improve reading, listening skills, and confidence was built.", "The course aims improving reading and to listening.", "The course aims to reading, listens, and confident."], "三个并列动词短语 improve、develop、build 保持结构一致。"),
],
"cet6_translation": [
    ("“近年来，这座城市改善了公共交通。”哪项保留时间与主要信息？", ["In recent years, the city has improved its public transport.", "The city will never improve its public transport.", "The city had no public transport in ancient times.", "Public transport improved every city centuries ago."], "in recent years 与 has improved 表示近年到现在的变化，主语和动作准确。"),
    ("“这项措施有助于减少浪费。”最贴切的表达是：", ["This measure helps reduce waste.", "This measure completely eliminates all waste.", "This measure causes more waste.", "This measure has nothing to do with waste."], "有助于不等于彻底消除，注意语气强度。"),
    ("“虽然距离很远，他们仍定期回乡。”哪项逻辑准确？", ["Although they live far away, they return to their hometown regularly.", "Because they live nearby, they never return.", "They return only because the distance is short.", "They have stopped returning to their hometown."], "although 保留让步，regularly 对应定期，不能改变频率或否定。"),
    ("“这座桥建于二十世纪初。”选择合适译法。", ["The bridge was built in the early twentieth century.", "The bridge builds the early twentieth century.", "The bridge will be built last century.", "The bridge has built a century."], "桥是被建造对象，明确过去时间使用一般过去时被动。"),
    ("“越来越多的人选择骑自行车上班。”哪项准确？", ["An increasing number of people choose to cycle to work.", "All people have stopped going to work.", "Fewer people are choosing to cycle to work.", "People only cycle at work."], "an increasing number 对应越来越多，to work 表示上班目的地。"),
    ("“除了借书，读者还可以参加讲座。”哪项保留补充关系？", ["In addition to borrowing books, readers can attend lectures.", "Instead of reading, nobody attends lectures.", "Readers must attend lectures before any book exists.", "Readers cannot borrow books or attend lectures."], "in addition to 表补充，can 保留可以而非强制。"),
    ("“这个项目旨在保护传统技艺。”最恰当的译法是：", ["The project aims to preserve traditional skills.", "The project has already preserved every traditional skill.", "The project prevents people from learning any skill.", "Traditional skills aim to remove the project."], "aims to 表目标，不等于已实现全部保护。"),
    ("“随着技术的发展，远程工作变得更加普遍。”哪项准确？", ["As technology develops, remote work is becoming more common.", "Technology develops only when everyone works remotely.", "Remote work has become impossible despite technology.", "Technology is more common than every worker."], "as 连接发展过程，更加普遍是趋势，不是所有人都已远程工作。"),
    ("“游客应尊重当地的风俗习惯。”哪项正确？", ["Visitors should respect local customs.", "Visitors should respect local customers only.", "Local customs should visit the tourists.", "Visitors never need to respect customs."], "customs 是风俗；customers 是顾客，形近词不能混淆。"),
    ("“政府不仅改善了住房条件，还增加了公共空间。”哪项完整？", ["The government has not only improved housing conditions but also created more public spaces.", "The government improved housing but removed every public space.", "Housing conditions have not improved.", "The government only considered public spaces."], "not only… but also…连接两项实际行动，保留不仅而且。"),
    ("“如果提前预约，参观者就可以避免长时间等待。”哪项保留条件？", ["If visitors book in advance, they can avoid long waits.", "Visitors never need to book and always avoid waiting.", "Visitors must wait longer because they booked.", "If visitors wait, every booking is cancelled."], "if 说明条件，can 说明可能获得的便利，不能删掉条件改成总是。"),
    ("“这种变化反映了公众对环境保护日益增长的关注。”哪项信息完整？", ["This change reflects growing public concern about environmental protection.", "This change proves that all environmental problems have been solved.", "The public is increasingly indifferent to environmental protection.", "Environmental protection changes every member of the public."], "reflects 是反映，growing concern 是日益关注，不代表环境问题已解决。"),
],
}

# Scripts deliberately remain out of active-question API responses.
LISTENING = [
    ("The study centre was due to open on Monday. However, repairs to the entrance are taking longer than expected. It will now open on Thursday. Students can still use the online catalogue while the building is closed.", "When will the study centre open?", ["Thursday", "Monday", "Tuesday", "Friday"], "however 后把原定 Monday 改为 Thursday。"),
    ("Our survey has enough responses from first-year students, but very few from those in their final year. Before we write the report, we need to contact the final-year classes. Otherwise, our conclusions may not reflect the whole university.", "What should the team do next?", ["Contact final-year classes", "Publish the report immediately", "Remove first-year responses", "Stop the survey permanently"], "Before we write the report 后提出下一步：联系毕业年级，补充代表性。"),
    ("The speaker is pleased that the new bus route connects the hospital with the station. She is less satisfied with the service in the evening, when buses run only once an hour. She recommends keeping the route but increasing evening departures.", "What does the speaker recommend?", ["More evening buses on the existing route", "Closing the route", "Moving the hospital", "Reducing daytime services"], "保留线路并增加晚间班次；不是取消线路或搬医院。"),
    ("The history lecture has moved from room twelve to room twenty because more students registered than expected. The starting time remains two o'clock. Please check the new room before inviting your classmates.", "Why was the lecture moved?", ["More students registered than expected", "The lecturer changed the topic", "The original room closed permanently", "The starting time changed"], "because 后说明报名人数超过预期，时间仍为两点。"),
    ("I thought the field trip would be cancelled because of the rain. Instead, the organiser has shortened the outdoor walk and added a visit to the indoor exhibition. We should still bring coats because the first part will be outside.", "How has the field trip changed?", ["A shorter walk and an indoor exhibition", "It has been cancelled", "It is entirely outdoors", "It will take place next year"], "Instead 否定取消的猜测，计划变为缩短步行加室内参观。"),
    ("The grant covers equipment and local travel, but it cannot be used to pay for accommodation. Before submitting the budget, applicants should explain how they will cover any overnight stays. Receipts are required for all reimbursed expenses.", "Which expense is NOT covered by the grant?", ["Accommodation", "Equipment", "Local travel", "All travel and equipment"], "but it cannot 后指出住宿不在资助范围。"),
    ("The software saved us time when sorting survey responses. Still, we checked the unusual entries by hand. Automatic sorting is useful, but errors in the original data can pass through unnoticed unless someone reviews the results.", "What is the speaker's main point?", ["Automation is useful but needs human checks", "All automatic sorting is useless", "Original data never contain errors", "People should stop using surveys"], "先肯定节约时间，再强调人工复核异常，观点包含收益和限制。"),
    ("Our community garden has attracted many volunteers. The difficulty is that most come on Saturdays, leaving weekday watering to just two people. We are asking volunteers to choose one weekday shift if their schedules allow it.", "What problem does the garden face?", ["Too few volunteers for weekday watering", "No volunteers on Saturdays", "Too many plants have been removed", "A complete lack of water"], "问题是周中浇水人手少，不是没有周六志愿者或缺水。"),
    ("The library will email a reminder three days before a book is due. You can renew online unless another reader has reserved the book. In that case, please return it by the original due date so the next reader can use it.", "When is online renewal unavailable?", ["When another reader has reserved the book", "Whenever an email reminder arrives", "For every book borrowed online", "Three days after borrowing any book"], "unless another reader has reserved 是续借的例外条件。"),
    ("A recent pilot offered free breakfast to students attending early classes. Attendance rose during the trial, although the organisers caution that the trial lasted only two weeks. They plan a longer study before deciding whether to expand the service.", "Why do the organisers want a longer study?", ["The short pilot provides limited evidence", "Attendance fell during the trial", "Breakfast was never offered", "All students refused to attend"], "although 后指出仅两周，短期证据不足以支持直接扩大。"),
    ("We initially planned to interview customers at the shop entrance. The manager worried that this would block the doorway. We have therefore arranged a small table in the courtyard, where participants can talk without interrupting other visitors.", "Where will the interviews take place?", ["In the courtyard", "In the doorway", "Inside the manager's car", "At the railway station"], "initially 是原计划，therefore 后才是最终安排：courtyard。"),
    ("The workshop is intended for beginners. Participants do not need to buy special tools, as the organisers will provide them. However, everyone should bring a damaged household item so that they can practise a repair during the session.", "What should participants bring?", ["A damaged household item", "A complete set of special tools", "An advanced qualification", "A completed repair report"], "工具由组织者提供；however 后明确需要自带待修的家用物品。"),
]


def _question(kp, index, row, *, listening=False):
    if listening:
        transcript, stem, options, explain = row
    else:
        stem, options, explain = row
    shift = index % 4
    options = options[shift:] + options[:shift]
    phase, number = ("baseline", index + 1) if index < 3 else ("fresh", index - 2)
    q = {"id": f"{kp}-{phase}-{number}", "kp": kp, "stem": stem,
         "options": options, "answer": "ABCD"[(-shift) % 4], "type": "single",
         "difficulty": 1 if index == 0 else 2, "explain": explain}
    if listening:
        q.update(transcript=transcript, audio_url=f"/course-audio/cet6-v1/{q['id']}.wav")
    return q


def build_course() -> dict:
    nodes, bank, practice, sections, evidence = [], [], [], [], {}
    for kp, name, anchor, objective in TOPICS:
        nodes.append({"id": kp, "name": name, "chapter": name, "difficulty": 2, "desc": objective, "aliases": ALIASES[kp]})
        text = LESSONS[kp]
        locator = {"id": anchor, "title": name, "kps": [kp], "url": f"{GUIDE_URL}#{anchor}",
                   "sha256": hashlib.sha256(text.encode()).hexdigest()}
        sections.append(locator)
        evidence[kp] = [{"source": "小知六级起点学习指南（原创）", "source_id": "cet6-guide-v1",
            "section_id": anchor, "chapter": name, "url": locator["url"], "version": VERSION,
            "text": text, "sha256": locator["sha256"], "location_kind": "章节"}]
        for index, row in enumerate(LISTENING if kp == "cet6_listening" else ITEMS[kp]):
            q = _question(kp, index, row, listening=kp == "cet6_listening")
            q["citations"] = [{k: v for k, v in e.items() if k != "text"} for e in evidence[kp]]
            (bank if index < 3 else practice).append(q)
    # One original multi-select distinction item; not an imitation of exam format.
    bank[2].update(stem="哪些改写保留了原句 'The change may improve access' 的不确定性？（多选）",
        options=["The change could make access easier.", "The change will certainly solve every problem.",
                 "The change might improve access.", "The change has already improved access everywhere."],
        answer=["A", "C"], type="multiple", explain="could 和 might 保留可能性；certainly 和 already 分别添加确定性与已发生事实。")
    textbook = {"id": "cet6-guide-v1", "title": "小知六级起点学习指南（原创）", "version": VERSION,
        "course": "cet6", "url": GUIDE_URL, "license": "CC BY-SA 4.0", "license_url": GUIDE_URL,
        "source_note": "指南、例子与训练题为本站原创；考试结构参考教育部教育考试院。未接入历年真题全文。",
        "scope_note": "覆盖词汇、两类阅读、听力、写作与翻译基础。18 道起点题与 54 道不同的新题，含 12 段合成英语音频。六级正式笔试还需要完整篇幅与限时训练。",
        "sha256": hashlib.sha256(json.dumps(LESSONS, ensure_ascii=False, sort_keys=True).encode()).hexdigest(), "sections": sections}
    return {"kind": "cet6", "title": TITLE, "bank": bank, "practice_bank": practice,
        "lessons": LESSONS.copy(), "evidence": evidence, "textbook": textbook,
        "coverage_note": textbook["scope_note"], "boundary": BOUNDARY,
        # These skills can be trained in parallel; no artificial Python-style chain.
        "graph": {"course_id": "cet6", "course": TITLE, "version": 1, "nodes": nodes, "edges": []},
        "exam_reference": {"url": OFFICIAL_URL, "checked_on": "2026-09-18", "total_minutes": 130,
            "parts": [{"name": "写作", "weight": 15, "minutes": 30}, {"name": "听力", "weight": 35, "minutes": 30},
                      {"name": "阅读", "weight": 35, "minutes": 40}, {"name": "翻译", "weight": 15, "minutes": 30}]}}
