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

import importlib.resources
import logging
import os
import pathlib
import typing
from abc import ABCMeta, abstractmethod

import click
import tomli

_logger = logging.getLogger("byre.commands.config")
_debug, _info, _warning = _logger.debug, _logger.info, _logger.warning


class GlobalConfig(click.ParamType):
    """配置文件。"""

    name = "配置文件路径"

    def __init__(self):
        self.config: typing.Optional[dict[str, typing.Any]] = None

    def convert(self, value: str, param, ctx):
        if not value:
            default_path = pathlib.Path.home().joinpath(".config", "byre", "byre.toml")
            for f in ["byre.toml", str(default_path), "/etc/byre.toml",
                      "/etc/byre/byre.toml"]:
                if os.path.exists(f):
                    _info("默认选定配置文件：%s", pathlib.Path(f))
                    value = f
                    break
            else:
                _warning("找不到配置文件“byre.toml”，如果已有配置文件，请尝试使用 -c / --config 选项")
                if click.prompt("是否创建配置文件？",
                                type=click.Choice(["yes", "no"]), default="no", prompt_suffix=" ") == "yes":
                    _info("默认配置文件位置：%s", default_path)
                    os.makedirs(default_path.parent, exist_ok=True)
                    with importlib.resources.files(__package__).joinpath("byre.example.toml").open() as tmpl:
                        with default_path.open("w") as config:
                            config.write(tmpl.read())
                            config.flush()
                    value = str(default_path)
                    click.edit(filename=value)
                else:
                    raise FileNotFoundError("找不到配置文件")
        with open(value, "rb") as file:
            self.config = tomli.load(file)
        return self

    def require(self, typer: typing.Callable, *args, password=False):
        config = self.config
        for arg in args:
            if arg not in config:
                if password:
                    config = click.prompt(f"请输入 {'.'.join(args)} 配置：", hide_input=True)
                    break
                raise ValueError(f"缺失 {'.'.join(args)} 配置参数")
            config = config[arg]
        try:
            return typer(config)
        except ValueError as e:
            raise ValueError(f"配置项 {'.'.join(args)} 的值 {config} 无效：{e}")

    def optional(self, typer: typing.Callable, default: typing.Any, *args):
        try:
            return self.require(typer, *args)
        except ValueError:
            return default


class ConfigurableGroup(click.Group, metaclass=ABCMeta):
    """能够把 ``GlobalConfig`` 导出传递从而实现 ``click`` 下手动的依赖注入的基类。"""

    @abstractmethod
    def configure(self, config: GlobalConfig):
        """各自的配置。"""

    def invoke(self, ctx: click.Context):
        self.configure(ctx.obj["config"])
        return super().invoke(ctx)

    def add_command(self, cmd: click.Command, name: typing.Optional[str] = None) -> None:
        inner = cmd.callback

        # click 下看起来只能通过这种方法把 self 传进去……
        def callback(*args, **kwargs):
            inner(self, *args, **kwargs)
        # 继承下的同一个函数对应的 Command 是同一个，所以必须复制。
        super().add_command(click.Command(
            name=cmd.name,
            context_settings=cmd.context_settings,
            callback=callback,
            params=cmd.params,
            help=cmd.help,
            epilog=cmd.epilog,
            short_help=cmd.short_help,
            options_metavar=cmd.options_metavar,
            add_help_option=cmd.add_help_option,
            no_args_is_help=cmd.no_args_is_help,
            hidden=cmd.hidden,
            deprecated=cmd.deprecated,
        ), name)

    def register(self, group: click.Group):
        group.add_command(self)
        for attr in (name for name in dir(self) if not name.startswith("_")):
            method = getattr(self, attr)
            if callable(method) and isinstance(method, click.Command) and not isinstance(method, ConfigurableGroup):
                self.add_command(method)
        return self
