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

import logging

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
