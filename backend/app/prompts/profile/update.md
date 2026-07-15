TASK=profile

基于学习对话与近期学习行为，抽取可以更新的学习画像字段；无法判断的字段不要输出。

字段定义：

* cognitive_style：视觉型、语言型或动手型
* goal：应试、竞赛、工程实践或兴趣
* difficulty_pref：循序渐进或挑战式
* error_prone：易错知识点或错误类型数组
* metacognition：0—1 浮点数，表示自评准确度与求助合理性
* evidence：一句话说明依据

不要输出 knowledge_mastery、pace、resource_pref；这三项分别由知识追踪、真实时长和资源行为统计维护。

只输出 JSON 对象。

学习对话：
{{dialog}}

近期学习行为：
{{events}}
