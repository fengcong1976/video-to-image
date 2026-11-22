# 视频转图片／动图工具 — 第三方组件与许可声明

本应用整体以 **GPL-3.0** 发布（见 LICENSE），源码公开：
https://gitee.com/FC1976/video-to-image
GitHub 镜像：https://github.com/fengcong1976/video-to-image

本应用以动态链接方式使用 Qt 6 / PySide6（LGPL-3.0），Qt 运行库以独立 DLL 随包分发，
用户可以自行替换。

| 组件 | 许可 | 来源 / 源码 |
|---|---|---|
| PySide6 6.12.0 | LGPL-3.0 | https://www.qt.io/ |
| Qt 6 | LGPL-3.0 | https://www.qt.io/ |
| shiboken6 6.12.0 | LGPL-3.0 | https://www.qt.io/ |
| Qt 6 | LGPL-3.0 | https://www.qt.io/ |
| shiboken6 6.12.0 | LGPL-3.0 | https://www.qt.io/ |
| FFmpeg（随包 GPL 构建） | GPL-3.0 | https://ffmpeg.org/download.html |

> 随包 FFmpeg 为 GPL-3.0 构建。对应源码可从 https://ffmpeg.org/download.html 获取；
> 如需与该二进制完全一致的源码及编译参数，请在 3 年内联系 1045117396@qq.com 免费获取。

## 其他随包组件

| 组件 | 许可 | 来源 / 源码 |
|---|---|---|
| OpenCV 5.0.0.93 | Apache-2.0 | https://opencv.org/ |
| FFmpeg（OpenCV videoio 内置） | LGPL-2.1-or-later | https://ffmpeg.org/ |
| NumPy 2.2.6 | BSD-3-Clause | https://numpy.org/ |
| Pillow 12.3.0 | HPND | https://python-pillow.org/ |

## 许可全文

安装目录下的 `LICENSES/` 存放 LGPL-3.0 全文、Qt 声明，以及 FFmpeg 等第三方组件说明。

## 其余 Python 依赖

未在上表列出的 Python 依赖，其许可见各自 PyPI 元数据。
