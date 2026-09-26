# 英语词典依据试点 · 2026-09-26

## 目的与范围

英语场景仍由共享模型网关与独立 Markdown Prompt 生成，词典来源由程序补充，模型不能填写来源 URL 或核验状态。沿用 english-vocabulary-notes 的来源分离原则，并非在网站运行完整 Skill。

第一版只覆盖三个输入预设中的 9 个词：hesitate、awkward、figure out、recommend、instead、take away、follow up、clarify、deadline。匹配允许大小写和空格差异，不猜测词形变化、同义词或相近词。其他词标明“暂无内置词典摘录”，提供 Wiktionary 搜索入口；该链接不代表词条存在。

收录部分英文释义、词性与原标签，不含发音、词源、真题、第三方引文。词典词条存在不证明模型的中文义项、搭配或例句已通过核验。尤其 take away 摘录列出了移走、剥夺、减去等义项，没有将它认定为餐饮场景用法的核验依据。查看词典时需结合语境；完整义项见原词条。

## 候选与决定

| 路线 | 证据与实验 | 决定 |
| --- | --- | --- |
| Cambridge API | [官方 FAQ](https://dictionary-api.cambridge.org/api/faq) 要求申请授权和密钥；常规条款不允许存储返回内容 | 本轮没有此授权，不接入其数据 |
| Merriam-Webster API | [官方入口](https://dictionaryapi.com/) 需要注册密钥；免费使用有用途与调用限制 | 暂不引入新账户与授权依赖 |
| Free Dictionary API | [官网](https://dictionaryapi.dev/)、[GitHub](https://github.com/meetDeveloper/freeDictionaryAPI)；仓库代码 GPL-3.0；本地与 ECS 最小连接实验出现超时/连接失败 | 不作为生成成功的必经接口；没有复制其代码 |
| Kaikki / Wiktextract | [数据说明](https://kaikki.org/dictionary/)、[项目](https://github.com/tatuylonen/wiktextract)；ECS 实际取得 9 个英文词条 JSONL | 仅复用小量已读取的数据快照，不安装提取器 |
| Kaikki 在线逐词查找 | [上游移除公告 #1178](https://github.com/tatuylonen/wiktextract/issues/1178) 涉及后处理数据与逐词链接，实测也存在偶发连接失败 | 不新增运行时依赖，快照随网站版本部署 |

本次是候选与目标环境的有界调研，不声称穷尽全部词典服务。复用的是许可范围内的数据与来源追踪方法，没有复制第三方实现。原逐词下载链接未来可能失效；已内置的摘录仍可读，完整词条指向 Wiktionary。后续扩大词库时应基于 Kaikki raw dump 按版本构建索引，或取得学习型词典 API 的正式授权，不依赖已公告弃用的接口。

## 数据与许可

data/english_dictionary_v1.json 的英文摘录由 Wiktionary contributors 编写，经 Kaikki / Wiktextract 提取，按 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) 提供。授权依据：[Kaikki 数据许可](https://kaikki.org/dictionary/)、[Wiktionary 版权说明](https://en.wiktionary.org/wiki/Wiktionary:Copyrights)。代码许可与数据许可分别判断；本轮未复制 GPL 代码。站内及归档均保留署名、词条与提取链接、许可证和摘录日期。

每条记录保留原始 JSONL SHA-256、实际读取时间、原词条、提取 URL 和本地版本；只选择与试点相关的义项，未改写原文，展示顺序可调整。界面中文词性标签是对应字段的显示映射。没有下载第三方例句、录音或图片，不据此宣称权威词典背书。

## 接口与兼容

- 新场景完成字段校验后，再按词头附加 dictionary；生成流程不访问外部词典，无新增超时或费用。
- 最近场景读取时按本地版本补充来源，可兼容旧记录；此 GET 不写数据库。来源更新不更改原句、释义或练习。
- 新归档同时保存结构化来源和带完整署名的 Markdown。练习重试只发送原句和 AI 词汇字段，不发送词典摘录或外部链接。
- 词典数据文件缺失/解析失败时回退为未收录，已生成内容仍可使用。没有新增全量词典、调度器、数据库表或外发用户资料。
- 暂不做自动义项匹配、专家核验、复习排程或全词库覆盖；这些需要独立数据与验收，不能由本次来源卡片推断完成。

## 验收

后端检查真实快照的来源/许可/字段、未收录与损坏文件降级、模型伪造来源被覆盖、旧记录兼容、归档署名及练习上下文隔离。浏览器检查来源折叠、英文释义、未收录入口、刷新恢复和桌面/平板/手机布局。生产验收继续使用同版本部署锁，测试真实生成与保存，并将实际词典摘录附入验收证据。
