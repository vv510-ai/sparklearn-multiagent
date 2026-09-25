# 英语生活场景三课试点

课程 ID：`english-scenes`；首个版本：`english-scenes-v1`。入口 `/library`。

## 用户能做什么

同学邀约、咖啡店点单、室友协商各有 8 句原创对话。直接进入后可以播放整段、按需打开中英文字幕、跳到任意句、慢放和循环复听，再按步骤看懂表达。每课有一次新情境选择题、隔日另一道新题，以及必须自己写回应的迁移任务。无需上传、无需先测评、无需录音。

参考回应由服务端在“已保存自己的回应 + 主动请求查看”之后提供；它是一个示例，不是唯一正确答案。查看后保持 `reference_viewed/assisted`，修改文本也不恢复成独立作答。听力记录明确为 `client_reported`：只有页面整段自然结束才解锁记录按钮，单句循环和文字降级不能解锁；服务端校验音频版本，但不宣称能够证明用户听见、听懂或跟读。所有活动都不写入知识掌握度。

这三课不覆盖大学英语全课程或四六级考纲，也不含《老友记》素材。当前是 AI 辅助编写、合成朗读的试点，未经过英语教师审校、学生学习效果实验或主观音质听审。浏览器完整解码播放、波形与时间轴校验不等于这三项验收。

## 原创内容与参考依据

- 对话、译文、任务、题目和讲解由本站 AI 辅助编写，源码在 `backend/scripts/english_scenes_content.py`；不会标为官方教材或考试真题。
- 情态动词邀请、请求和许可用法参考 [British Council 原文](https://learnenglishteens.britishcouncil.org/grammar/b1-b2-grammar/can-could-would-invitations-offers-requests-permission)。2026-09-25 核验正文，只链接，不收录网页对话/视频/练习。这里提供用法依据，不声称机构审定或背书。
- 音频使用 [Bryce Beattie 的 LJSpeech medium](https://brycebeattie.com/files/tts/)，作者将该模型列为 public domain。[原始数据作者](https://keithito.com/LJ-Speech-Dataset/)声明数据在美国为公有领域、无使用限制；不扩大为全球法律保证。[模型卡](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD)提供模型与训练者关系。
- 离线构建程序 Piper 1.4.2 的 [GPL 许可](https://github.com/OHF-Voice/piper1-gpl/blob/v1.4.2/COPYING)与声音模型许可分别记录。只将本站原创文本生成的 WAV 加入网站；运行程序和模型权重未打包进服务。该选择是基于上述原始许可的工程判断。
- 本版是同一个美式单人合成声音朗读所有角色，页面用角色名区分；没有演员声音模仿。

## 技术选择与独立审查

沿用已发布课程的不可变版本、所有权、进度 CAS、独立课程索引和撤回机制。增加 `english_scenes` 类型、平台原创来源类型、受鉴权保护的媒体与原文端点。无需新增数据库、向量服务、在线 TTS 或浏览器依赖。

教学动画采用课程 JSON 的 `scene.steps` 作为不可变步骤，React 只按步骤下标渲染。支持前进、后退、从末尾重播、回到第一步、键盘首尾/左右/空格；键盘处理仅限拆解区域自身，不截获输入框。优先减少首屏信息，字幕、全文、讲解、出处和示例按需展开。

替代方案：Windows System.Speech 在本机可生成 WAV，但没有找到足以确认当前桌面声音公开分发的明确依据，因此未采用；在线 TTS 会增加密钥、计费及服务可用性依赖；完整影视导入超出本试点。若真人示范质量成为验收门槛，应改为已授权录音并创建新版本，不能原地替换音频。

standard 模式独立审查纠正了时间数量笔误，识别桌面声音许可缺口，复核了原文/示例隔离、媒体撤回和掌握度边界。未将独立代码审查当作教师审校或音质听审。

## 文件与数据边界

- `backend/app/data/course_library/english-scenes-v1.json`：内容、课时目标、步骤、题目、来源和媒体清单。
- `backend/app/data/course_media/english-scenes-v1/*.wav`：实际发布的 22,050 Hz / 16-bit / mono PCM。
- `backend/app/services/english_scene_library.py`：路径约束、音频/文本 SHA-256、时长、逐句顺序与范围校验。
- `GET /api/library/releases/{release_id}/media/{lesson_id}`：鉴权、每次读检查撤回与文件哈希，支持 Range，`private, no-store`。文件不放入公开 static 目录。
- `GET /api/library/releases/{release_id}/sections/{section_id}`：鉴权及撤回保护的原创文本出处。
- RAG 仅收录三节原创对话与导学，标为 `platform_original`；不收录迁移任务参考答案或新题答案。引用证明检索了材料，不代表回答每句话都已经核实。
- 句级时间点来自实际音频 PCM 帧数，不由字数估计，也不伪装成逐词时间轴。切换课程/课时或退出登录会卸载播放器并暂停。

## 离线重建

已发布版本必须新建 ID；不要重新生成并覆盖 v1。生成随机性可能改变 WAV，模型固定也不代表音频按字节可复现，最终 WAV SHA 才是该次发布的内容标识。

1. 单独创建构建虚拟环境，安装 `piper-tts==1.4.2`；不向后端生产 requirements 添加依赖。
2. 从模型作者页面下载 `lj-med.onnx` 与 `lj-med.onnx.json` 到本地构建缓存。
3. 首次发布前运行：`python backend/scripts/build_english_scenes_audio.py --model <路径>/lj-med.onnx`。脚本拒绝覆写现有版本。
4. 模型 SHA-256 为 `6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22`；配置 SHA-256 为 `01699b1f64aec09d359efd73aed94453d83a3fe6031de1f570bbb1df46d995d2`，脚本先校验再运行。
5. 新增版本需同步维护部署时的显式 bundle 列表；不能用任意目录自动发现代替发布审核。

## 验证方式

后端：`backend/tests/test_english_scene_library.py` 验证音频真实文件与定位、请求参数、答案隐藏、辅助状态持久化、账户隔离、Range、RAG 来源类型和撤回。完整后端测试仍必须通过。

浏览器：`frontend/e2e/english-scenes.spec.ts` 实际等待三段 WAV 自然播放结束，检查循环不算完整播放、逐句返回、字幕开关、键盘不影响作答、任务保存与恢复、三个视口和故障降级。播放验证没有人工触发 ended 事件，也没有 seek 到结尾。Python 课程原回归同时保留。

线上验收使用 `scripts/acceptance.py live --suite english-scenes --expected-commit <完整提交> --identity <部署验证密钥> --allow-live-models`，在既有部署互斥锁内完成相同核心链路和一次真实模型引用原始英语材料的问答。密钥和浏览器认证信息不写入仓库。


2026-09-25 本地结果：633 项后端测试通过；前端生产构建通过；3 条浏览器用例通过；4 项验收运行器测试通过。三段真实 WAV 自然播完，音频降级不写播放记录，1280/834/390 宽度无横向溢出；已检查电脑与手机截图。后台信号暂停用模拟 visibilitychange 回归，未声称完成真实操作系统后台实测。结果保存在本地 `.tmp/english-browser-final`，不包含在部署产物中。
