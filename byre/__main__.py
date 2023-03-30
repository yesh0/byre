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

import click

from byre import utils, setup
from byre.clients.byr import ByrClient, ByrApi
from byre.clients.tju import TjuPtClient, TjuPtApi
from byre.commands.bt import BtCommand
from byre.commands.config import GlobalConfig
from byre.commands.main import MainCommand
from byre.commands.nexus import NexusCommand, ByrCommand


@click.group()
@click.option("-c", "--config", type=GlobalConfig(), default="", help="TOML 格式配置文件")
@click.option("-v", "--verbose", is_flag=True, help="输出详细信息")
@click.pass_context
def main(ctx: click.Context, config: GlobalConfig, verbose: bool):
    """
    北邮人命令行操作以及 BT 软件整合实现。

    软件主要通过 qBittorrent 的标签功能来标记北邮人 PT 的种子，
    再在种子名称前加入 ``[byr-北邮人ID]`` 来建立本地种子与
    北邮人种子的关联。

    详细的使用说明请见代码仓库的 README 文件：

        https://github.com/yesh0/byre
    """
    ctx.ensure_object(dict)
    ctx.obj["config"] = config

    utils.colorize_logger(None)
    logging.basicConfig(stream=sys.stderr)
    if verbose:
        logging.getLogger("byre").setLevel(logging.DEBUG)
    else:
        logging.getLogger("byre").setLevel(logging.INFO)


byr = ByrCommand(ByrClient, ByrApi).register(main)
tju = NexusCommand(TjuPtClient, TjuPtApi).register(main)
bt = BtCommand(byr, tju).register(main)
MainCommand(bt, byr, tju).register(main)


@main.command(name="setup")
@click.pass_context
def setup_qbittorrent(ctx: click.Context):
    """下载并配置 qBittorrent-nox。"""
    conf: GlobalConfig = ctx.obj["config"]
    setup.setup(conf.require(str, "qbittorrent", "url"))


def entry_point():
    # 这些要在 click 产生输出之前设置好，因为要兼容 setuptools 的配置（直接调用 main 函数），所以只能放这里了。
    os.environ["LANGUAGE"] = "zh"
    # 想用 importlib 但似乎 gettext 不支持，希望没问题。
    gettext.bindtextdomain("messages", localedir=os.path.join(os.path.dirname(os.path.realpath(__file__)), "locales"))
    main(obj={})


if __name__ == "__main__":
    entry_point()
