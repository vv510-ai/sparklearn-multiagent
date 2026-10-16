# 任务：按已确认的分镜，制作「{{topic}}」讲解视频

分镜方案已确认。{{approval_notes}}

现在开始制作，目标是一条可以直接给学习者观看的成片。

## 已经准备好的素材

- `storyboard.json`：确认后的分镜。每一镜都有 `start`、`end`（秒），由真实配音的时长决定，必须严格按这个时间轴制作；全片时长是其中的 `duration` 字段。
- `video/assets/narration.mp3`：完整旁白配音，从第 0 秒开始播放，不要改动它的时间。
- `audio/captions.json`：逐句字幕时间轴，格式为 `[{"text": "...", "start": 0.0, "end": 2.4}]`。
- `video/`：已经初始化好的 HyperFrames 项目（`video/index.html` 是根合成），`video/vendor/gsap.min.js` 是本地 GSAP。
- `guides/`：讲解视频的视觉设计、动效语言和叙事参考，动手前先读一遍。

{{engine_rule}}

## 制作要求

1. **画面与旁白同步**：每一镜在自己的 `start`–`end` 区间内完成，旁白讲到哪一步，画面就演示到哪一步。揭示要跟着旁白逐步发生，不要开头一次性把内容全摆出来然后静止。
2. **字幕**：按 `audio/captions.json` 逐句显示在画面下方居中，最多两行，字号不小于 40px，带柔和的半透明底，不遮挡主体内容。
3. **视觉品质**：沿用分镜里的 `visual_style`。大留白、清晰的层级、统一的圆角与阴影；正文字号不小于 36px，画面四周至少留 96px 安全边距；转场 0.4–0.8 秒，缓动自然（如 power3、expo），不要生硬闪切，也不要满屏乱动。
4. **中文字体**：用 `@font-face` 声明本机字体，例如 `@font-face { font-family: "PingFang SC"; src: local("PingFang SC"); }`，再在样式里使用。
5. **确定性**：不用 `Date.now()`、`Math.random()`，不从网络加载任何资源（不用 CDN）；需要的库只用 `video/vendor/` 里的本地文件。

## 检查与渲染

1. 写完后运行 `hyperframes lint video`，修掉所有错误。
2. 运行 `hyperframes snapshot video --at <每一镜中点的秒数，用逗号分隔> -o out/snapshots`，然后逐张查看截图（用读取文件的方式打开 PNG）。重点检查：文字溢出、重叠或被裁切；字幕遮挡主体；画面和这一镜的旁白对不上；出现了分镜和资料里没有的事实。有问题就改，再截图复查，最多三轮。
3. 渲染成片：`hyperframes render video --output out/video.mp4 --fps 30 --quality {{quality}} --quiet`。
4. 运行 `learnloop-check out/video.mp4`，它必须输出 `OK`；如果报错，按提示修正后重新渲染。
5. 最后写 `out/result.json`：

```json
{
  "title": "视频标题",
  "engine": "hyperframes",
  "chapters": [{"start": 0, "title": "镜头标题"}],
  "notes": "自查发现并修复了哪些问题，不超过 120 字"
}
```

完成以上步骤后结束。如果遇到无法解决的问题，把原因用一两句话写进 `out/error.txt` 后结束，不要反复重试同一个失败的命令。
