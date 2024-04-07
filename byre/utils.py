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
import re
import typing
from dataclasses import dataclass

import click

_logger = logging.getLogger("byre.utils")
_warning = _logger.warning
_non_size_chars = re.compile("[^\\s\\w.]+")


def convert_iec_size(size: str) -> float:
    """
    将文字形式的 xx MB 转换为字节数。

    原来：北邮人是 1024 派的, Linux 是 1000 派的, 所以 GB 会差 1-(1000/1024)**3=6.9%。
    现在：我们也 1024 派吧，毕竟 qBittorrent 也是这样。

    然而，北邮人的字节数里加上了 "|" 啊或者是 `chr(0xa0)` 这种字符，就只能稍微变通一下了。
    """
    size = re.sub(_non_size_chars, "", size).strip()
    if size.isdigit():
        _warning("“%s”不带单位，默认使用 GiB", size)
        size = f"{size} GiB"

    unit_sets = [
        ["", "KIB", "MIB", "GIB", "TIB", "PIB"],
        ["", "KB", "MB", "GB", "TB", "PB"],
        ["B", "K", "M", "G", "T", "P"],
    ]
    for units in unit_sets:
        unit_len = len(units[-1])
        unit = size[-unit_len:].upper()
        if unit in units:
            unit_power = units.index(unit)
            size = size[0:-unit_len]
            return float(size.strip()) * 1024 ** unit_power
    _warning("无法识别的数据量单位：%s", size)
    return 0.


def int_or(s: str, default=0) -> int:
    """安全地将字符串解析成 int 值。"""
    try:
        return int(s.replace(',', '').strip())
    except ValueError:
        return default


def float_or(s: str, default=0.) -> float:
    """安全地将字符串解析成 float 值。"""
    try:
        return float(s.replace(',', '').strip())
    except ValueError:
        return default


def colorize_logger(name: typing.Optional[str] = "byre") -> None:
    class ClickEchoStream(io.StringIO):
        def write(self, s: str) -> int:
            click.echo(s, nl=False, err=True)
            return len(s)

    handler = logging.StreamHandler(stream=ClickEchoStream())

    colors = [
        (logging.INFO, "white"),
        (logging.WARNING, "bright_yellow"),
    ]

    # noinspection SpellCheckingInspection
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


@dataclass
class S:
    """
    用于显示文件大小。

    用法为 ``f"{S(size_in_bytes)}"`` 。
    """

    size: float
    """The size in bytes."""

    def __format__(self, format_spec: str) -> str:
        """自动使用合适的单位来显示文件大小。"""
        if format_spec is not None and len(format_spec) > 0:
            raise ValueError("不支持的格式")

        for i, unit in enumerate(("B", "KiB", "MiB", "GiB", "TiB", "PiB")):
            if self.size < 1024 ** (i + 1):
                return f"{self.size / 1024 ** i:.2f} {unit}"
        return "超大"


T = typing.TypeVar("T")

def cast(t: typing.Type[T], value: typing.Any) -> T:
    """
    检查类型并使用 `typing.cast` 转化类型。

    与 `typing.cast` 不同，这里如果类型不对会直接报错。基本上可以当成一个 inline 的 assert 来用。
    早点报错总比类型不对的东西到处乱跑要好……

    数值类型稍微宽松一点点。
    """
    if isinstance(value, t):
        return typing.cast(T, value)
    if t == int or t == float:
        return t(value)
    raise TypeError(f"类型错误：{type(value)} 无法转为 {t}")


def not_none(value: T | None, msg: str | None = "值不能为 None") -> T:
    """Inline None 值校验。"""
    if value is None:
        raise ValueError(msg)
    return value
