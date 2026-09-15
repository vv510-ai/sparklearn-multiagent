# 本机 API 配置与激活

实际项目环境文件：`C:\Users\26054\Desktop\SparkLearn星火学伴\sparklearn-multiagent\.env`。

1. 在该文件更新`OPENAI_API_KEY`。官方服务使用`OPENAI_BASE_URL=https://api.openai.com/v1`；如果使用其他服务商提供的兼容端点，须核实其真实模型标识及Responses、图像、音频接口支持，不能只因兼容聊天接口就视为全部兼容。
2. 合并[quality-profile.env](quality-profile.env)中对应能力的非秘密配置，替换同名旧值，避免保留旧的`OPENAI_IMAGE_MODEL=gpt-image-2`。保留数据库、认证和存储字段。后端需要重启才能加载新配置。
3. OpenAI额度和Ark权限是两件事。只有Ark账号开通`doubao-seedance-2-5-260628`并真实创建成功后，才将`VIDEO_PROVIDER`设为`ark`；此前保留`xiaoyunque`。ElevenLabs是可选路线，需要另配密钥与有授权的音色。
4. 从实际仓库的`backend`目录运行下列命令。默认只查模型目录；`--live`会提交少量真实生成并产生服务商费用。每项先验收再测下一项，失败后不批量重试。

```powershell
.venv\Scripts\python.exe -X utf8 scripts\verify_quality_apis.py
.venv\Scripts\python.exe -X utf8 scripts\verify_quality_apis.py --live text
.venv\Scripts\python.exe -X utf8 scripts\verify_quality_apis.py --live image
.venv\Scripts\python.exe -X utf8 scripts\verify_quality_apis.py --live tts
.venv\Scripts\python.exe -X utf8 scripts\verify_quality_apis.py --live ppt
```

模型目录返回200只说明可读取目录。真实图像还应检查文字、结构与教学正确性；语音需要播放试听；视觉和语音输入应从页面上传合成测试材料验收。视频成功提交后先保存任务ID并轮询，不能反复创建付费任务来代替查询。

本机修改不会自动上传到生产环境。生产环境文件是`/opt/sparklearn/shared/.env`，需要私密同步相关配置并在ECS验证连通性、模型权限和核心学习流程后切换。任何密钥都不要发到聊天或提交到Git。
