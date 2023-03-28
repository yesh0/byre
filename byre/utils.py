# Copyright (C) 2023 Yesh
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""一些工具函数。"""
import io
import logging

import click

_logger = logging.getLogger("byre.utils")
_warning = _logger.warning


def convert_byr_size(size: str) -> float:
    """
    将文字形式的 xx MB 转换为以 GB 为单位的浮点数。

    北邮人是1024派的, Linux 是 1000 派的, 所以 GB 会差 1-(1000/1024)**3=6.9%。
    """

    size = size.strip().upper()
    try:
        unit = ["B", "KB", "MB", "GB", "TB"].index(size[-2:])
        return float(size[0:-2].strip()) * 1024 ** unit / (1000 ** 3)
    except ValueError:
        _warning("无法识别的数据量单位：%s", size)
        return 0.


def int_or(s: str, default=0) -> int:
    """安全地将字符串解析成 int 值。"""
    try:
        return int(s)
    except ValueError:
        return default


def float_or(s: str, default=0.) -> float:
    """安全地将字符串解析成 float 值。"""
    try:
        return float(s)
    except ValueError:
        return default


def colorize_logger(name="byre") -> None:
    class ClickEchoStream(io.StringIO):
        def write(self, s: str) -> int:
            click.echo(s, nl=False, err=True)
            return len(s)

    handler = logging.StreamHandler(stream=ClickEchoStream())

    colors = [
        (logging.INFO, "white"),
        (logging.WARNING, "bright_yellow"),
    ]

    class ColorFormatter(logging.Formatter):
        def __init__(self):
            super().__init__(
                fmt=" ".join((
                    click.style("%(asctime)s", dim=True),
                    "%(levelname)5s",
                    click.style("%(name)s", fg="yellow"),
                    "%(message)s",
                )),
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        def format(self, record: logging.LogRecord) -> str:
            if record.levelno <= logging.DEBUG:
                record.levelname = click.style(record.levelname, dim=True)
                record.msg = click.style(record.msg, dim=True)
            else:
                for level, color in colors:
                    if record.levelno <= level:
                        record.levelname = click.style(record.levelname, fg=color)
                        break
                else:
                    record.levelname = click.style(record.levelname, fg="bright_red")
                    record.msg = click.style(record.msg, fg="bright_red")
            return super().format(record)

    handler.setFormatter(ColorFormatter())
    logger = logging.getLogger(name)
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logger.addHandler(handler)
