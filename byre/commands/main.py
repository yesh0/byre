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

import bisect
import logging
import math
import re
import time
import typing

import bencoder
import click
import psutil
from overrides import override

from byre import scoring, planning, storage
from byre.clients import SITES
from byre.clients.api import NexusSortableField
from byre.clients.data import UserTorrentKind, TorrentInfo, LocalTorrent, TorrentPromotion, PROMOTION_FREE
from byre.commands import pretty
from byre.commands.bt import BtCommand
from byre.commands.config import GlobalConfig, ConfigurableGroup
from byre.commands.nexus import ByrCommand, NexusCommand

_logger = logging.getLogger("byre.commands.main")
_debug, _info, _warning = _logger.debug, _logger.info, _logger.warning


class MainCommand(ConfigurableGroup):
    def __init__(self, bt: BtCommand, byr: ByrCommand, *sites: NexusCommand):
        super().__init__(
            name="do",
            help="综合 PT 站点与本地的命令，主要功能所在。",
            no_args_is_help=True,
        )
        self.bt = bt
        self.byr = byr
        self.sites = dict((site.api_cls.site(), site) for site in sites)
        self.config: typing.Optional[GlobalConfig] = None
        self.planner: typing.Optional[planning.Planner] = None
        self.scorer: typing.Optional[scoring.Scorer] = None
        self.store: typing.Optional[storage.TorrentStore] = None

    @override
    def configure(self, config: GlobalConfig):
        self.scorer = scoring.Scorer(
            free_weight=config.optional(float, 1., "scoring", "free_weight"),
            cost_recovery_days=config.optional(float, 7., "scoring", "cost_recovery_days"),
            removal_exemption_days=config.optional(float, 15., "scoring", "removal_exemption_days"),
        )
        max_total_size = config.optional(float, 0., "planning", "max_total_size")
        self.planner = planning.Planner(
            max_total_size=max_total_size,
            max_download_size=config.optional(float, max_total_size / 50, "planning", "max_download_size"),
        )
        self.store = storage.TorrentStore(config.require(str, "qbittorrent", "cache_database"))
        self.config = config
        self.bt.configure(config)
        self.byr.configure(config)

    @click.command
    @click.option("-d", "--dry-run", is_flag=True, help="计算种子选择结果，但不添加种子到本地")
    @click.option("-p", "--print", "print_scores", is_flag=True, help="显示新种子评分以及最终选择结果")
    @click.option("-f", "--free-only", is_flag=True, help="只会下载免费促销的种子")
    def main(self, dry_run: bool, print_scores: bool, free_only: bool):
        """自动选择北邮人种子并在本地开始下载。"""
        self.download(None, dry_run, print_scores, free_only)

    @click.command
    @click.option("-d", "--dry-run", is_flag=True, help="获取重命名列表，但不重命名")
    def fix(self, dry_run: bool):
        """
        尝试修复 qBittorrent 中的任务名（也即给名称加上 ``[byr-北邮人ID]`` 的前缀）。

        暂时只支持北邮人。
        """
        pending = [t for t in self.bt.api.list_torrents([], wants_all=True, site="byr") if t.seed_id == 0]
        if len(pending) == 0:
            _info("所有种子均已经正确命名")
            return
        for kind in [UserTorrentKind.SEEDING, UserTorrentKind.COMPLETED, UserTorrentKind.LEECHING,
                     UserTorrentKind.INCOMPLETE]:
            self._match_against_remote(pending, self.byr.api.list_user_torrents(kind))
            if all(t.seed_id != 0 for t in pending):
                break
        rename_actions = pretty.pretty_rename(pending)
        _info("重命名结果：\n%s", rename_actions)
        if dry_run:
            _info("以上计划未被实际运行；若想实际重命名，请去除命令行 -d / --dry-run 选项")
        else:
            for torrent in pending:
                if torrent.seed_id != 0:
                    _debug("正在重命名 %s", torrent.info.title)
                    self.bt.api.rename_torrent(torrent, torrent.info)

    @click.command(name="stat")
    def stat(self):
        """显示当前本地统计信息。"""
        local = self.bt.api.list_torrents([])
        total, duplicates = self.planner.merge_torrent_info(local, self.store)
        finished = sum(t.torrent.amount_left == 0 for t in local)
        amount_left = sum(t.torrent.amount_left for t in local) / 1000 ** 3
        dl_speed = sum(t.torrent.dlspeed for t in local) / 1000 ** 2
        up_speed = sum(t.torrent.upspeed for t in local) / 1000 ** 2
        uploaded = sum(t.torrent.uploaded for t in local) / 1000 ** 3
        uploaded_session = sum(t.torrent.uploaded_session for t in local) / 1000 ** 3
        click.echo(f"当前管理种子数：{len(local)}，下载完成数 {finished}，剩余下载量 {amount_left:.2f} GB")
        click.echo(f"上传速度 {up_speed:.2f} MB/s，下载速度 {dl_speed:.2f} MB/s")
        click.echo(f"当前种子总上传量 {uploaded:.2f} GB，最近一次重启后上传量 {uploaded_session:.2f} GB")
        click.echo(f"当前本地种子已用空间 {total:.2f} GB，使用空间上限为 {self.planner.max_total_size:.2f} GB")
        remaining = self._get_disk_remaining()
        click.echo(f"当前下载目录分区剩余空间 {remaining:.2f} GB")

    def _get_disk_remaining(self):
        remaining = psutil.disk_usage(self.bt.api.download_dir).free / 1000 ** 3
        return remaining

    @click.command(name="download")
    @click.argument("seed", type=click.STRING, metavar="<北邮人链接或是种子 ID>")
    @click.option("-a", "--at", default="byr", type=click.Choice(SITES.keys()), help="种子所在 PT 站点")
    @click.option("-d", "--dry-run", is_flag=True, help="计算种子调整结果，但不添加种子到本地")
    @click.option("-p", "--paused", is_flag=True, help="使种子在添加后被暂停")
    @click.option("-e", "--exists", is_flag=True, help="告诉 qBittorrent 文件已经下载完毕并让其跳过哈希检查")
    @click.option("-s", "--same", default="", type=click.STRING,
                  help="告诉 qBittorrent 该种子与这个哈希对应的北邮人种子的文件一模一样")
    def download_one(self, at: str, seed: str, dry_run: bool, paused: bool, exists: typing.Union[bool, LocalTorrent],
                     same: str):
        """下载特定种子，可能会删除其它种子腾出空间来满足下载需求。"""
        seed_id = pretty.parse_url_id(seed)
        if same:
            # 原本应该 BtClient 再封装一下的，但是懒。
            local = self.bt.api.client.torrents_info(torrent_hashes=[same])
            if len(local) == 0:
                raise ValueError(f"不存在哈希为 {same} 的种子")
            if local[0].amount_left != 0:
                raise RuntimeError(f"该 {same} 种子还在下载中，请下载完成后重试")
            exists = self.bt.api.local_torrent_from(local[0], "byr")
        if at == "byr":
            api = self.byr.api
        else:
            self.sites[at].configure(self.config)
            api = self.sites[at].api
        self.download(api.torrent(seed_id), dry_run, paused=paused, exists=exists)

    @click.command
    @click.option("-d", "--dry-run", is_flag=True, help="计算种子下载结果，但不添加种子到本地")
    def hitchhike(self, dry_run: bool):
        """
        搭便车，尝试寻找从北邮人站下载下来的、其它站点也有的种子，同时做种。
        """
        for site in self.sites.values():
            site.configure(self.config)

        # 本地种子分站点放好。
        torrents = self.bt.api.list_torrents([], wants_all=False, site=None)
        byr_torrents = [t for t in torrents if t.site == "byr" and t.torrent.amount_left == 0]
        byr_torrents.sort(key=lambda t: t.torrent.size)
        existing_seeds: dict[str, list[int]] = dict((name, []) for name in self.sites.keys())
        for t in torrents:
            if t.site != "byr":
                existing_seeds[t.site].append(t.seed_id)

        # 用 bisect 按照 torrent.torrent.size 来查找种子。
        class SizeSearchable(typing.Sequence):
            def __init__(self, ts: list[LocalTorrent]):
                self.torrents = ts

            def __getitem__(self, item):
                return self.torrents[item].torrent.size

            def __len__(self):
                return len(self.torrents)

        local_byr = SizeSearchable(byr_torrents)
        matches = []
        for name, existing in existing_seeds.items():
            api = self.sites[name].api
            page = []
            page.extend(api.list_torrents(0))
            page.extend(api.list_torrents(0, NexusSortableField.LEECHER_COUNT))
            page.extend(api.list_torrents(0, NexusSortableField.SEEDER_COUNT))
            page.sort(key=lambda t: t.file_size)
            existing_set = set(existing)
            for torrent in page:
                if torrent.seed_id in existing_set:
                    continue
                # 只匹配总大小误差在 ~0.03 GB 范围内的种子。
                i = bisect.bisect_left(local_byr, (torrent.file_size - 0.03) * 1000 ** 3)
                for local in byr_torrents[i:]:
                    if (torrent.file_size + 0.03) * 1000 ** 3 < local.torrent.size:
                        break
                    # 最严格的是一个一个区块的哈希比较，但是可能会有重新做种块大小改变的情况。
                    # 总之这些 PT 站还是比较严格的，文件名大概率有格式可寻，不同种子文件名不同，
                    # 因此比较文件名、文件大小应该可以保证是同一个种子。
                    if self._match_words(local.torrent.name, torrent.title):
                        _debug("关键词提取匹配了 %s 和 %s", local.torrent.name, torrent.title)
                        remote_content = api.download_torrent(torrent.seed_id)
                        if self._torrent_files_exact_match(local, remote_content, torrent):
                            matches.append((local, torrent, remote_content))
        _info("找到 %d 对匹配", len(matches))

        if not dry_run:
            for local, torrent, content in matches:
                self.bt.api.add_torrent(content, torrent, exists=local)

    def download(self, target: typing.Optional[TorrentInfo] = None, dry_run=False, print_scores=False, free_only=False,
                 paused=False, exists: typing.Union[LocalTorrent, bool] = False):
        remote = (
                self.byr.api.list_user_torrents(kind=UserTorrentKind.SEEDING) +
                self.byr.api.list_user_torrents(kind=UserTorrentKind.LEECHING)
        )
        local, scored_local, local_dict = self._gather_local_info(remote)
        if target is None:
            candidates = self._fetch_candidates(scored_local, local_dict, remote, free_only=free_only)
        else:
            _info("准备下载指定种子，将种子的价值设为无穷，去除单次下载量上限")
            candidates = [(target, math.inf)]
            self.planner.max_download_size = self.planner.max_total_size
        if print_scores:
            pretty.pretty_scored_torrents(candidates[:10])

        _info("正在计算最终种子选择")
        disk_remaining = self._get_disk_remaining()
        removable, downloadable, duplicates = self.planner.plan(
            local, scored_local, candidates,
            disk_remaining, self.store,
        )
        estimates = self.planner.estimate(local, removable, downloadable, self.store)
        summary = "\n".join((
            "更改总结：",
            f"最大允许空间占用 {self.planner.max_total_size:.2f} GB，"
            f"本次最大下载量为 {self.planner.max_download_size:.2f} GB",
            f"目前总空间占用 {estimates.before:.2f} GB，"
            f"最后预期总占用 {estimates.after:.2f} GB",
            f"将会删除 {len(removable)} 项内容（共计 {estimates.to_be_deleted:.2f} GB），"
            f"将会下载 {len(downloadable)} 项内容（共计 {estimates.to_be_downloaded:.2f} GB）",
            pretty.pretty_changes(removable, downloadable)
        ))
        if print_scores:
            click.echo_via_pager(summary)
        else:
            _info(summary)
        if dry_run:
            _info("以上计划未被实际运行；若想开始下载，请去除命令行 -d / --dry-run 选项")
        else:
            for t in removable:
                _info("正在删除：%s", t.torrent.name)
                self.bt.api.remove_torrent(t, duplicates[t.torrent.hash])
            for t in downloadable:
                _info("正在添加下载：[%s-%d]%s", t.site, t.seed_id, t.title)
                if t.site == "byr":
                    api = self.byr.api
                else:
                    self.sites[t.site].configure(self.config)
                    api = self.sites[t.site].api
                time.sleep(0.5)
                torrent = api.download_torrent(t.seed_id)
                if isinstance(exists, LocalTorrent):
                    if not self._torrent_files_exact_match(exists, torrent, t):
                        _warning("将要下载的种子与本地文件不符，无法合并种子")
                        continue
                self.bt.api.add_torrent(torrent, t, paused=paused, exists=exists)

    @staticmethod
    def _merge_torrent_list(*lists: list[TorrentInfo]):
        result = {}
        for torrents in lists:
            for torrent in torrents:
                if torrent.seed_id not in result:
                    result[torrent.seed_id] = torrent
        return list(result.values())

    def _match_against_remote(self, pending: list[LocalTorrent], remote: list[TorrentInfo]):
        for local in pending:
            if local.seed_id != 0:
                continue
            for torrent in remote:
                if not self._match_words(torrent.title, local.torrent.name):
                    continue
                info = self.byr.api.torrent(torrent.seed_id)
                torrent_hash = info.hash
                if local.torrent.hash == torrent_hash:
                    local.seed_id = torrent.seed_id
                    local.info = info
                    break

    @staticmethod
    def _extract_torrent_files(content: bytes):
        torrent = bencoder.bdecode(content)
        info = torrent[b"info"]
        root = info[b"name"].decode()
        if b"files" not in info:
            return [(root, info[b"length"])]
        return [(
            "/".join((root, *(segment.decode() for segment in file[b"path"]))),
            file[b"length"],
        ) for file in info[b"files"]]

    @staticmethod
    def _match_words(a: str, b: str):
        separator = re.compile("[\\d -@\\[-`{-~]")
        matches = (set(s.lower() for s in separator.split(a) if len(s) > 3) &
                   set(s.lower() for s in separator.split(b) if len(s) > 3))
        if len(matches) != 0:
            _debug("尝试匹配 %s 与 %s：%s", a, b, matches)
        return len(matches) != 0

    def _gather_local_info(self, remote: list[TorrentInfo]):
        _info("正在合并远端种子列表和本地种子列表信息")
        local = self.bt.api.list_torrents(remote)
        local_dict = dict((t.seed_id, -1) for t in local)

        _info("正在对本地种子评分")
        scored_local = list(filter(lambda t: t[1] >= 0, ((t, self.scorer.score_uploading(t)) for t in local)))
        scored_local.sort(key=lambda t: t[1])
        local_dict.update((t[0].seed_id, i) for i, t in enumerate(scored_local))

        return local, scored_local, local_dict

    def _fetch_candidates(self, scored_local: list[tuple[LocalTorrent, float]], local_dict: dict[int, int],
                          byr_remote: list[TorrentInfo], free_only: bool):
        _info("正在抓取新种子")
        lists = [
            self.byr.api.list_torrents(0),
            self.byr.api.list_torrents(0, sorted_by=NexusSortableField.LEECHER_COUNT),
            self.byr.api.list_torrents(0, promotion=TorrentPromotion.FREE),
        ]
        # 我们只支持批量抓取北邮人的种子，这里的 byr_ids 是为了防止多客户端
        # （例如 NAS 一个，笔记本一个）被禁止下载的情况。
        byr_ids = set(t.seed_id for t in byr_remote)
        fetched = []
        _debug("正在将已下载的种子从新种子列表中除去")
        for torrent in self._merge_torrent_list(*lists):
            if torrent.seed_id in local_dict:
                i = local_dict[torrent.seed_id]
                if i != -1:
                    scored_local[i][0].info = torrent
            elif torrent.seed_id in byr_ids:
                continue
            else:
                fetched.append(torrent)

        if free_only:
            _debug("正在筛选免费促销的种子")
            fetched = [t for t in fetched if PROMOTION_FREE in t.promotions]

        _info("正在对新种子评分")
        candidates = [(t, self.scorer.score_downloading(t)) for t in fetched]
        candidates.sort(key=lambda t: t[1], reverse=True)
        return candidates

    @classmethod
    def _torrent_files_exact_match(cls, local: LocalTorrent, remote_torrent: bytes, remote: TorrentInfo):
        local_files = dict((file.name, file.size) for file in local.torrent.files)
        remote_files = dict(cls._extract_torrent_files(remote_torrent))
        if local_files == remote_files:
            _debug("文件详情匹配：均 %d 文件，文件路径、文件大小完全一致", len(local_files))
            pretty.pretty_comparison(local, remote, local_files, remote_files)
            return True
