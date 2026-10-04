# 单词发音跨设备修复

用户反馈安卓 Chrome／自带浏览器无法播放单词，并要求不同设备均能听到。

原实现只调用 `speechSynthesis.getVoices()`，且要求声音的语言严格匹配 `en-US` 或 `en-GB`。没有安装对应英语语音、声音列表尚未准备好或浏览器没有可用合成引擎时，按钮不能发声。旧验收只检查了“设备合成语音”文案和口音选项，没有验证没有本机语音时的真实播放。

## 实现

- 为修正后的全部 8,010 个词条生成英美两套 MP3，共 16,020 段。音频随网站发布，同源访问，设备无需安装英语语音包，也不在点击时请求在线合成服务。
- 词条详情和有限轮次均使用 `WordPronunciation`。点击处理器直接调用原生 `audio.play()`，中间没有异步请求或定时器，保留手机浏览器所需的用户点击上下文。
- 保留英美切换、慢速和重播；切词、切口音或离开时停止旧音频。真实加载或权限失败会提示，提供原生播放器并可重试，不把错误记为成功。
- 静态文件位于 `frontend/public/word-audio/v1/{accent}/{entry_id}.mp3`，支持 Range 请求；版本目录不可原地重建，使用一年不可变缓存。
- `frontend/scripts/verify-word-audio.mjs` 在构建前校验完整有效词库、两种口音、文本映射、全部文件 SHA-256 和生成时的非静音检查。原词库及学习记录不变。
- 音频按二进制入库；词库文本哈希统一为 LF 换行，使 Windows 与 Linux 检出结果一致。
- 源文件哈希用于追溯生成来源；发音构建门槛校验完整的词条 ID 与有效拼写，单独修改释义不会要求重建音频。

## 音频来源与重建

沿用项目已有的离线 Piper 方案。美式为 LJSpeech medium，英式为 Cori medium，模型作者均为 Bryce Beattie；[作者页面](https://brycebeattie.com/files/tts/)把两模型标为 public domain。使用的是合成语音，不标为词典真人录音，页面仍保留 Cambridge 核对入口。多音词、重音与整套发音的教学质量没有经过逐词专家听审。

隔离构建环境：`piper-tts==1.4.2`、`lameenc==1.8.4`、`miniaudio==1.71`。每段 MP3 都解码后检查时长与非静音采样。引擎、编解码库和模型权重只用于构建，不进入服务器运行依赖。所有模型／配置哈希固定在 `backend/scripts/build_word_audio.py` 和发布清单。

```powershell
.tmp/piper-env/Scripts/python.exe backend/scripts/build_word_audio.py --us-model .tmp/piper-model/lj-med.onnx --gb-model .tmp/word-audio-models/cori-med.onnx
```

默认一个构建工作进程，避免 Windows 内存压力。生成器拒绝覆盖已完成版本；对没有最终 manifest 的中断构建，可加 `--resume`，先逐段解码已有文件，再补齐缺失部分。未来需变更发音时使用新目录，并同步播放器与完整性检查器的版本；不能破坏已缓存的 v1 内容。

## 验证

- `npm run build -- --webpack`：含全词库覆盖及文件完整性门槛。
- `node node_modules/@playwright/test/cli.js test --config playwright.word-audio.config.ts --project desktop-chromium --project android-chromium --project iphone-webkit`：桌面 Chromium、安卓视口 Chromium、iPhone 视口 WebKit；禁用设备语音接口，验证英美实际解码、自然结束、慢速、重播、Range、刷新记忆、网络失败、权限拒绝后重试和卸载停止。Chromium 关闭测试框架默认的音频静音参数。
- 加载错误用真实不存在的音频 URL 触发 HTTP 404，权限错误仅注入一次 `NotAllowedError`；恢复后仍须正常解码并自然播放结束。WebKit 的原生媒体请求可能绕过浏览器请求拦截，因此不依赖 `page.route` 制造音频网络错误。
- 生产运行 `python scripts/acceptance.py live --suite word-audio --expected-commit <完整提交> --identity <部署验证密钥>`，沿用 `ReleaseLease` 锁定已部署提交；只使用专用测试账号，不调用文字或语音模型。
- 详情验收固定使用内置讲解词 `analyze`，导航前只读确认默认义项的讲解已经就绪，避免打开缺失讲解的词卡时自动触发模型生成。各浏览器使用独立账号与课程，沿用仓库的串行运行方式。
- 浏览器引擎与移动模拟不能代替用户真机的扬声器／系统音量测试，也不等于逐词音质听审。
- 当前 Windows 上，官方 Playwright Firefox 1538 包在启动前报 `SideBySide: mozglue assembly not found`；DLL 与官方压缩包一致，尚不能得到 Firefox 产品流程结论。可重复传入 `--browser-project desktop-chromium --browser-project android-chromium --browser-project iphone-webkit` 执行可用引擎，报告会记录精确项目范围；Firefox 项目保留供可启动的环境验证。

兼容性依据：[MDN 的设备声音列表说明](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis/getVoices)、[WebKit 的媒体用户操作限制](https://webkit.org/blog/7734/auto-play-policy-changes-for-macos/)。

## 本地验收结果（2026-10-05）

- 全量 8,010 词、16,020 段音频通过逐段解码、非静音及文件完整性检查，共 85,844,226 字节，平均每段约 5.4 KB，按当前词加载。
- `npm run build -- --webpack` 通过，含音频校验和 TypeScript；记录：`.tmp/word-audio-build-frontend-final.log`。
- 后端完整回归 784 项通过（1 条依赖弃用警告）；验收运行器 4 项检查通过。后端记录：`.tmp/word-audio-final-backend.log`。
- 正式构建中桌面 Chromium、安卓模拟、iPhone WebKit 模拟各 3 项，共 9 项通过，无失败、重试或跳过；已查看手机截图。报告：`.tmp/word-audio-release-final.json`，截图：`.tmp/word-audio-release-final/`。这验证浏览器播放流程，不代表逐台真机扬声器或逐词发音质量验收。
