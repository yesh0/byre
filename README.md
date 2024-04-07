# byre - 一款北邮人 PT 命令行操作软件

（示例图片用的 asciinema 的中文渲染有问题，将就着看吧。）

[![asciicast](https://asciinema.org/a/570391.svg)](https://asciinema.org/a/570391)

- **命令行访问站点**：可以在命令行查看北邮人站点的种子列表、用户信息、种子信息等等。

- **qBittorrent 种子管理**：可以将本地的种子与北邮人的种子关联起来，以列表展示。

- **种子自动下载**：

  - **下载特定种子**：给定一个种子 ID，自动下载 `.torrent` 文件，开始 qBittorrent 下载，
    重命名为容易识别的下载任务名称，并打上对应站点的标签（`byr` 或 `tju`）以方便管理。

    这边建议是先稍微手动下载一些热门免费种子保证有一定的上传量先，不然落到 Peasant 的话，
    很多站点都会有强制的告示之类的，程序肯定会出错。
    （或者也可以用 `--free-only` 让自动下载只下载免费的种子，以免程序操盘失误。投资有风险！）

    用 `byre do download --help` 查看用法。

  - **共同种子识别**：

    - **手动**：对于用户指定的一个本地下载完成的种子和一个其它 PT 站点的种子，
      如果两个种子对应的文件完全相同，则可以跳过后者的下载、校验，直接开始做种。

      用 `byre do download --help` 查看用法，使用 `--same` 选项。

    - **自动**：自动抓取 PT 站点的热门种子，与本地已有的种子对比，
      如果有种子相同且来源的 PT 站不同，则自动开始做另外的 PT 站的种。

      因为感觉上搜索还是挺耗服务器性能的，所以这里不进行搜索而是直接在种子列表看运气。

      用 `byre do hitchhike --help` 查看用法。

  - **种子自动下载刷流**：

    **（试验性）** 自动选取北邮人站点上相对热门的种子进行下载，在存储空间不足的情况下，
    自动识别本地的冷门种子进行删除。

    用 `byre do main --help` 查看用法。

    如果想要让一些冷门种子不被删除（例如想要留到有空的时候再看的电影等），可以给种子打上 `keep` 标签。

## 使用方法

### 安装

```console
$ git clone https://github.com/yesh0/byre.git
$ pip3 install --use-pep517 ./byre
$ byre
Usage: byre [OPTIONS] COMMAND [ARGS]...

  北邮人命令行操作以及 BT 软件整合实现。

  软件主要通过 qBittorrent 的标签功能来标记北邮人 PT 的种子， 再在种子名称前加入 ``[byr-北邮人ID]`` 来建立本地种子与
  北邮人种子的关联。

  详细的使用说明请见代码仓库的 README 文件：

      https://github.com/yesh0/byre

选项:
  -c, --config 配置文件路径  TOML 格式配置文件
  -v, --verbose        输出详细信息
  --help               显示此消息并退出。

命令:
  byr    访问北邮人 PT 站。
  do     综合 PT 站点与本地的命令，主要功能所在。
  qbt    访问 qBittorrent 信息。
  setup  配置 byre、下载并配置 qBittorrent-nox。
  tju    访问北洋园 PT 站。
```

### 配置方法一

1. 启动 qBittorrent，开启 Web UI
2. 设置配置文件：使用 `byre setup` 命令来交互式配置。
3. 试试 `byre do main --dry-run --print` 吧。

### 配置方法二（Linux）

使用 `byre setup` 来进行配置，并自动下载、配置 qBittorrent。

### 手动编辑配置文件

请见 [byre.example.toml](byre/setup/byre.example.toml)，里面有比较详细的注释说明。总之需要填写：
- 北邮人用户名、密码
- qBittorrent 用户名、密码、端口等
- 下载位置
- 最大允许的占用空间上限、一次下载量上限

### 自动刷流配置

自动刷流需要一些外部的配置：
- 在 Linux 下可以使用 `crontab` 来定时运行 `byre**。
- Windows 我不知道（欢迎提供思路）。
- macOS 我更不知道（欢迎提供思路）。

我个人定时运行的命令是 `byre do main --free-only && byre do hitchhike` 。

### 北洋园相关

本脚本曾经支持过北洋园，但是因为现在北洋园禁用脚本，所以本仓库不计划继续更新和测试相关内容。
北洋园的相关功能仍然可以通过命令行调用，但是我们不保证其可以正常工作，
并可能会在后续的版本中移除相关代码。相关功能包括：

- `byre tju` 访问北洋园 PT 站的所有子命令
- `byre qbt --pt tju`
- `byre do download --at tju`
- `byre do hitchhike`
- `byre do main --at tju`

不使用有上述参数的命令的话理论上不需要配置北洋园相关的东西。

1. 关于北洋园使用的 **警告** ：[北洋园禁止脚本](https://www.tjupt.org/forums.php?action=viewtopic&topicid=16580)，请不要使用相关功能。
   现在北洋园使用的是 H&R 机制，基本上可以不用担心分享率，所以这里其实更推荐直接用 RSS 配合 qBittorrent 等来直接自动下载。
   qBittorrent 里也可以对种子进行一定的限制，例如：
   - 在[获取 RSS](https://www.tjupt.org/getrss.php) 时勾选 `[大小]` 则可以通过 qBittorrent 的正则进行大小的筛选：
     - 在“Must Not Contain”里填入 `MiB` 可以排除小于 1 GiB 的种子，
     - 填入 `TiB|GiB|(\[\d{4}\.\d{2} MiB)|(\[\d{2}\.\d{2} MiB)|(\[[1-2]\d{2}\.\d{2} MiB)` 则可以将种子大小限制在大约 1 GiB 以下，300 MiB 以上。
   - 勾选 `[发布者]` 则可以通过在“Must Contain”里填入发布者名字来筛选相对可靠的资源。
   个人认为这样已经足够刷流（以及刷升级所需的下载数量）了。（但你需要隔段时间去删删种子。）

2. 北洋园站点无法下载？

   北洋园在第一次下载种子时会跳转到一个“第一次下载提示”页面，你需要手动去下载一个种子然后勾选“下次不再提示”。

3. 北洋园还是无法下载？

   有可能站点发公告了，不手动点击“已读”的话是没法进行任何操作的。请登录站点读公告。

## 愿望清单

- [X] 自动创建配置文件并进行交互式配置。

- [X] 自动下载 qBittorrent，根据配置文件配置好。（目前只支持 Linux（SystemD）。）

- [X] 支持多个 NexusPHP 站点：

  - 目标：
    - [X] 提供不同站点的爬虫 API 接口。
    - [X] 实现不同站点（北邮人、北洋园等）在刷流同时的自动跨站辅种。
    - [X] 相同种子识别机制（以及储存空间计算的调整和删除机制调整）。
    - [ ] 跨站点种子评分机制……说不定还是需要用户指定一个主站（而例如北洋园还有额外的机制）。
      目前是北邮人为主，其它站点纯粹用北邮人下载的内容来做种。
      （就算这样，我这边 15 个北邮人种子也有 12 个能在北洋园找到，虽然要人工找。）

- [X] 让用户可以更轻松地指定最大可用空间（自动计算硬盘剩余空间）。

- [X] 多块硬盘/多分区支持（指定不同下载目录即可），暂时不支持一个分区里放两个下载目录或是 Linux 子目录下的挂载。

- [ ] 心态转变：提供一个跨站种子复活的功能，当用户刷流刷够了之后可以考虑做做慈善（也刷魔力值利人利己）。

  目前看到的比较可行的是对接 [IYUU](https://github.com/ledccn/IYUUAutoReseed) 或是 [Reseed](https://github.com/tongyifan/Reseed-backend)，
  但这两看起来后端都不是开源的，而且 API 也比较难用。（抱歉我真的看到微信扫码就头疼。）

  其实自己写一个也真的不难，但缺动力，看看各位有没有需求吧。

## 为什么要自己造轮子？

1. 个人对[没有空格的代码](https://github.com/WhymustIhaveaname/ByrBtAutoDownloader/blob/main/byrbt.py)过敏，
   症状包括且不限于浑身发痒、拳头发硬等等。
2. 个人用的是 [qBittorrent](https://www.qbittorrent.org/) 所以想把北邮人 API 部分和种子管理部分好好分离开来。
3. 谁知道呢？说不定只是手痒想写写代码罢了。

## 许可证相关

- [byre/decaptcha](./byre/decaptcha) 里的代码基本是照搬 [bumzy/decaptcha](https://github.com/bumzy/decaptcha) 的。
- [byre/scoring.py](./byre/scoring.py) 里的种子评分的计算方法基本按照
  [WhymustIhaveaname/ByrBtAutoDownloader](https://github.com/WhymustIhaveaname/ByrBtAutoDownloader) 的来。
- [byre/locales](./byre/locales) 里放了一些我对 [click](https://github.com/pallets/click) 的翻译。
