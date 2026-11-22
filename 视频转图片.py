# -*- coding: utf-8 -*-
"""视频转图片/动图工具 v2.0

功能：
- 选择/拖拽视频文件，显示视频信息，支持播放、进度条拖动预览
- 设置时间段（或全部），按设置的帧率导出图片序列（jpg/png）
- 按设置的帧率、尺寸、循环次数把视频段导出为 GIF 动图
- 可选同时导出所选片段的声音（mp3/m4a/wav）
"""
import math
import glob
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
import threading

import cv2
from PIL import Image, ImageFilter, ImageDraw, ImageFont
from PySide6.QtCore import Qt, QEvent, QPointF, QRectF, QThread, QTimer, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QDragEnterEvent, QDropEvent,
                         QFont, QIcon, QImage, QPainter, QPainterPath, QPen,
                         QPixmap, QMovie)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSlider, QSpinBox,
    QStatusBar, QVBoxLayout, QWidget,
)

from about_dialog import show_about
from version import VERSION as APP_VERSION

VIDEO_EXTS = "视频文件 (*.mp4 *.avi *.mkv *.mov *.flv *.wmv *.webm *.ts *.m4v);;所有文件 (*.*)"
VIDEO_EXT_SET = {".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".ts", ".m4v"}


def make_filename(template, video_stem, index, total, ext):
    """根据模板生成输出文件名

    支持的占位符：
      {名称} → 视频文件名（不含扩展名）
      {序号} → 序列号（1 开始，自动补零）
    """
    pad = max(4, len(str(total)))
    seq = str(index).zfill(pad)
    name = template.replace("{名称}", video_stem).replace("{序号}", seq)
    return f"{name}.{ext}"


def fmt_time(sec: float) -> str:
    """把秒格式化为 时:分:秒.毫秒"""
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def get_video_info(path: str):
    """读取视频基本信息，失败返回 None"""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    info = {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    cap.release()
    if info["width"] <= 0 or info["height"] <= 0:
        return None
    if info["fps"] <= 0 or not math.isfinite(info["fps"]):
        info["fps"] = 25.0  # 某些容器读不到帧率时的兜底值
    if info["frames"] <= 0:
        info["frames"] = 0
    info["duration"] = info["frames"] / info["fps"] if info["frames"] else 0.0
    return info


def extract_frames(video_path, out_dir, start_sec, end_sec, target_fps,
                   out_size, img_format, quality, filename_template,
                   progress_cb=None, cancel_cb=None):
    """按帧率抽取视频段保存为图片

    out_size: None 表示原始大小，否则 (w, h)
    filename_template: 文件名模板，支持 {名称} {序号}
    返回 (保存张数, 是否被取消)
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("无法打开视频文件")
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if src_fps <= 0 or not math.isfinite(src_fps):
        src_fps = 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    start_f = max(0, int(round(start_sec * src_fps)))
    end_f = total if end_sec is None else min(total, int(round(end_sec * src_fps)))
    if end_f <= start_f:
        cap.release()
        raise RuntimeError("所选时间段内没有帧，请检查开始/结束时间")

    fps = min(target_fps, src_fps)  # 源帧率是上限，超过没有意义
    step = src_fps / fps if fps > 0 else 1.0
    est_total = max(1, int((end_f - start_f - 1) // step) + 1)

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video_path))[0]
    params = ([cv2.IMWRITE_JPEG_QUALITY, int(quality)] if img_format == "jpg"
              else [cv2.IMWRITE_PNG_COMPRESSION, 3])
    ext = "jpg" if img_format == "jpg" else "png"

    saved = 0
    cancelled = False
    next_target = float(start_f)
    pos = start_f
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
    while True:
        if cancel_cb is not None and cancel_cb():
            cancelled = True
            break
        ok, frame = cap.read()
        if not ok or pos >= end_f:
            break
        if pos >= next_target:
            w, h = out_size if out_size else (frame.shape[1], frame.shape[0])
            if (w, h) != (frame.shape[1], frame.shape[0]):
                interp = cv2.INTER_AREA if w * h < frame.shape[0] * frame.shape[1] else cv2.INTER_LINEAR
                frame = cv2.resize(frame, (w, h), interpolation=interp)
            fname = make_filename(filename_template, stem, saved + 1, est_total, ext)
            out_path = os.path.join(out_dir, fname)
            okenc, buf = cv2.imencode("." + ext, frame, params)
            if not okenc:
                cap.release()
                raise RuntimeError(f"图片编码失败: {out_path}")
            buf.tofile(out_path)  # 兼容中文/Unicode 路径
            saved += 1
            if progress_cb is not None:
                progress_cb(saved, est_total)
            next_target = start_f + saved * step
        pos += 1
    cap.release()
    return saved, cancelled


def find_ffmpeg():
    """优先用系统 ffmpeg，其次 imageio-ffmpeg 自带的，都找不到返回 None"""
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def extract_audio(video_path, out_dir, start_sec, end_sec, fmt, ffmpeg_exe):
    """用 ffmpeg 抽取视频段的声音

    返回 (输出文件路径或None, 提示信息)
    """
    stem = os.path.splitext(os.path.basename(video_path))[0]
    out_path = os.path.join(out_dir, f"{stem}_音频.{fmt}")
    os.makedirs(out_dir, exist_ok=True)
    cmd = [ffmpeg_exe, "-y", "-loglevel", "error"]
    if start_sec > 0:
        cmd += ["-ss", f"{start_sec:.3f}"]
    cmd += ["-i", video_path]
    if end_sec is not None:
        cmd += ["-t", f"{max(0.001, end_sec - start_sec):.3f}"]
    cmd += ["-vn"]  # 不要视频流
    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-q:a", "2"]
    elif fmt == "m4a":
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:  # wav
        cmd += ["-c:a", "pcm_s16le"]
    cmd += [out_path]
    try:
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW，避免弹出控制台
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              creationflags=flags, timeout=600)
    except subprocess.TimeoutExpired:
        return None, "声音导出超时，已跳过"
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        if "does not contain any stream" in err or "matched no streams" in err:
            return None, "视频中未检测到音轨，未导出声音"
        last = err.splitlines()[-1] if err else "未知错误"
        return None, f"声音导出失败: {last}"
    return out_path, ""


GIF_ALPHA_THRESHOLD = 128     # 低于此 alpha 视为完全透明（与表情包生成器一致）
GIF_TRANSPARENT_INDEX = 255   # GIF 调色板透明索引（与表情包生成器一致）
GIF_BG_COLORS = {"透明": (0, 0, 0, 0), "白色": (255, 255, 255, 255), "黑色": (0, 0, 0, 255)}

# AI 去背景：内置 u2net 模型 + onnxruntime 直连推理（管线与 rembg 一致，
# 与表情包生成器同一方案，无需 rembg 库、无需联网下载模型）
_rembg_lock = threading.Lock()
_rembg_session = None


def _setup_model_dir():
    """配置 u2net 模型目录：优先用打包内置/相邻项目的模型，避免用户联网下载（约168MB）。"""
    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        here = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        exe_dir = os.path.dirname(sys.executable)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        exe_dir = here
    candidates = [
        os.path.normpath(os.path.join(exe_dir, "..", "AI去背景工具", "models")),
        os.path.join(exe_dir, "models"),
        os.path.join(here, "models"),
    ]
    for d in candidates:
        if os.path.isfile(os.path.join(d, "u2net.onnx")):
            os.environ["U2NET_HOME"] = d
            return
    os.environ["U2NET_HOME"] = os.path.join(
        os.path.expanduser("~"), ".u2net")  # 兜底：用户主目录（rembg 默认位置）


_setup_model_dir()


def _get_rembg():
    """加载内置 u2net 模型（仅初始化一次）。"""
    global _rembg_session
    with _rembg_lock:
        if _rembg_session is None:
            import onnxruntime
            model = os.path.join(os.environ.get("U2NET_HOME", ""), "u2net.onnx")
            if not os.path.isfile(model):
                raise RuntimeError("未找到内置 AI 模型：" + model)
            _rembg_session = onnxruntime.InferenceSession(
                model, providers=["CPUExecutionProvider"])
    return _rembg_session


def _run_rembg(im):
    """内置 u2net 抠图：管线与 rembg 一致，仅依赖 numpy + onnxruntime。"""
    import numpy as np
    session = _get_rembg()
    w, h = im.size
    rgb = im.convert("RGB").resize((320, 320), Image.LANCZOS)
    ary = np.asarray(rgb, dtype=np.float32)
    ary /= max(float(ary.max()), 1e-6)
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    x = ((ary - mean) / std).transpose(2, 0, 1)[None].astype(np.float32)
    pred = session.run(None, {session.get_inputs()[0].name: x})[0][:, 0, :, :]
    pred = (pred - pred.min()) / (pred.max() - pred.min())
    pred = np.squeeze(pred).clip(0, 1)
    mask = Image.fromarray((pred * 255).astype("uint8"), mode="L")
    mask = mask.resize((w, h), Image.LANCZOS)
    mask = mask.filter(ImageFilter.GaussianBlur(1.0))  # 轻微平滑边缘
    rgba = im.convert("RGBA")
    rgba.putalpha(mask)
    return rgba


def _gif_fit_center(im, size):
    """等比缩放（允许放大）到恰好填入 size 的内接矩形并居中（同表情包生成器）"""
    s = min(size[0] / im.width, size[1] / im.height)
    im = im.resize((max(int(im.width * s), 1), max(int(im.height * s), 1)),
                   Image.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.alpha_composite(im, ((size[0] - im.width) // 2,
                                (size[1] - im.height) // 2))
    return canvas


# ---- 字幕颜色：颜色名 -> (文字色 RGB, 描边色 RGB)，描边保证任何背景都清晰 ----
TEXT_COLORS = {
    "白色": ((255, 255, 255), (20, 20, 20)),
    "黑色": ((0, 0, 0), (255, 255, 255)),
    "黄色": ((255, 222, 0), (20, 20, 20)),
    "红色": ((255, 70, 70), (255, 255, 255)),
    "蓝色": ((64, 158, 255), (255, 255, 255)),
}


def _load_caption_font(size):
    """加载字幕字体（微软雅黑粗体，逐级回退）"""
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(os.path.join(fonts_dir, name), size)
        except Exception:
            continue
    return ImageFont.load_default()


# ---- 字幕预设位置：位置名 -> (中心 x, 中心 y)（相对画面宽高 0~1，可被鼠标拖动覆盖）----
CAPTION_PRESETS = {
    "底部居中": (0.5, 0.93),
    "顶部居中": (0.5, 0.09),
    "左上角": (0.09, 0.09),
    "右上角": (0.91, 0.09),
}


def _draw_text_overlay(im, text, xy, scale, color_name):
    """把字幕文字画到帧图片上（烧录进像素，同微信表情加字原理）

    xy: 文字中心位置（相对画面宽高 0~1，来自鼠标拖动或预设）
    scale: 字号（相对画面高度的比例，来自滚轮调节）
    """
    w, h = im.size
    fill, stroke = TEXT_COLORS.get(color_name, TEXT_COLORS["白色"])
    fsize = max(9, min(200, int(scale * h)))
    font = _load_caption_font(fsize)
    sw = max(2, fsize // 8)    # 描边宽度随字号缩放
    draw = ImageDraw.Draw(im)
    draw.text((xy[0] * w, xy[1] * h), text, font=font, fill=fill, anchor="mm",
              stroke_width=sw, stroke_fill=stroke)
    return im


def _gif_to_palette(rgba, colors=GIF_TRANSPARENT_INDEX):
    """RGBA -> GIF 调色板模式，透明区域使用固定索引（同表情包生成器）

    colors: 调色板颜色数（需 <= 255，留出索引 255 作透明色）
    """
    alpha = rgba.getchannel("A")
    mask = alpha.point(lambda a: 255 if a < GIF_ALPHA_THRESHOLD else 0)
    p = rgba.convert("RGB").convert("P", palette=Image.ADAPTIVE,
                                    colors=max(2, int(colors)))
    p.paste(GIF_TRANSPARENT_INDEX, mask)
    p.info["transparency"] = GIF_TRANSPARENT_INDEX
    return p


def make_gif(video_path, out_dir, start_sec, end_sec, fps, out_size,
             loop, optimize, bg, remove_bg=False,
             progress_cb=None, cancel_cb=None, phase_cb=None,
             fmt="gif", quality=80, colors=256, dedup=True,
             text=None, text_xy=(0.5, 0.93), text_scale=0.10, text_color="白色"):
    """视频段 → GIF/WebP 动图：先按抽帧频率抽取帧临时保存为 PNG，再用 PIL 合成
    （GIF 合成流程与表情包生成器一致：fit_center 等比缩放置中 → 调色板 → save_all）

    fps: 抽帧频率（帧/秒），默认 10 即每帧间隔 100ms；源帧率为上限
    out_size: None 表示原始大小，否则 (w, h)，等比缩放置中
    loop: 0 表示无限循环，N 表示额外循环 N 次
    optimize: 是否优化体积（仅 GIF 生效）
    bg: "透明" / "白色" / "黑色"，仅影响留白区域
    remove_bg: AI 去背景（rembg/u2net），配合透明背景可得到透明底动图
    fmt: "gif" 或 "webp"（WebP 直接存 RGBA，支持有损质量参数，体积远小于 GIF）
    quality: WebP 有损压缩质量（10~100），仅 fmt="webp" 时生效
    colors: GIF 调色板颜色数（256/128/64/32），越少体积越小，仅 fmt="gif" 时生效
    dedup: 合并静止帧——画面完全相同的连续帧合并为一帧（时长累加）
    text: 字幕文字（None/空串不加），画到每一帧画面上（烧录进像素）
    text_xy: 字幕中心位置（相对画面宽高 0~1，由鼠标拖动或预设下拉决定）
    text_scale: 字号（相对画面高度比例，由滚轮调节，默认 0.10）
    text_color: 字幕颜色（白色/黑色/黄色/红色/蓝色），自动加对比色描边
    返回 (输出文件路径, 是否被取消)
    """
    stem = os.path.splitext(os.path.basename(video_path))[0]
    out_path = os.path.join(out_dir, f"{stem}{'.webp' if fmt == 'webp' else '.gif'}")
    os.makedirs(out_dir, exist_ok=True)

    bg_rgba = GIF_BG_COLORS.get(bg, GIF_BG_COLORS["透明"])
    transparent = bg_rgba[3] == 0
    delay_ms = max(10, int(round(1000.0 / max(float(fps), 0.1))))

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("无法打开视频文件")
    temp_dir = tempfile.mkdtemp(prefix="v2i_gif_")
    try:
        src_fps = cap.get(cv2.CAP_PROP_FPS)
        if src_fps <= 0 or not math.isfinite(src_fps):
            src_fps = 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        target_fps = min(float(fps), src_fps)  # 源帧率是上限，超过没有意义
        start_f = max(0, int(round(start_sec * src_fps)))
        end_f = total if end_sec is None else min(total, int(round(end_sec * src_fps)))
        if end_f <= start_f:
            raise RuntimeError("所选时间段内没有帧，请检查开始/结束时间")
        step = src_fps / target_fps if target_fps > 0 else 1.0
        est_total = max(1, int((end_f - start_f - 1) // step) + 1)

        # ---- 阶段 1：抽帧，临时保存为 PNG（无损中间结果）----
        # dedup 开启时，画面完全相同的连续帧不重复存盘，只累计重复次数 repeats[i]
        pngs = []
        repeats = []
        cancelled = False
        saved = 0          # 实际保存的不同帧数
        processed = 0      # 已处理的抽帧数（含被合并的重复帧）
        prev_bytes = None  # 上一保留帧的像素字节（用于静止帧比较）
        next_target = float(start_f)
        pos = start_f
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
        if phase_cb is not None:
            phase_cb("正在抽取帧并临时保存 PNG…")
        if remove_bg and phase_cb is not None:
            phase_cb("正在加载 AI 去背景模型…")
        while True:
            if cancel_cb is not None and cancel_cb():
                cancelled = True
                break
            ok, frame = cap.read()
            if not ok or pos >= end_f:
                break
            if pos >= next_target:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                im = Image.fromarray(rgb).convert("RGBA")
                if remove_bg:
                    im = _run_rembg(im)
                if out_size:
                    im = _gif_fit_center(im, out_size)  # 等比缩放置中
                if not transparent:  # 不透明背景：合成纯色底
                    canvas = Image.new("RGBA", out_size or im.size, bg_rgba)
                    canvas.alpha_composite(im)
                    im = canvas
                if text:  # 字幕最后画，保证盖在所有内容之上
                    im = _draw_text_overlay(im, text, text_xy, text_scale, text_color)
                if dedup:
                    b = im.tobytes()
                    if b == prev_bytes:  # 与上一帧完全相同：合并，时长累加
                        repeats[-1] += 1
                        processed += 1
                        if progress_cb is not None:
                            progress_cb(processed, est_total)
                        pos += 1
                        continue  # next_target 不变，继续合并后续相同帧
                    prev_bytes = b
                png_path = os.path.join(temp_dir, f"{saved:06d}.png")
                im.save(png_path)  # PNG 无损保留透明通道
                pngs.append(png_path)
                repeats.append(1)
                saved += 1
                processed += 1
                if progress_cb is not None:
                    progress_cb(processed, est_total)
                next_target = start_f + saved * step
            pos += 1

        if cancelled or not pngs:
            return out_path, cancelled

        # ---- 阶段 2：读取 PNG 序列合成动图 ----
        if phase_cb is not None:
            phase_cb("正在合成动图…")
        frames = []
        for p in pngs:
            with Image.open(p) as im:
                if fmt == "webp":
                    # WebP 直接保留 RGBA（无需量化调色板），不透明底时可丢弃 alpha 减小体积
                    frames.append(im.convert("RGBA" if transparent else "RGB"))
                elif transparent:
                    frames.append(_gif_to_palette(im.convert("RGBA"),
                                                  colors=min(colors, 255)))
                else:
                    rgb = im.convert("RGB")
                    # 颜色数 < 256 时先量化，减小调色板体积
                    frames.append(rgb.convert("P", palette=Image.ADAPTIVE,
                                              colors=colors) if colors < 256 else rgb)
        if progress_cb is not None:
            progress_cb(est_total, est_total)
        # 每帧时长 = 基础间隔 × 该画面连续出现的次数（合并静止帧时 > 1）
        delay_list = [delay_ms * r for r in repeats]
        if fmt == "webp":
            frames[0].save(
                out_path,
                save_all=True,
                append_images=frames[1:],
                duration=delay_list,
                loop=int(loop),
                quality=int(quality),
                method=4,  # 压缩与速度的平衡档：method=6 编码慢数倍，体积仅再小几个百分点
            )
        else:
            frames[0].save(
                out_path,
                save_all=True,
                append_images=frames[1:],
                duration=delay_list,
                loop=int(loop),
                disposal=2,
                optimize=bool(optimize) and not transparent,
            )
        return out_path, False
    finally:
        cap.release()
        shutil.rmtree(temp_dir, ignore_errors=True)  # 清理临时 PNG


class ExtractWorker(QThread):
    """后台导出线程"""
    progress = Signal(int, int)
    phase = Signal(str)                 # 阶段提示（如"正在导出声音…"）
    done = Signal(int, bool, str, str)  # 保存张数, 是否取消, 输出目录, 声音导出提示
    failed = Signal(str)

    def __init__(self, video_path, out_dir, start_sec, end_sec, fps,
                 out_size, img_format, quality, filename_template,
                 export_audio, audio_fmt, ffmpeg_exe):
        super().__init__()
        self.video_path = video_path
        self.out_dir = out_dir
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.fps = fps
        self.out_size = out_size
        self.img_format = img_format
        self.quality = quality
        self.filename_template = filename_template
        self.export_audio = export_audio
        self.audio_fmt = audio_fmt
        self.ffmpeg_exe = ffmpeg_exe
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            saved, cancelled = extract_frames(
                self.video_path, self.out_dir, self.start_sec, self.end_sec,
                self.fps, self.out_size, self.img_format, self.quality,
                self.filename_template,
                progress_cb=lambda c, t: self.progress.emit(c, t),
                cancel_cb=lambda: self._cancelled,
            )
            audio_note = ""
            if self.export_audio and not cancelled:
                self.phase.emit("正在导出声音…")
                _, audio_note = extract_audio(
                    self.video_path, self.out_dir, self.start_sec,
                    self.end_sec, self.audio_fmt, self.ffmpeg_exe)
            self.done.emit(saved, cancelled, self.out_dir, audio_note)
        except Exception as e:
            self.failed.emit(str(e))


class GifWorker(QThread):
    """后台动图导出线程（GIF / WebP）"""
    progress = Signal(int, int)
    phase = Signal(str)        # 阶段提示（如模型加载）
    done = Signal(str, bool)   # 输出文件, 是否取消
    failed = Signal(str)

    def __init__(self, video_path, out_dir, start_sec, end_sec, fps,
                 out_size, loop, optimize, bg, remove_bg,
                 fmt="gif", quality=80, colors=256, dedup=True,
                 text=None, text_xy=(0.5, 0.93), text_scale=0.10,
                 text_color="白色"):
        super().__init__()
        self.video_path = video_path
        self.out_dir = out_dir
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.fps = fps
        self.out_size = out_size
        self.loop = loop
        self.optimize = optimize
        self.bg = bg
        self.remove_bg = remove_bg
        self.fmt = fmt
        self.quality = quality
        self.colors = colors
        self.dedup = dedup
        self.text = text
        self.text_xy = text_xy
        self.text_scale = text_scale
        self.text_color = text_color
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            out_path, cancelled = make_gif(
                self.video_path, self.out_dir, self.start_sec, self.end_sec,
                self.fps, self.out_size, self.loop, self.optimize,
                self.bg, self.remove_bg,
                progress_cb=lambda c, t: self.progress.emit(c, t),
                cancel_cb=lambda: self._cancelled,
                phase_cb=lambda s: self.phase.emit(s),
                fmt=self.fmt, quality=self.quality,
                colors=self.colors, dedup=self.dedup,
                text=self.text, text_xy=self.text_xy,
                text_scale=self.text_scale, text_color=self.text_color,
            )
            self.done.emit(out_path, cancelled)
        except Exception as e:
            self.failed.emit(str(e))


GIF_PREVIEW_MAX_FRAMES = 48   # 预览最多帧数（超过则自动拉大帧间隔抽稀）
GIF_PREVIEW_MAX_WIDTH = 320   # 预览最大宽度（原始大小模式下等比缩小）
GIF_PREVIEW_SEQ = itertools.count(1)  # 预览文件唯一序号（QMovie 占用旧文件时避免覆盖失败）


class GifPreviewWorker(QThread):
    """后台 GIF 快速预览线程：按当前设置生成小尺寸预览 GIF，不写输出目录"""
    done = Signal(str, bool)   # 预览文件, 是否取消
    failed = Signal(str)

    def __init__(self, video_path, start_sec, end_sec, fps,
                 out_size, loop, optimize, bg, remove_bg,
                 text=None, text_xy=(0.5, 0.93), text_scale=0.10,
                 text_color="白色"):
        super().__init__()
        self.video_path = video_path
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.fps = fps
        self.out_size = out_size
        self.loop = loop
        self.optimize = optimize
        self.bg = bg
        self.remove_bg = remove_bg
        self.text = text
        self.text_xy = text_xy
        self.text_scale = text_scale
        self.text_color = text_color
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            dur = self.end_sec - self.start_sec
            fps = max(float(self.fps), 0.1)
            # 帧数超限时降低抽帧频率，保证预览快速
            if dur > 0 and dur * fps > GIF_PREVIEW_MAX_FRAMES:
                fps = GIF_PREVIEW_MAX_FRAMES / dur
            size = self.out_size
            if size is None:
                info = get_video_info(self.video_path)
                size = (info["width"], info["height"]) if info else None
            if size and size[0] > GIF_PREVIEW_MAX_WIDTH:  # 等比缩小到最大宽度
                h = max(1, int(size[1] * GIF_PREVIEW_MAX_WIDTH / size[0]))
                size = (GIF_PREVIEW_MAX_WIDTH, h)
            target = os.path.join(
                os.environ.get("TEMP", os.path.dirname(os.path.abspath(__file__))),
                f"v2i_gif_preview_{next(GIF_PREVIEW_SEQ)}.gif")
            out_path, cancelled = make_gif(
                self.video_path, os.path.dirname(target),
                self.start_sec, self.end_sec, fps, size,
                self.loop, self.optimize, self.bg, self.remove_bg,
                cancel_cb=lambda: self._cancelled,
                phase_cb=lambda s: None,
                text=self.text, text_xy=self.text_xy,
                text_scale=self.text_scale, text_color=self.text_color,
            )
            if not cancelled:
                if os.path.abspath(out_path) != os.path.abspath(target):
                    os.replace(out_path, target)
            self.done.emit(target, cancelled)
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"视频转图片/动图工具 v{APP_VERSION}")
        self.resize(880, 620)
        self.video_path = None
        self.info = None
        self.worker = None
        self._updating_size = False
        self.cap = None             # 播放器专用 VideoCapture
        self._current_frame = None  # 当前显示的帧
        self._dragging = False
        self._was_playing = False
        self._pending_seek = None
        self._auto_dir = ""          # 自动生成的输出目录，用于判断用户是否手动改过
        self._size_mode_key = "img"  # 当前尺寸设置所属的输出模式
        self._size_cache = {"img": None, "gif": None}
        self.preview_worker = None   # GIF 预览线程
        self._gif_movie = None       # QMovie 预览
        self._clean_old_previews()
        self.setAcceptDrops(True)

    def _clean_old_previews(self):
        """启动时清理上次遗留的预览临时文件与抽帧临时目录"""
        temp = os.environ.get("TEMP", "")
        if temp:
            for f in glob.glob(os.path.join(temp, "v2i_gif_preview*")):
                try:
                    os.remove(f)
                except OSError:
                    pass
            for d in glob.glob(os.path.join(temp, "v2i_gif_*")):
                if os.path.isdir(d):
                    shutil.rmtree(d, ignore_errors=True)

        # 应用图标（图标.png 与主程序同目录）
        self._icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "图标.png")
        icon_path = self._icon_path
        if os.path.exists(icon_path):
            self._app_icon = QIcon(icon_path)
            if not self._app_icon.isNull():
                self.setWindowIcon(self._app_icon)
            else:
                self._app_icon = None
        else:
            self._app_icon = None

        # 帮助菜单
        help_menu = self.menuBar().addMenu("帮助")
        act_help = QAction("使用说明", self)
        act_help.triggered.connect(self.show_help)
        help_menu.addAction(act_help)
        act_about = QAction("关于", self)
        act_about.triggered.connect(self.show_about)
        help_menu.addAction(act_about)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        body = QHBoxLayout()
        root.addLayout(body, stretch=1)

        # ---------- 左侧：预览与播放器 ----------
        left = QVBoxLayout()
        body.addLayout(left, stretch=5)
        self.preview = QLabel("拖拽视频到此处\n或点击右侧「选择视频文件」")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 320)
        self.preview.setStyleSheet("background:#202020;color:#aaa;font-size:14px;border-radius:4px;")
        self.preview.setScaledContents(False)
        left.addWidget(self.preview, stretch=1)
        # 字幕交互状态：位置/字号由鼠标拖动和滚轮调节（相对画面 0~1）
        self.caption_xy = [0.5, 0.93]
        self.caption_scale = 0.10
        self._cap_drag = None      # 拖动中：(dx, dy) 抓取点相对文字中心的偏移（归一化）
        self._cap_rect = None      # 当前帧字幕包围盒（预览图坐标）
        self._pm_off = (0, 0)      # 预览图在 QLabel 内的偏移
        self._pm_size = (0, 0)     # 预览图尺寸
        self.preview.installEventFilter(self)
        self.preview.setMouseTracking(True)

        # GIF 预览时的"关闭预览"浮动按钮（预览区右上角）
        self.btn_close_preview = QPushButton("✕ 关闭预览，回到视频", self.preview)
        self.btn_close_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close_preview.setStyleSheet(
            "QPushButton{background:rgba(30,30,30,200);color:#fff;"
            "border:1px solid #666;border-radius:4px;padding:4px 10px;font-size:13px;}"
            "QPushButton:hover{background:rgba(60,60,60,230);}")
        self.btn_close_preview.hide()
        self.btn_close_preview.clicked.connect(self._on_close_preview)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self.on_slider_pressed)
        self.slider.sliderReleased.connect(self.on_slider_released)
        self.slider.valueChanged.connect(self.on_slider_value_changed)
        left.addWidget(self.slider)

        ctrl = QHBoxLayout()
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setFixedWidth(92)
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_set_start = QPushButton("设为起点")
        self.btn_set_start.setToolTip("把当前播放位置设置为导出时间段的开始时间")
        self.btn_set_start.clicked.connect(self.set_start_from_player)
        self.btn_set_end = QPushButton("设为终点")
        self.btn_set_end.setToolTip("把当前播放位置设置为导出时间段的结束时间")
        self.btn_set_end.clicked.connect(self.set_end_from_player)
        self.lbl_time = QLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_time.setStyleSheet("color:#444;")
        ctrl.addWidget(self.btn_play)
        ctrl.addWidget(self.btn_set_start)
        ctrl.addWidget(self.btn_set_end)
        ctrl.addStretch(1)
        ctrl.addWidget(self.lbl_time)
        left.addLayout(ctrl)

        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self.next_frame)
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(60)
        self._seek_timer.timeout.connect(self._do_pending_seek)

        # ---------- 右侧：设置 ----------
        right = QVBoxLayout()
        body.addLayout(right, stretch=4)

        # 视频选择
        grp_video = QGroupBox("1. 选择视频")
        form_video = QVBoxLayout(grp_video)
        row = QHBoxLayout()
        self.btn_pick = QPushButton("选择视频文件…")
        self.btn_pick.clicked.connect(self.pick_video)
        row.addWidget(self.btn_pick)
        row.addStretch(1)
        form_video.addLayout(row)
        self.lbl_video = QLabel("未选择")
        self.lbl_video.setWordWrap(True)
        form_video.addWidget(self.lbl_video)
        self.lbl_info = QLabel("分辨率 - | 帧率 - | 时长 - | 总帧数 -")
        self.lbl_info.setStyleSheet("color:#444;")
        form_video.addWidget(self.lbl_info)
        right.addWidget(grp_video)

        # 时间段
        grp_range = QGroupBox("2. 选择时间段（不勾选全部时生效）")
        grid_range = QGridLayout(grp_range)
        self.chk_full = QCheckBox("全部视频")
        self.chk_full.setChecked(True)
        self.chk_full.stateChanged.connect(self.on_range_changed)
        grid_range.addWidget(self.chk_full, 0, 0, 1, 2)
        grid_range.addWidget(QLabel("开始时间(秒)"), 1, 0)
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setDecimals(3)
        self.spin_start.setRange(0, 1e9)
        self.spin_start.setValue(0)
        self.spin_start.setFixedWidth(110)
        self.spin_start.valueChanged.connect(self.on_start_changed)
        grid_range.addWidget(self.spin_start, 1, 1)
        grid_range.addWidget(QLabel("结束时间(秒)"), 2, 0)
        self.spin_end = QDoubleSpinBox()
        self.spin_end.setDecimals(3)
        self.spin_end.setRange(0, 1e9)
        self.spin_end.setFixedWidth(110)
        self.spin_end.valueChanged.connect(self.on_end_changed)
        grid_range.addWidget(self.spin_end, 2, 1)
        self.lbl_time_fmt = QLabel("")
        self.lbl_time_fmt.setStyleSheet("color:#666;")
        grid_range.addWidget(self.lbl_time_fmt, 3, 0, 1, 2)
        right.addWidget(grp_range)

        # 输出设置
        grp_out = QGroupBox("3. 输出设置")
        form_out = QFormLayout(grp_out)

        self.cmb_out_type = QComboBox()
        self.cmb_out_type.addItems(["图片序列", "GIF 动图", "WebP 动图"])
        self.cmb_out_type.currentIndexChanged.connect(self.on_out_type_changed)
        form_out.addRow("输出类型", self.cmb_out_type)

        # ---- 公共：输出大小 ----
        self.chk_original = QCheckBox("使用视频原始大小")
        self.chk_original.setChecked(True)
        self.chk_original.stateChanged.connect(self.on_original_changed)
        form_out.addRow("", self.chk_original)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("宽"))
        self.spin_w = QSpinBox()
        self.spin_w.setRange(16, 100000)
        self.spin_w.setValue(720)
        self.spin_w.valueChanged.connect(self.on_size_w_changed)
        size_row.addWidget(self.spin_w)
        size_row.addWidget(QLabel("高"))
        self.spin_h = QSpinBox()
        self.spin_h.setRange(16, 100000)
        self.spin_h.setValue(720)
        self.spin_h.valueChanged.connect(self.on_size_h_changed)
        size_row.addWidget(self.spin_h)
        size_row.addStretch(1)
        self.lbl_size = QLabel("输出大小")
        form_out.addRow(self.lbl_size, size_row)

        # ---- 图片序列专用参数 ----
        self.img_panel = QWidget()
        form_img = QFormLayout(self.img_panel)
        form_img.setContentsMargins(0, 0, 0, 0)
        self.spin_fps = QDoubleSpinBox()
        self.spin_fps.setDecimals(2)
        self.spin_fps.setRange(0.01, 1000)
        self.spin_fps.setValue(24.0)
        self.spin_fps.setSuffix(" 帧/秒")
        self.spin_fps.valueChanged.connect(self.update_estimate)
        form_img.addRow("抽帧帧率", self.spin_fps)

        fmt_row = QHBoxLayout()
        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["jpg", "png"])
        self.cmb_format.currentTextChanged.connect(self.update_estimate)
        fmt_row.addWidget(self.cmb_format)
        fmt_row.addWidget(QLabel("jpg质量"))
        self.spin_quality = QSpinBox()
        self.spin_quality.setRange(10, 100)
        self.spin_quality.setValue(95)
        fmt_row.addWidget(self.spin_quality)
        fmt_row.addStretch(1)
        form_img.addRow("输出格式", fmt_row)

        self.edit_filename = QLineEdit("{名称}_{序号}")
        self.edit_filename.setToolTip(
            "文件名模板，支持占位符：\n"
            "  {名称} → 视频文件名（不含扩展名）\n"
            "  {序号} → 序列号（1 开始，自动补零）\n"
            "例如：{名称}_frame_{序号} → 鹦鹉走路_frame_0001.jpg")
        form_img.addRow("文件名模板", self.edit_filename)

        audio_row = QHBoxLayout()
        self.chk_audio = QCheckBox("导出声音")
        self.chk_audio.setToolTip("同时把所选时间段的声音导出为音频文件（需要 ffmpeg，已内置）")
        self.chk_audio.toggled.connect(self.on_audio_toggled)
        audio_row.addWidget(self.chk_audio)
        audio_row.addWidget(QLabel("声音格式"))
        self.cmb_audio_fmt = QComboBox()
        self.cmb_audio_fmt.addItems(["mp3", "m4a", "wav"])
        self.cmb_audio_fmt.setEnabled(False)
        audio_row.addWidget(self.cmb_audio_fmt)
        audio_row.addStretch(1)
        form_img.addRow("", audio_row)
        form_out.addRow(self.img_panel)

        # ---- GIF 专用参数（缺省设置与表情包生成器一致）----
        self.gif_panel = QWidget()
        form_gif = QFormLayout(self.gif_panel)
        form_gif.setContentsMargins(0, 0, 0, 0)
        self.spin_gif_fps = QDoubleSpinBox()
        self.spin_gif_fps.setDecimals(2)
        self.spin_gif_fps.setRange(0.1, 60)
        self.spin_gif_fps.setValue(10.0)
        self.spin_gif_fps.setSuffix(" 帧/秒")
        self.spin_gif_fps.setToolTip(
            "GIF/WebP 抽帧频率：每秒抽取几帧（默认 10 帧/秒 = 每帧间隔 100 毫秒）。\n"
            "越高越流畅、文件越大；超过源帧率时按源帧率抽取")
        self.spin_gif_fps.valueChanged.connect(self.update_estimate)
        form_gif.addRow("抽帧频率", self.spin_gif_fps)

        self.spin_loop = QSpinBox()
        self.spin_loop.setRange(0, 999)
        self.spin_loop.setValue(0)
        self.spin_loop.setSuffix(" 次")
        self.spin_loop.setSpecialValueText("无限循环")
        self.spin_loop.setToolTip("GIF/WebP 循环次数，0 表示无限循环")
        self.spin_loop.valueChanged.connect(self.update_estimate)
        form_gif.addRow("循环次数", self.spin_loop)

        self.chk_gif_remove_bg = QCheckBox("AI 去背景（自动抠图，透明底）")
        self.chk_gif_remove_bg.setChecked(True)
        self.chk_gif_remove_bg.setToolTip(
            "用 AI 自动抠出画面主体并去除背景（模型已内置，本地运行无需联网）。\n"
            "配合透明背景可得到透明底 GIF/WebP；速度较慢，建议用于短片段")
        form_gif.addRow("", self.chk_gif_remove_bg)

        gif_bg_row = QHBoxLayout()
        gif_bg_row.addWidget(QLabel("背景颜色"))
        self.cmb_gif_bg = QComboBox()
        self.cmb_gif_bg.addItems(["透明", "白色", "黑色"])
        self.cmb_gif_bg.setToolTip("仅影响输出尺寸与视频画面宽高比不一致时的留白区域")
        gif_bg_row.addWidget(self.cmb_gif_bg)
        self.chk_gif_optimize = QCheckBox("优化体积")
        self.chk_gif_optimize.setChecked(True)
        self.chk_gif_optimize.setToolTip("GIF 专用：优化帧内存储方式减小体积（透明底时自动失效）")
        gif_bg_row.addWidget(self.chk_gif_optimize)
        gif_bg_row.addStretch(1)
        form_gif.addRow("", gif_bg_row)

        # ---- GIF 体积优化行：颜色数 + 合并静止帧（仅 GIF 模式显示）----
        self.gif_color_row = QWidget()
        color_row = QHBoxLayout(self.gif_color_row)
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.addWidget(QLabel("颜色数"))
        self.cmb_gif_colors = QComboBox()
        self.cmb_gif_colors.addItems(["256", "128", "64", "32"])
        self.cmb_gif_colors.setToolTip(
            "GIF 调色板颜色数：越少文件越小，肉眼一般看不出差别。\n"
            "发微信表情包建议 64~128，可大幅减小体积")
        color_row.addWidget(self.cmb_gif_colors)
        self.chk_gif_dedup = QCheckBox("合并静止帧")
        self.chk_gif_dedup.setChecked(True)
        self.chk_gif_dedup.setToolTip(
            "把画面完全相同的连续帧合并为一帧（时长自动累加），\n"
            "画面有静止片段时能明显减小体积，动画效果不变")
        color_row.addWidget(self.chk_gif_dedup)
        color_row.addStretch(1)
        form_gif.addRow("", self.gif_color_row)

        # ---- 文字字幕行：内容留空则不加字 ----
        text_row = QHBoxLayout()
        text_row.addWidget(QLabel("文字"))
        self.line_gif_text = QLineEdit()
        self.line_gif_text.setPlaceholderText("输入字幕内容，留空则不加文字")
        self.line_gif_text.setToolTip(
            "把文字画到每一帧画面上（烧录进像素，同微信表情加字原理），\n"
            "适合做带台词的表情包；导出图片序列时不生效")
        text_row.addWidget(self.line_gif_text, 1)
        text_row.addWidget(QLabel("位置"))
        self.cmb_text_pos = QComboBox()
        self.cmb_text_pos.addItems(["底部居中", "顶部居中", "左上角", "右上角"])
        self.cmb_text_pos.setToolTip("预设位置；也可直接在左侧画面上拖动文字定位")
        text_row.addWidget(self.cmb_text_pos)
        text_row.addWidget(QLabel("字色"))
        self.cmb_text_color = QComboBox()
        self.cmb_text_color.addItems(list(TEXT_COLORS.keys()))
        self.cmb_text_color.setToolTip("自动加对比色描边，任何背景都清晰")
        text_row.addWidget(self.cmb_text_color)
        form_gif.addRow("", text_row)
        self.cmb_text_pos.currentIndexChanged.connect(self._on_caption_preset)
        self.line_gif_text.textChanged.connect(self._refresh_caption)

        # ---- WebP 专用参数（仅 WebP 模式显示）----
        self.webp_quality_row = QWidget()
        webp_row = QHBoxLayout(self.webp_quality_row)
        webp_row.setContentsMargins(0, 0, 0, 0)
        webp_row.addWidget(QLabel("WebP 质量"))
        self.spin_webp_quality = QSpinBox()
        self.spin_webp_quality.setRange(10, 100)
        self.spin_webp_quality.setValue(80)
        self.spin_webp_quality.setSuffix(" %")
        self.spin_webp_quality.setToolTip(
            "WebP 有损压缩质量：80 左右画质几乎无损且体积小；\n"
            "调小体积更小、画质下降，调大画质更好、体积更大。\n"
            "同等内容 WebP 通常比 GIF 小 50%~80%，且透明支持更好")
        webp_row.addWidget(self.spin_webp_quality)
        webp_row.addStretch(1)
        form_gif.addRow("", self.webp_quality_row)
        self.webp_quality_row.setVisible(False)

        self.btn_preview_gif = QPushButton("预览 GIF（按当前设置，含起点终点）")
        self.btn_preview_gif.setToolTip(
            "在左侧画面快速预览动图效果（预览版最大 320 宽、48 帧，不影响正式导出）\n"
            "先用播放器定位后点「设为起点 / 设为终点」选择片段，再点此预览")
        self.btn_preview_gif.clicked.connect(self.preview_gif)
        form_gif.addRow("", self.btn_preview_gif)
        form_out.addRow(self.gif_panel)

        right.addWidget(grp_out)
        self.gif_panel.setVisible(False)

        # 输出目录
        grp_dir = QGroupBox("4. 输出目录")
        form_dir = QVBoxLayout(grp_dir)
        row_dir = QHBoxLayout()
        self.edit_dir = QLineEdit()
        self.edit_dir.textChanged.connect(self.update_estimate)
        row_dir.addWidget(self.edit_dir)
        self.btn_dir = QPushButton("浏览…")
        self.btn_dir.clicked.connect(self.pick_dir)
        row_dir.addWidget(self.btn_dir)
        form_dir.addLayout(row_dir)
        right.addWidget(grp_dir)

        self.lbl_estimate = QLabel("预计输出：-")
        self.lbl_estimate.setStyleSheet("font-weight:bold;color:#0a6;")
        right.addWidget(self.lbl_estimate)

        # ---------- 底部：导出 ----------
        export_row = QHBoxLayout()
        self.btn_export = QPushButton("开始导出")
        self.btn_export.setFixedHeight(34)
        self.btn_export.clicked.connect(self.start_export)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_export)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        export_row.addWidget(self.btn_export)
        export_row.addWidget(self.btn_cancel)
        export_row.addWidget(self.progress, stretch=1)
        root.addLayout(export_row)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪")

        # 预览刷新防抖
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self.enable_settings(False)

    # ---------------- 帮助 ----------------
    def show_help(self):
        QMessageBox.information(self, "使用说明", (
            "<b>视频转图片/动图工具使用说明</b>"
            "<ol>"
            "<li>载入视频：点击<b>选择视频文件…</b>，或直接把视频文件<b>拖拽</b>到窗口中</li>"
            "<li>播放到想要的位置时，点<b>设为起点</b> / <b>设为终点</b>选择导出片段；"
            "勾选<b>全部视频</b>则处理整个视频</li>"
            "<li><b>输出类型</b>：可选「图片序列」「GIF 动图」「WebP 动图」，"
            "右侧参数会随类型切换</li>"
            "<li><b>图片序列</b>：<br>"
            "&nbsp;&nbsp;抽帧帧率：每秒保存几张图片（如 24 帧/秒视频设为 12 则每隔一帧保存一张）<br>"
            "&nbsp;&nbsp;输出格式：jpg（可调质量）或 png<br>"
            "&nbsp;&nbsp;文件名模板：支持 {名称}（视频名）、{序号}（自动补零），"
            "如 {名称}_frame_{序号} → 鹦鹉走路_frame_0001.jpg<br>"
            "&nbsp;&nbsp;导出声音：可同时把所选片段的声音导出为 mp3/m4a/wav</li>"
            "<li><b>GIF 动图</b>（合成流程与表情包生成器一致）：<br>"
            "&nbsp;&nbsp;抽帧频率：默认 10 帧/秒（即每帧间隔 100 毫秒），越高越流畅、文件越大；"
            "超过源帧率时按源帧率抽取<br>"
            "&nbsp;&nbsp;循环次数：0 为无限循环，N 为额外循环 N 次<br>"
            "&nbsp;&nbsp;AI 去背景：自动抠出画面主体去除背景（模型已内置，本地运行无需联网），"
            "配合透明背景得到透明底动图；速度较慢，建议用于短片段<br>"
            "&nbsp;&nbsp;背景颜色：透明/白色/黑色，仅影响留白区域（默认透明）<br>"
            "&nbsp;&nbsp;优化体积：减小 GIF 文件大小（默认开启）<br>"
            "&nbsp;&nbsp;颜色数：调色板颜色 256/128/64/32，越少体积越小（发微信表情包建议 64~128）<br>"
            "&nbsp;&nbsp;合并静止帧：画面完全相同的连续帧合并为一帧（时长累加），体积更小<br>"
            "&nbsp;&nbsp;文字：在画面上加字幕（字色可选，自动描边），"
            "在左侧画面上<b>拖动文字定位、滚轮调大小</b>，位置下拉可快速归位<br>"
            "&nbsp;&nbsp;GIF 大小：默认 240×240，画面等比缩放置中<br>"
            "&nbsp;&nbsp;预览：点「设为起点/设为终点」选片段后，点<b>预览 GIF</b> "
            "可在画面中直接播放动画效果（预览最大 320 宽/48 帧）；正式导出完成后也会自动播放预览<br>"
            "&nbsp;&nbsp;生成单个「视频名.gif」文件</li>"
            "<li><b>WebP 动图</b>：参数与 GIF 相同（抽帧频率/循环/去背景/背景颜色/大小），"
            "另有<b>WebP 质量</b>设置（默认 80%，画质几乎无损）。"
            "同等内容体积通常比 GIF 小 50%~80%，透明支持更好，"
            "现代浏览器与新版聊天软件均可播放；生成单个「视频名.webp」文件</li>"
            "<li><b>输出大小</b>：默认使用视频原始大小；取消勾选后可自定义宽高（自动保持宽高比）</li>"
            "<li><b>输出目录</b>：图片序列默认「视频名_图片」文件夹，GIF/WebP 默认视频所在目录，均可自行修改</li>"
            "<li>点击<b>开始导出</b>，进度条实时显示进度，可随时<b>取消</b></li>"
            "</ol>"
        ))

    def show_about(self):
        show_about("视频转图片/动图工具", self,
                   icon_path=self._icon_path if os.path.exists(self._icon_path) else None,
                   version=APP_VERSION)

    # ---------------- 交互 ----------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if os.path.splitext(p)[1].lower() in VIDEO_EXT_SET:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isfile(p) and os.path.splitext(p)[1].lower() in VIDEO_EXT_SET:
                self.load_video(p)
                event.acceptProposedAction()
                return
        event.ignore()

    def pick_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", VIDEO_EXTS)
        if not path:
            return
        self.load_video(path)

    def load_video(self, path):
        info = get_video_info(path)
        if info is None:
            QMessageBox.warning(self, "错误", "无法打开该视频文件")
            return
        self.video_path = path
        self.info = info
        self.lbl_video.setText(path)
        self.lbl_video.setToolTip(path)
        dur = info["duration"]
        self.lbl_info.setText(
            f"分辨率 {info['width']}×{info['height']} | 帧率 {info['fps']:.2f} fps | "
            f"时长 {fmt_time(dur)} | 总帧数 {info['frames']}"
        )
        self.spin_end.blockSignals(True)
        self.spin_end.setMaximum(dur)
        self.spin_end.setValue(dur)
        self.spin_end.blockSignals(False)
        self.spin_start.setMaximum(dur)
        self.spin_fps.blockSignals(True)
        self.spin_fps.setValue(info["fps"])
        self.spin_fps.blockSignals(False)
        self.spin_w.blockSignals(True)
        self.spin_w.setValue(info["width"])
        self.spin_w.blockSignals(False)
        self.spin_h.blockSignals(True)
        self.spin_h.setValue(info["height"])
        self.spin_h.blockSignals(False)
        if self.is_anim_mode() and not self.chk_original.isChecked():
            # 动图模式保持其尺寸设置（缺省 240×240，与表情包生成器一致）
            saved = self._size_cache["gif"]
            w, h = (saved[1], saved[2]) if saved else (240, 240)
            self.spin_w.blockSignals(True)
            self.spin_w.setValue(w)
            self.spin_w.blockSignals(False)
            self.spin_h.blockSignals(True)
            self.spin_h.setValue(h)
            self.spin_h.blockSignals(False)
        default_dir = os.path.join(os.path.dirname(path), os.path.splitext(os.path.basename(path))[0] + "_图片")
        self._auto_dir = ""
        self.edit_dir.setText(default_dir)
        self._auto_dir = default_dir
        if self.is_anim_mode():
            self.refresh_default_dir()
        self.chk_full.setChecked(True)
        self.lbl_time_fmt.setText(f"总时长 {fmt_time(dur)}")
        # 播放器初始化
        if self.cap is not None:
            self.cap.release()
        self.cap = cv2.VideoCapture(path)
        self.pause()
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, info["frames"] - 1))
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.play_timer.setInterval(max(1, round(1000 / info["fps"])))
        self.enable_settings(True)
        self.update_time_fmt()
        self.update_estimate()
        self.refresh_preview()

    def enable_settings(self, on: bool):
        for w in (self.cmb_out_type, self.chk_full, self.spin_start, self.spin_end,
                  self.spin_fps, self.chk_original, self.spin_w, self.spin_h,
                  self.cmb_format, self.spin_quality, self.edit_filename,
                  self.spin_gif_fps, self.spin_loop, self.cmb_gif_bg,
                  self.chk_gif_optimize, self.chk_gif_remove_bg,
                  self.cmb_gif_colors, self.chk_gif_dedup,
                  self.line_gif_text, self.cmb_text_pos, self.cmb_text_color,
                  self.spin_webp_quality,
                  self.btn_preview_gif,
                  self.edit_dir, self.btn_dir, self.btn_export,
                  self.slider, self.btn_play, self.btn_set_start, self.btn_set_end,
                  self.chk_audio):
            w.setEnabled(on)
        self.cmb_audio_fmt.setEnabled(on and self.chk_audio.isChecked())

    def on_audio_toggled(self, checked: bool):
        self.cmb_audio_fmt.setEnabled(checked)

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.edit_dir.text() or "")
        if d:
            self.edit_dir.setText(d)

    def refresh_default_dir(self):
        """按当前输出类型更新默认输出目录；用户手动改过则不覆盖"""
        if not self.video_path:
            return
        stem = os.path.splitext(os.path.basename(self.video_path))[0]
        base = os.path.dirname(self.video_path)
        new_dir = base if self.is_anim_mode() else os.path.join(base, stem + "_图片")
        cur = self.edit_dir.text().strip()
        if not cur or cur == self._auto_dir:
            self.edit_dir.setText(new_dir)
        self._auto_dir = new_dir

    def on_range_changed(self):
        full = self.chk_full.isChecked()
        self.spin_start.setEnabled(not full)
        self.spin_end.setEnabled(not full)
        if full:
            self.spin_start.setValue(0)
            self.spin_end.setValue(self.info["duration"] if self.info else 0)
        self.update_time_fmt()
        self.update_estimate()
        self._preview_timer.start()

    def on_start_changed(self):
        # 保证 开始 <= 结束
        if self.spin_start.value() > self.spin_end.value():
            self.spin_end.blockSignals(True)
            self.spin_end.setValue(self.spin_start.value())
            self.spin_end.blockSignals(False)
        self.update_time_fmt()
        self.update_estimate()
        self._preview_timer.start()

    def on_end_changed(self):
        if self.spin_end.value() < self.spin_start.value():
            self.spin_start.blockSignals(True)
            self.spin_start.setValue(self.spin_end.value())
            self.spin_start.blockSignals(False)
        self.update_time_fmt()
        self.update_estimate()

    def update_time_fmt(self):
        if not self.info:
            return
        s = 0.0 if self.chk_full.isChecked() else self.spin_start.value()
        e = self.info["duration"] if self.chk_full.isChecked() else self.spin_end.value()
        self.lbl_time_fmt.setText(f"{fmt_time(s)} → {fmt_time(e)}")

    def on_original_changed(self):
        orig = self.chk_original.isChecked()
        self.spin_w.setEnabled(not orig)
        self.spin_h.setEnabled(not orig)
        if orig and self.info:
            self._updating_size = True
            self.spin_w.setValue(self.info["width"])
            self.spin_h.setValue(self.info["height"])
            self._updating_size = False

    def on_size_w_changed(self):
        if self._updating_size or not self.info:
            return
        self._updating_size = True
        self.spin_h.setValue(max(16, round(self.spin_w.value() * self.info["height"] / self.info["width"])))
        self._updating_size = False

    def on_size_h_changed(self):
        if self._updating_size or not self.info:
            return
        self._updating_size = True
        self.spin_w.setValue(max(16, round(self.spin_h.value() * self.info["width"] / self.info["height"])))
        self._updating_size = False

    def get_out_size(self):
        if self.chk_original.isChecked():
            return None
        return self.spin_w.value(), self.spin_h.value()

    def is_gif_mode(self):
        return self.cmb_out_type.currentIndex() == 1

    def is_anim_mode(self):
        """GIF / WebP 动图模式（共用同一组动图参数面板）"""
        return self.cmb_out_type.currentIndex() >= 1

    def anim_fmt(self):
        return "webp" if self.cmb_out_type.currentIndex() == 2 else "gif"

    def _preview_btn_text(self):
        return ("预览 WebP（按当前设置，含起点终点）" if self.anim_fmt() == "webp"
                else "预览 GIF（按当前设置，含起点终点）")

    def on_out_type_changed(self):
        idx = self.cmb_out_type.currentIndex()
        self.img_panel.setVisible(idx == 0)
        self.gif_panel.setVisible(idx > 0)
        self._switch_size_defaults(idx > 0)  # WebP 与 GIF 共用尺寸设置
        self.chk_gif_optimize.setVisible(idx == 1)   # 优化体积仅 GIF 有意义
        self.gif_color_row.setVisible(idx == 1)      # 颜色数/合并静止帧仅 GIF 显示
        self.webp_quality_row.setVisible(idx == 2)   # WebP 质量仅 WebP 显示
        self.lbl_size.setText(["输出大小", "GIF 大小", "WebP 大小"][idx])
        self.btn_preview_gif.setText(self._preview_btn_text())
        self.status.showMessage("输出类型：" + ["图片序列", "GIF 动图", "WebP 动图"][idx])
        self.refresh_default_dir()
        self.update_estimate()

    def _switch_size_defaults(self, gif):
        """切换输出类型时缓存/恢复各自的尺寸设置

        GIF/WebP 动图模式共用尺寸设置（缺省固定 240×240，与表情包生成器一致），
        图片模式缺省原始大小
        """
        new_key = "gif" if gif else "img"
        if getattr(self, "_size_mode_key", "img") == new_key:
            return
        old_key = self._size_mode_key
        self._size_mode_key = new_key
        self._size_cache[old_key] = (self.chk_original.isChecked(),
                                     self.spin_w.value(), self.spin_h.value())
        saved = self._size_cache[new_key]
        self.chk_original.blockSignals(True)
        self.spin_w.blockSignals(True)
        self.spin_h.blockSignals(True)
        try:
            if saved is None:
                if gif:  # GIF 缺省：固定 240×240
                    self.chk_original.setChecked(False)
                    self.spin_w.setValue(240)
                    self.spin_h.setValue(240)
                else:    # 图片模式缺省：原始大小
                    self.chk_original.setChecked(True)
            else:
                self.chk_original.setChecked(saved[0])
                self.spin_w.setValue(saved[1])
                self.spin_h.setValue(saved[2])
        finally:
            self.chk_original.blockSignals(False)
            self.spin_w.blockSignals(False)
            self.spin_h.blockSignals(False)
        # 恢复"原始大小"时把宽高刷成视频尺寸
        if self.chk_original.isChecked() and self.info:
            self.on_original_changed()

    def update_estimate(self):
        if not self.info:
            self.lbl_estimate.setText("预计输出：-")
            return
        s = 0.0 if self.chk_full.isChecked() else self.spin_start.value()
        e = self.info["duration"] if self.chk_full.isChecked() else self.spin_end.value()
        if self.is_anim_mode():
            est = max(1, int(round((e - s) * self.spin_gif_fps.value())))
            name = "WebP 动图" if self.anim_fmt() == "webp" else "GIF 动图"
            self.lbl_estimate.setText(f"预计输出：1 个 {name}（约 {est} 帧）")
            return
        fps = self.spin_fps.value()
        est = max(0, int((e - s) * fps))
        if fps > self.info["fps"] and est > 0:
            self.lbl_estimate.setText(f"预计输出：约 {est} 张（帧率超过源帧率，实际按源帧率 {self.info['fps']:.2f} 抽帧）")
        else:
            self.lbl_estimate.setText(f"预计输出：约 {est} 张")

    def refresh_preview(self):
        """跳到所选时间段的起始画面（暂停播放）"""
        if not self.video_path or self.cap is None or not self.cap.isOpened():
            return
        self.pause()
        fps = self.info["fps"]
        s = 0.0 if self.chk_full.isChecked() else self.spin_start.value()
        idx = min(self.info["frames"] - 1, int(round(s * fps)))
        self.seek_to(idx)

    # ---------------- 播放器 ----------------
    def _caption_text(self):
        return self.line_gif_text.text().strip()

    def _draw_caption_on(self, pm):
        """在预览图上绘制字幕（与导出效果同源：同一位置/字号/颜色参数）"""
        self._cap_rect = None
        text = self._caption_text()
        if not text or self._gif_movie is not None:
            return
        pw, ph = pm.width(), pm.height()
        self._pm_size = (pw, ph)
        self._pm_off = ((self.preview.width() - pw) // 2,
                        (self.preview.height() - ph) // 2)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        fsize = max(10, int(self.caption_scale * ph))
        font = QFont("微软雅黑", fsize)
        font.setBold(True)
        path = QPainterPath()
        path.addText(0, 0, font, text)
        cx, cy = self.caption_xy[0] * pw, self.caption_xy[1] * ph
        br = path.boundingRect()
        path.translate(cx - br.center().x(), cy - br.center().y())
        fill, stroke = TEXT_COLORS.get(
            self.cmb_text_color.currentText(), TEXT_COLORS["白色"])
        sw = max(2, fsize // 8)
        p.setPen(QPen(QColor(*stroke), sw, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(QBrush(QColor(*fill)))
        p.drawPath(path)
        p.end()
        self._cap_rect = QRectF(path.boundingRect().adjusted(
            -sw, -sw, sw, sw))

    def _caption_hit(self, pos):
        """鼠标位置是否点中字幕（预览图坐标）"""
        if self._cap_rect is None or self._pm_size[0] <= 0:
            return None
        px = pos.x() - self._pm_off[0]
        py = pos.y() - self._pm_off[1]
        if QRectF(self._cap_rect).contains(QPointF(px, py)):
            return (px, py)
        return None

    def _on_caption_preset(self):
        self.caption_xy = list(CAPTION_PRESETS.get(
            self.cmb_text_pos.currentText(), (0.5, 0.93)))
        self._refresh_caption()

    def _refresh_caption(self):
        if self._current_frame is not None:
            self.show_frame(self._current_frame)

    def eventFilter(self, obj, event):
        """视频画面上的字幕交互：拖动定位、滚轮调字号"""
        if obj is self.preview and self._current_frame is not None:
            t = event.type()
            if t == QEvent.Type.MouseButtonPress and \
                    event.button() == Qt.MouseButton.LeftButton:
                hit = self._caption_hit(event.position())
                if hit is not None:
                    pw, ph = self._pm_size
                    self._cap_drag = (
                        (hit[0] - self.caption_xy[0] * pw) / pw,
                        (hit[1] - self.caption_xy[1] * ph) / ph)
                    return True
            elif t == QEvent.Type.MouseMove and self._cap_drag is not None:
                pw, ph = self._pm_size
                if pw > 0 and ph > 0:
                    px = event.position().x() - self._pm_off[0]
                    py = event.position().y() - self._pm_off[1]
                    self.caption_xy = [
                        min(0.99, max(0.01, px / pw - self._cap_drag[0])),
                        min(0.99, max(0.01, py / ph - self._cap_drag[1]))]
                    self.show_frame(self._current_frame)
                return True
            elif t == QEvent.Type.MouseButtonRelease and \
                    self._cap_drag is not None:
                self._cap_drag = None
                return True
            elif t == QEvent.Type.Wheel and self._caption_text():
                d = event.angleDelta().y()
                if d:
                    self.caption_scale = min(
                        0.30, max(0.04,
                                  self.caption_scale + (0.01 if d > 0 else -0.01)))
                    self.status.showMessage(
                        f"字幕大小：{int(self.caption_scale * 100)}%"
                        f"（滚轮调节，范围 4%~30%）")
                    self.show_frame(self._current_frame)
                    return True
        return super().eventFilter(obj, event)

    def show_frame(self, frame):
        """显示一帧 BGR 图像"""
        if frame is None:
            return
        self._current_frame = frame
        if self._gif_movie is not None:  # 任何视频帧显示都退出 GIF 预览态
            self._stop_gif_preview()
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        pw, ph = self.preview.width(), self.preview.height()
        scale = min(pw / w, ph / h)
        if scale > 0:
            pm = QPixmap.fromImage(img).scaled(
                max(1, int(w * scale)), max(1, int(h * scale)),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._draw_caption_on(pm)  # 预览图上叠加字幕（拖动/滚轮实时生效）
            self.preview.setPixmap(pm)

    def seek_to(self, frame_idx):
        """定位到指定帧并显示，同步滑块与时间"""
        if self.cap is None or not self.cap.isOpened():
            return
        frame_idx = max(0, min(self.info["frames"] - 1, int(frame_idx)))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = self.cap.read()
        if ok:
            self.show_frame(frame)
        self.slider.blockSignals(True)
        self.slider.setValue(frame_idx)
        self.slider.blockSignals(False)
        self.update_time_label()

    def update_time_label(self):
        if not self.info:
            return
        cur = self.slider.value() / self.info["fps"]
        self.lbl_time.setText(f"{fmt_time(cur)} / {fmt_time(self.info['duration'])}")

    def toggle_play(self):
        if self.play_timer.isActive():
            self.pause()
        else:
            self.play()

    def play(self):
        if not self.video_path or self.cap is None or not self.cap.isOpened():
            return
        if self.slider.value() >= self.info["frames"] - 1:  # 到结尾后从头播放
            self.seek_to(0)
        self.play_timer.start()
        self.btn_play.setText("⏸ 暂停")

    def pause(self):
        self.play_timer.stop()
        self.btn_play.setText("▶ 播放")

    def next_frame(self):
        if self.cap is None:
            self.pause()
            return
        ok, frame = self.cap.read()
        if not ok:  # 播放结束
            self.pause()
            return
        self.show_frame(frame)
        self.slider.blockSignals(True)
        self.slider.setValue(self.slider.value() + 1)
        self.slider.blockSignals(False)
        self.update_time_label()

    def on_slider_pressed(self):
        self._dragging = True
        self._was_playing = self.play_timer.isActive()
        self.pause()

    def on_slider_value_changed(self, value):
        if self._dragging:
            self._pending_seek = value
            self._seek_timer.start()  # 拖动时节流定位，保证流畅
        self.update_time_label()

    def on_slider_released(self):
        self._dragging = False
        self._seek_timer.stop()
        if self._pending_seek is not None:
            self.seek_to(self._pending_seek)
            self._pending_seek = None
        if self._was_playing:
            self.play()

    def _do_pending_seek(self):
        if self._pending_seek is not None and self._dragging:
            self.seek_to(self._pending_seek)

    def set_start_from_player(self):
        """把当前播放位置设为导出开始时间"""
        if not self.info:
            return
        t = self.slider.value() / self.info["fps"]
        if self.chk_full.isChecked():
            self.chk_full.setChecked(False)  # 自动取消"全部视频"
        if t > self.spin_end.value():
            self.spin_end.setValue(t)
        self.spin_start.setValue(t)
        self.status.showMessage(f"已设置起点: {fmt_time(t)}")

    def set_end_from_player(self):
        """把当前播放位置设为导出结束时间"""
        if not self.info:
            return
        t = self.slider.value() / self.info["fps"]
        if self.chk_full.isChecked():
            self.chk_full.setChecked(False)
        if t < self.spin_start.value():
            self.spin_start.setValue(t)
        self.spin_end.setValue(t)
        self.status.showMessage(f"已设置终点: {fmt_time(t)}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_frame is not None:
            self.show_frame(self._current_frame)  # 窗口变化时按新尺寸重绘当前帧
        if self._gif_movie is not None:
            self._position_close_preview_btn()

    # ---------------- GIF 预览 ----------------
    def _position_close_preview_btn(self):
        """把关闭预览按钮放到预览区右上角"""
        b = self.btn_close_preview
        b.adjustSize()
        m = 8
        b.move(max(0, self.preview.width() - b.width() - m), m)
        b.raise_()

    def _on_close_preview(self):
        """点击关闭预览按钮：回到视频画面"""
        self._stop_gif_preview()
        self.status.showMessage("已关闭 GIF 预览，回到视频画面")

    def _stop_gif_preview(self):
        """停止并清除 GIF 动画预览，恢复视频帧显示"""
        self.btn_close_preview.hide()
        if self._gif_movie is not None:
            self.preview.setMovie(None)
            self._gif_movie.stop()
            self._gif_movie.deleteLater()
            self._gif_movie = None
        if self._current_frame is not None:
            frame = self._current_frame
            self._current_frame = None
            self.show_frame(frame)  # 重绘最后一帧

    def _play_gif(self, path):
        """在预览区循环播放 GIF 动画"""
        self._stop_gif_preview()
        self._gif_movie = QMovie(path)
        self._gif_movie.setCacheMode(QMovie.CacheMode.CacheAll)
        self.preview.setMovie(self._gif_movie)
        self._gif_movie.start()
        self._position_close_preview_btn()
        self.btn_close_preview.show()
        self.status.showMessage("GIF 预览中：点「✕ 关闭预览」或拖动进度条即可回到视频画面")

    def preview_gif(self):
        """按当前设置生成快速预览 GIF 并播放（含所选起点/终点）"""
        if not self.video_path:
            QMessageBox.warning(self, "提示", "请先选择视频文件")
            return
        if self.worker is not None or self.preview_worker is not None:
            return
        s = 0.0 if self.chk_full.isChecked() else self.spin_start.value()
        e = (self.info["duration"] if self.chk_full.isChecked()
             else self.spin_end.value())
        if e <= s:
            QMessageBox.warning(self, "提示", "结束时间必须大于开始时间")
            return
        self.pause()
        self.btn_preview_gif.setEnabled(False)
        self.btn_preview_gif.setText("生成预览中…")
        if self.anim_fmt() == "webp":
            # QMovie 不支持 WebP，预览仍以 GIF 呈现（帧内容与节奏与成品一致）
            self.status.showMessage("正在生成 WebP 动画预览（预览以 GIF 呈现，成品体积更小）…")
        else:
            self.status.showMessage("正在生成 GIF 预览…")
        self.preview_worker = GifPreviewWorker(
            self.video_path, s, e,
            self.spin_gif_fps.value(), self.get_out_size(),
            self.spin_loop.value(), self.chk_gif_optimize.isChecked(),
            self.cmb_gif_bg.currentText(), self.chk_gif_remove_bg.isChecked(),
            text=(self.line_gif_text.text().strip() or None),
            text_xy=tuple(self.caption_xy),
            text_scale=self.caption_scale,
            text_color=self.cmb_text_color.currentText())
        self.preview_worker.done.connect(self.on_preview_done)
        self.preview_worker.failed.connect(self.on_preview_failed)
        self.preview_worker.start()

    def on_preview_done(self, path, cancelled):
        self.preview_worker = None
        self.btn_preview_gif.setEnabled(True)
        self.btn_preview_gif.setText(self._preview_btn_text())
        if cancelled:
            self.status.showMessage("已取消动图预览")
            return
        self._play_gif(path)

    def on_preview_failed(self, err):
        self.preview_worker = None
        self.btn_preview_gif.setEnabled(True)
        self.btn_preview_gif.setText(self._preview_btn_text())
        self.status.showMessage("动图预览失败")
        QMessageBox.critical(self, "预览失败", err)

    # ---------------- 导出 ----------------
    def start_export(self):
        if not self.video_path or self.worker is not None:
            return
        if self.preview_worker is not None:  # 预览中直接导出：先停预览
            self.preview_worker.cancel()
            self.preview_worker.wait(2000)
            self.preview_worker = None
            self.btn_preview_gif.setEnabled(True)
            self.btn_preview_gif.setText(self._preview_btn_text())
            self._stop_gif_preview()
        self.pause()  # 导出时暂停播放，避免抢占解码资源
        out_dir = self.edit_dir.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "提示", "请先设置输出目录")
            return
        s = 0.0 if self.chk_full.isChecked() else self.spin_start.value()
        e = None if self.chk_full.isChecked() else self.spin_end.value()
        if e is not None and e <= s:
            QMessageBox.warning(self, "提示", "结束时间必须大于开始时间")
            return

        self.btn_export.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setValue(0)

        if self.is_anim_mode():
            end_sec = self.info["duration"] if e is None else e
            fmt = self.anim_fmt()
            self.status.showMessage(f"正在生成 {'WebP' if fmt == 'webp' else 'GIF'}…")
            self.worker = GifWorker(
                self.video_path, out_dir, s, end_sec,
                self.spin_gif_fps.value(), self.get_out_size(),
                self.spin_loop.value(), self.chk_gif_optimize.isChecked(),
                self.cmb_gif_bg.currentText(), self.chk_gif_remove_bg.isChecked(),
                fmt=fmt, quality=self.spin_webp_quality.value(),
                colors=int(self.cmb_gif_colors.currentText()),
                dedup=self.chk_gif_dedup.isChecked(),
                text=(self.line_gif_text.text().strip() or None),
                text_xy=tuple(self.caption_xy),
                text_scale=self.caption_scale,
                text_color=self.cmb_text_color.currentText())
            self.worker.progress.connect(self.on_progress)
            self.worker.phase.connect(self.status.showMessage)
            self.worker.done.connect(self.on_gif_done)
            self.worker.failed.connect(self.on_failed)
            self.worker.start()
            return

        export_audio = self.chk_audio.isChecked()
        ffmpeg_exe = None
        if export_audio:
            ffmpeg_exe = find_ffmpeg()
            if ffmpeg_exe is None:
                self.btn_export.setEnabled(True)
                self.btn_cancel.setEnabled(False)
                QMessageBox.warning(self, "提示",
                                    "未找到 ffmpeg，无法导出声音。\n"
                                    "请安装 ffmpeg 并加入 PATH（或取消勾选\"导出声音\"）。")
                return
        self.status.showMessage("正在导出…")
        self.worker = ExtractWorker(
            self.video_path, out_dir, s, e,
            self.spin_fps.value(), self.get_out_size(),
            self.cmb_format.currentText(), self.spin_quality.value(),
            self.edit_filename.text().strip() or "{名称}_{序号}",
            export_audio, self.cmb_audio_fmt.currentText(), ffmpeg_exe)
        self.worker.progress.connect(self.on_progress)
        self.worker.phase.connect(self.status.showMessage)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def cancel_export(self):
        if self.worker is not None:
            self.btn_cancel.setEnabled(False)
            self.status.showMessage("正在取消…")
            self.worker.cancel()

    def on_progress(self, cur, total):
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(cur)

    def on_done(self, saved, cancelled, out_dir, audio_note=""):
        self.worker = None
        self.btn_export.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        msg = f"已取消，共保存 {saved} 张图片" if cancelled else f"导出完成，共保存 {saved} 张图片"
        if audio_note:
            msg += f"\n{audio_note}"
        self.status.showMessage(f"{msg.splitlines()[0]} → {out_dir}")
        QMessageBox.information(self, "完成", msg + f"\n输出目录：{out_dir}")

    def on_gif_done(self, out_path, cancelled):
        self.worker = None
        self.btn_export.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        is_webp = out_path.lower().endswith(".webp")
        name = "WebP 动图" if is_webp else "GIF 动图"
        if cancelled:
            self.status.showMessage(f"已取消 {name} 导出")
            QMessageBox.information(self, "已取消", f"{name}导出已取消，未生成文件")
            return
        size_mb = os.path.getsize(out_path) / 1024 / 1024
        self.status.showMessage(f"{name}生成完成 → {out_path}")
        QMessageBox.information(
            self, "完成",
            f"{name}已生成\n文件：{out_path}\n大小：{size_mb:.2f} MB"
            + ("\n（WebP 不支持内置播放预览，可在浏览器中查看效果）" if is_webp else ""))
        if not is_webp:
            self._play_gif(out_path)  # 生成完成后自动播放预览（QMovie 不支持 WebP）

    def on_failed(self, err):
        self.worker = None
        self.btn_export.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.status.showMessage("导出失败")
        QMessageBox.critical(self, "导出失败", err)

    def closeEvent(self, event):
        self.pause()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.preview_worker is not None:
            self.preview_worker.cancel()
            self.preview_worker.wait(3000)
            self.preview_worker = None
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception:
        # pythonw 无控制台，崩溃信息写入日志便于排查
        import traceback
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "启动错误.log")
        with open(log_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise
