"""通用「关于」对话框与标准「关于」按钮：图标 + 应用名 + 版本 + 公司 + 网址。

标准公司信息规范，所有桌面应用共用（PySide6 版）。
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from version import VERSION

COMPANY = '深圳市创炫互动网络科技有限公司'
WEBSITE = 'www.mrheedu.com'
WEBSITE_URL = 'https://www.mrheedu.com'
SOURCE_URL = 'https://gitee.com/FC1976/video-to-image'


def find_icon(name: str = '图标.png') -> Path | None:
    """在当前目录及其上溯 3 层里找应用图标（约定放在项目根目录）。"""
    base = Path.cwd()
    for folder in (base, *base.parents[:3]):
        p = folder / name
        if p.exists():
            return p
    return None


def app_icon(name: str = '图标.png') -> QIcon | None:
    """返回应用图标；找不到时返回 None，调用方跳过 setWindowIcon。"""
    path = find_icon(name)
    return QIcon(str(path)) if path else None


class AboutDialog(QDialog):
    def __init__(self, app_name: str, parent=None, icon_path: Path | None = None,
                 version: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f'关于 {app_name}')
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        path = icon_path or find_icon()
        if path:
            pic = QLabel()
            pic.setPixmap(QPixmap(str(path)).scaled(
                72, 72,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            row.addWidget(pic)

        info = QLabel(
            f'<h2>{app_name}</h2>'
            f'<p>版本：{version or VERSION}</p>'
            f'<p>公司：{COMPANY}</p>'
            f'<p>技术框架：Qt 6 / PySide6（LGPLv3）</p>'
            f'<p>开源许可：GPL-3.0　源码：<a href="{SOURCE_URL}">{SOURCE_URL}</a></p>'
            f'<p>更多免费软件：<a href="{WEBSITE_URL}">{WEBSITE}</a></p>')
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setOpenExternalLinks(True)
        row.addWidget(info, stretch=1)
        root.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(self.accept)
        root.addWidget(btns)


def show_about(app_name: str, parent=None, icon_path: Path | None = None,
               version: str | None = None) -> None:
    """弹出「关于」对话框。version 传打包配置里的真实版本号。"""
    AboutDialog(app_name, parent, icon_path, version).exec()


def about_button(app_name: str, version: str | None = None) -> QPushButton:
    """标准「关于」按钮：文案固定「关于」，点击弹标准对话框。"""
    btn = QPushButton('关于')
    btn.setToolTip(f'关于 {app_name}')
    btn.clicked.connect(lambda: show_about(app_name, btn.window(), version=version))
    return btn
