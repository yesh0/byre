#  Copyright (C) 2023 Yesh
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

import gettext
import logging
import os.path
import sys
import typing

import click

from byre.commands import GlobalConfig

_commands: typing.Union[GlobalConfig, None] = None


@click.group()
@click.option("-c", type=GlobalConfig(), default="byre.toml", help="TOML 格式配置文件")
@click.option("-v", is_flag=True, help="输出详细信息")
def main(c: GlobalConfig, v: bool):
    """北邮人命令行操作以及 BT 软件整合实现。"""
    global _commands
    _commands = c
    logging.basicConfig(stream=sys.stderr)
    if v:
        logging.getLogger("byre").setLevel(logging.DEBUG)


@main.group()
def byr():
    """访问北邮人 PT。"""


@byr.command()
@click.argument("seed", type=click.STRING, metavar="<北邮人链接或是种子 ID>")
def torrent(seed: str):
    """显示种子信息。"""
    _commands.display_torrent_info(seed)


os.environ["LANGUAGE"] = "zh"
gettext.bindtextdomain("messages", localedir=os.path.join(os.path.dirname(os.path.realpath(__file__)), "locales"))


if __name__ == "__main__":
    main()
