"""Original pilot content. Run build_english_scenes_audio.py to produce a new release."""
import hashlib
import json
from pathlib import Path

REFERENCE = "https://learnenglishteens.britishcouncil.org/grammar/b1-b2-grammar/can-could-would-invitations-offers-requests-permission"
SCENES = [
    dict(id="invitation", title="同学邀约", objective="发出邀请；时间冲突时提出替代安排，并确认地点。",
         context="周四下课后，Maya 想约 Alex 周五一起复习。他们需要找到双方都有空的时间。先听一遍，留意最终约定。",
         lines=[
             ("Maya", "Would you like to study together at the library on Friday afternoon?", "周五下午你想一起去图书馆复习吗？"),
             ("Alex", "I'd love to, but I have a lab until four. What time were you thinking?", "我很想去，不过实验课要到四点。你原本想几点？"),
             ("Maya", "I was thinking three, but we could meet a little later.", "我原本想三点，不过我们可以稍晚一点见。"),
             ("Alex", "Would four thirty work for you? That would give me time to get there.", "四点半你方便吗？那样我就来得及赶过去。"),
             ("Maya", "That works for me. Let's meet by the library entrance.", "我可以。我们在图书馆入口见吧。"),
             ("Alex", "Great. Should I bring my notes from last week's lecture?", "好。我要带上周的课堂笔记吗？"),
             ("Maya", "Yes, please. I'll bring the practice questions, and we can compare our answers.", "好呀。我会带练习题，我们可以核对答案。"),
             ("Alex", "Perfect. See you at four thirty on Friday, by the entrance.", "太好了。周五四点半入口见。"),
         ],
         steps=[
             ("发出邀请", ["Would you like", "to study together", "on Friday afternoon?"], "would like 后接 to + 动词原形。这里是在邀请对方参与活动。"),
             ("友好地说明冲突", ["I'd love to,", "but I have a lab", "until four."], "先表达意愿，再说明时间冲突；不是已经接受原定时间。"),
             ("换成你自己的安排", ["Would", "Saturday morning", "work for you?"], "替换中间的时间，再问对方是否方便。work 在这里表示安排可行。"),
         ],
         markdown="### 先听意图，再看表达\n邀请不只是一句问话：要说明活动，再协调时间，最后确认地点。\n\n**Would you like to …?** 后面接动作。**I'd love to, but …** 表示有意愿但有障碍。**Would … work for you?** 用来确认安排是否合适。\n\n听到多个时间时，不要只记第一个：三点是最初提议，四点是实验结束，四点半才是双方确认的见面时间。",
         task="换个情境：邀请同学周六上午去校园摄影展；对方十点前有课。用英语写 3–5 句，提出一个可行时间并确认见面地点。不要照抄图书馆对话。",
         criteria=["说清楚摄影展这个活动", "安排在十点之后，并询问对方是否方便", "确认具体见面地点"],
         reference="Would you like to visit the campus photo exhibition on Saturday? We could meet at ten thirty, after your class. Would that work for you? Let's meet outside the student center.",
         questions=[
             ("同学邀请你周一两点讨论报告，但你三点前有课。哪一句既说明冲突又提出可行安排？", ["I'd love to, but I have class until three. Would three thirty work?", "Yes, two o'clock is perfect. I have class then.", "I'd love to. See you yesterday.", "The report has three pages."], 0, "先说明三点前有课，再提议三点半，既回应邀请又推动协商。"),
             ("隔日换题：你们原本约十点。对方说 'I have class until eleven. Could we meet at eleven thirty?' 你回答 'That works for me.' 最终约在几点？", ["十点", "十一点", "十一点半", "没有确定"], 2, "That works for me 接受的是对方刚提出的十一点半。"),
         ]),
    dict(id="cafe", title="咖啡店点单", objective="说明饮品、大小和冷热；缺货时确认替代选择，复述订单。",
         context="Maya 在校园咖啡店点饮料。她想要燕麦奶，但店员提供了另一种选择。先听懂她最终买了什么。",
         lines=[
             ("Maya", "Hi. Could I have a small iced latte with oat milk, please?", "你好，请给我一杯小杯冰拿铁，换成燕麦奶。"),
             ("Alex", "I'm sorry, we're out of oat milk today. We have soy milk or regular milk.", "抱歉，今天燕麦奶用完了。我们有豆奶或普通牛奶。"),
             ("Maya", "Soy milk is fine. Is there an extra charge for that?", "豆奶可以。换豆奶需要加钱吗？"),
             ("Alex", "No extra charge. Would you like anything to eat with your drink?", "不用加钱。你想配点吃的吗？"),
             ("Maya", "No, thank you. Just the latte, to go, please.", "不用，谢谢。只要拿铁，请打包。"),
             ("Alex", "Sure. That's one small iced latte with soy milk, to go.", "好的，一杯小杯冰豆奶拿铁，打包。"),
             ("Maya", "That's right. Could you tell me where I should pick it up?", "没错。请问我在哪里取饮料？"),
             ("Alex", "At the counter by the window. We'll call your name when it's ready.", "在窗边的柜台。做好后我们会叫你的名字。"),
         ],
         steps=[
             ("礼貌提出需求", ["Could I have", "a small iced latte", "please?"], "Could I have …? 是点单时的请求，不是在问过去的能力。"),
             ("补充具体要求", ["a small iced latte", "with soy milk", "to go"], "大小、冷热、配料和是否带走是不同信息；听复述时逐项核对。"),
             ("迁移到新订单", ["Could I have", "a large hot tea", "to go, please?"], "替换饮品时也要同步修改大小和冷热，不能只换一个词。"),
         ],
         markdown="### 把订单说完整\n**Could I have …, please?** 可以礼貌点单。**with …** 补充配料；**to go** 表示带走。**We're out of …** 表示当前没有这种商品。\n\n这段对话最初要的是燕麦奶，最终确认的是豆奶；不要把第一句请求误当成最终订单。例子中的价格规则只适用于这段虚构对话，现实中需要向店员确认。",
         task="换个情境：你想买大杯热红茶，不加糖，带走。店员说只有绿茶。写 3–5 句英语，确认替代饮品是否含咖啡因，再说明你是否接受，并复述最终要求。",
         criteria=["明确大杯、热饮、不加糖、带走", "询问替代饮品是否含咖啡因", "表达接受或拒绝并确认自己的选择"],
         reference="Could I have a large hot black tea with no sugar, to go, please? Does the green tea contain caffeine? Green tea is fine for me. So that's a large hot green tea, no sugar, to go. Thank you.",
         questions=[
             ("你想确认替代牛奶会不会加钱。哪一句直接询问这件事？", ["Where should I pick it up?", "Could I have it to go?", "Is there an extra charge for that?", "Would you like a drink?"], 2, "extra charge 指额外费用；另外三项分别问取餐、打包或邀请喝饮料。"),
             ("隔日换题：顾客说 'A large hot tea, please.' 店员问 'For here?' 顾客回答 'To go, please.' 最终要求是什么？", ["小杯冰茶，店内", "大杯热茶，带走", "大杯冰茶，带走", "小杯热茶，店内"], 1, "large / hot / to go 分别提供大小、冷热与带走的信息。"),
         ]),
    dict(id="roommates", title="室友协商", objective="说清具体影响，礼貌请求调整，再协商双方可执行的安排。",
         context="Maya 明早有考试，室友 Alex 正在和小组通话。两人要协调安静时间，不把请求变成指责。",
         lines=[
             ("Maya", "Hey, could we talk about the noise for a minute? I have an exam tomorrow morning.", "嘿，我们能聊一下声音的问题吗？我明天上午有考试。"),
             ("Alex", "Sure. Is my call too loud? We're working on a group project.", "可以。我的通话声音太大了吗？我们正在做小组项目。"),
             ("Maya", "A little. Could you use headphones? I'm trying to review my notes.", "有一点。你可以用耳机吗？我正想复习笔记。"),
             ("Alex", "Of course. I still need to speak, though. We should finish in about twenty minutes.", "当然可以。不过我还需要说话。我们大概二十分钟后结束。"),
             ("Maya", "Thanks. Could we keep the room quiet after ten tonight?", "谢谢。今晚十点之后，我们能让房间安静下来吗？"),
             ("Alex", "Yes. If the call runs late, I'll move to the common room.", "可以。如果通话延迟结束，我会去公共休息室。"),
             ("Maya", "That would really help. I'll use headphones when you're studying, too.", "那会很有帮助。你学习的时候我也会戴耳机。"),
             ("Alex", "Sounds fair. Good luck with your exam tomorrow.", "这样很公平。祝你明天考试顺利。"),
         ],
         steps=[
             ("提出具体请求", ["Could you", "use headphones", "please?"], "Could you + 动词原形，请对方做一个具体动作。语气也会影响礼貌程度。"),
             ("补充理由", ["I'm trying", "to review", "my notes."], "说明自己正在做什么，让对方理解影响；避免一上来评价对方的人品。"),
             ("形成双方约定", ["Could we", "keep the room quiet", "after ten?"], "you 换成 we，协商双方共同遵守的安排；时间要具体。"),
         ],
         markdown="### 请求要具体，安排要可执行\n**Could you + 动词原形 …?** 可以请求对方调整行为。**Could we …?** 可以协商共同安排。礼貌也取决于语气和情境，不是加 could 就自动合适。\n\n戴耳机只能减少外放声音，不能消除通话者说话的声音。对话因此又约定了十点后的安静时间，以及通话延迟时去公共休息室的办法。",
         task="换个情境：室友常在公共书桌上放餐盒，你今晚需要用桌子准备演示。写 3–5 句英语：说明影响，请对方做一个具体动作，提出以后双方可以遵守的安排。",
         criteria=["说明今晚需要桌子准备演示", "礼貌请求收走餐盒或清理桌面", "提出双方都能执行的日常安排"],
         reference="Could you clear the food containers from the shared desk, please? I need to prepare my presentation there tonight. Could we both clear the desk after each meal? That would make it easier for us to study.",
         questions=[
             ("你需要室友把外放音乐调小，哪一句最清楚地提出具体请求？", ["You are always a bad roommate.", "Could you turn the music down? I need to study.", "The music was interesting yesterday.", "I own some headphones."], 1, "turn the music down 是可执行的动作，后半句解释需要；不是泛泛指责。"),
             ("隔日换题：室友说 'I can move my call to the common room after nine.' 你回答 'Thanks, that would help.' 你们确认的安排是哪项？", ["九点前取消所有通话", "你搬到公共休息室", "室友九点后转移通话地点", "整晚都在卧室通话"], 2, "主语 I 指室友，after nine 是时间边界，move my call 指转移通话地点。"),
         ]),
]


def make_bundle():
    rid = "english-scenes-v1"
    lessons, sections = [], []
    for s in SCENES:
        lines = [dict(id=f"{s['id']}-{i+1}", speaker=who, text=en, translation=zh) for i, (who,en,zh) in enumerate(s["lines"])]
        # No transfer-task reference answers or new-question answers in retrieval.
        source = s["context"] + "\n\n" + "\n".join(f"{l['speaker']}: {l['text']}\n{l['translation']}" for l in lines) + "\n\n" + s["markdown"]
        sid = s["id"] + "-guide"
        sections.append(dict(id=sid,title=s["title"]+" · 原创对话与导学",url=f"/api/library/releases/{rid}/sections/{sid}",text=source,sha256=hashlib.sha256(source.encode()).hexdigest(),kps=["english_scene_"+s["id"]]))
        lessons.append(dict(id=s["id"],title=s["title"],objective=s["objective"],markdown=s["markdown"],example={"code":"", "output":""},task=s["task"],criteria=s["criteria"],work_reference=s["reference"],review_prompt="隔日回到本课，用新题检查能否把表达用在不同场合。",authoring="本站 AI 辅助编写的原创场景与练习；非影视台词、非考试真题，尚未经英语教师审校。",source_sections=[sid],scene={"context":s["context"],"lines":lines,"steps":[dict(id=str(i+1),title=t,parts=p,explanation=e) for i,(t,p,e) in enumerate(s["steps"])],"references":[{"title":"British Council：邀请与请求的情态动词用法", "url":REFERENCE}],"alignment":"句级定位；不提供逐词时间对齐"},questions=[dict(id=s["id"]+f"-q{i+1}",stem=stem,code="",options=opts,answer=ans,expected=opts[ans],explanation=ex) for i,(stem,opts,ans,ex) in enumerate(s["questions"])]))
    return dict(schema_version=1,kind="english_scenes",kp_prefix="english_scene_",emoji="🎧",course_id="english-scenes",release_id=rid,title="英语生活场景 · 三课试学",description="从校园里的三段日常对话开始：先听，再逐句理解，最后换个情境自己表达。",audience="有基础英语词汇，想练习日常交流的大学生",prerequisites="无需上传视频或教材；准备能播放声音的设备即可",scope="3 个原创场景，含合成音频、逐句复听、表达拆解、迁移任务和隔日新题。",not_covered="完整大学英语课程、四六级考纲、真人发音示范、口语评分与影视剧内容。",status_label="原创场景试点 · 3 课",review={"method":"原创内容逐项核对、语言用法参考链接、音频与文本哈希及句级定位检查", "note":"本站原创试点，合成语音；尚未经英语教师审校或学习效果验证。播放与自查不计入能力分数。"},rights={"public_distribution":True,"license_notice":"本站 AI 辅助编写的原创对话、中文解释与练习。音频由 Piper / LJSpeech medium 离线合成；声音模型作者标示 public domain，许可来源另列。未使用影视台词、音乐或演员录音。语法参考仅提供官方链接，不收录对方网页、视频或练习全文。"},textbook={"id":"english-scenes-original-guide", "title":"LearnLoop 原创英语生活场景导学", "course":"英语生活场景", "version":"1.0", "source_kind":"platform_original", "license":"本站原创学习材料；供本平台学习使用", "sections":sections},lessons=lessons)

if __name__ == "__main__":
    import sys
    Path(sys.argv[1]).write_text(json.dumps(make_bundle(),ensure_ascii=False,indent=2),encoding="utf-8")
