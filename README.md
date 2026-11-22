# video-to-image

视频转图片/动图工具可将本地视频按指定时间段抽帧导出为图片序列，也可合成 GIF 或 WebP 动图。内置播放器可预览画面、拖动进度并一键设为起点终点；支持自定义帧率、输出尺寸、JPG 质量与文件名模板，并能同时导出所选片段的声音。动图模式提供 AI 去背景、透明或纯色背景、循环次数、颜色数、合并静止帧与画面加字，导出前可快速预览效果，动图默认 240×240 并等比缩放置中，输出目录可自行指定，图片序列与动图各自记住尺寸设置，导出完成后会提示文件保存位置，适合制作表情包、教程配图与短视频素材。 本应用已开源（GPL-3.0）：https://gitee.com/FC1976/video-to-image（GitHub 镜像：https://github.com/fengcong1976/video-to-image）。

## 运行

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py
```

构建与安装包脚本见仓库内的 `.spec`、`.iss` 与 `build*.bat`。

## 许可

GPL-3.0，详见 LICENSE。第三方组件声明见 THIRD_PARTY_NOTICES.md。

## 仓库说明

本仓库只包含源码，以下运行时资源体积较大，未纳入仓库：

- models/u2net.onnx 由同级项目「AI去背景工具」提供：请自行准备后放到 ../AI去背景工具/models/。
