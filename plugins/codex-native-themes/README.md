# 皮肤工作室

macOS 实验版 Codex 插件，在面板中管理主题、图片壁纸、渐变、透明与玻璃效果。8 套内置主题可独立使用，无需安装 DSH。

完整效果通过本机调试连接更新 Codex 窗口样式，依赖客户端的运行时结构。原生配色通过 Codex 配置接口保存。Codex 更新后可能需要适配。

## 使用

按[仓库安装说明](../../README.md#安装)安装后，在聊天中说「打开皮肤工作室」。

1. 选择主题、材质与壁纸。
2. 首次点击「开启直接换肤…」，阅读面板中的影响后，确认「重开并自动应用」。Codex 会正常退出并重新打开，可能中断正在运行的任务。正常退出被取消或超时会报告失败，不强制关闭应用。
3. 连接建立后，点击「应用到 Codex」。本次运行中后续换主题无需重开；面板收到窗口回传结果后才显示已应用。普通启动后需要重新建立完整效果的连接。
4. 「暂停并还原」移除样式与壁纸，停止自动恢复，并恢复插件修改前的原生配色。用户后来自行修改的外观字段会保留；保存的原生配色在重新打开 Codex 后加载。

与论文阅读器组合使用时，配色、壁纸、渐变和透明材质会同步到论文页面。原生配色导入码可单独导出，不会自动执行完整效果的应用。

## 环境与路径

需要 macOS、Python 3.11+ 与已有的 Codex 桌面版。优先寻找应用内置 Node，缺少时使用 PATH 中已有的 Node.js 22+，并检查 WebSocket、fetch 和超时接口。Codex CLI 优先从 PATH 寻找，随后寻找应用内的版本。不会自动安装依赖。

应用通过 bundle ID `com.openai.codex` 校验，在系统或用户 Applications 目录及 Spotlight 中查找。非标准安装可设置：

| 环境变量 | 用途 |
| --- | --- |
| `CODEX_DESKTOP_APP` | Codex `.app` 的完整路径，仍需匹配 bundle ID |
| `CODEX_SKIN_NODE` | 已有兼容 Node 可执行文件的完整路径 |
| `CODEX_SKIN_STATE_DIR` | 主题状态目录，默认 `~/.codex/native-themes/` |
| `CODEX_HOME` | Codex 配置目录，默认 `~/.codex/` |
| `DSH_HOME` | 可选 DSH 状态目录，用于同步已有主题 |

这些变量需要传入插件进程；在终端设置变量后，应从同一环境启动宿主，或在本地插件 MCP 配置中设置 `env`。修改市场源码不会自动改变已安装缓存。

## 数据与连接

壁纸、主题库、皮肤选项和外观还原记录保存在本机状态目录。原生配色写入 Codex 配置的 `desktop` 外观字段，并校验配置版本，避免覆盖同时发生的修改。

完整换肤连接仅使用 `127.0.0.1:9341`。开启后可访问 Codex 的调试目标，因此适合可信的本机环境；只在明确确认后重开并开启。普通启动 Codex 即结束本次调试连接。插件不请求远端图片，不调用模型 API，不修改 DSH 状态。

包含 dsh-dream-skin 9.29.0 的 8 套主题颜色：沉静蓝、极光青、星云紫、余烬橙、午夜黑、iOS 扁平、干净明亮、Material 粉。可选同步本机 DSH 状态，或导入 `.dsh-theme.json`、DSH 分享链接和 `codex-theme-v1` 导入码。主题包不包含壁纸；不同应用的组件和材质实现也会产生显示差异。

## 验证范围

当前 macOS 实机已验证主题运行时应用与论文阅读器同步。原生配色持久化使用真实 Codex CLI 与临时配置文件验证，覆盖重新读取、还原、并发版本检查和无关配置保留。配置格式基于 Codex 26.928.40906，DOM 语义锚点基于 26.928.31416。

重开流程使用模拟进程边界测试，尚未执行真实 Codex 重开验收。非标准路径的发现与无关应用排除由临时应用目录测试覆盖。其他 Codex 版本、Windows 与 Linux 未验证。

## 本地开发

在此目录中运行：

```sh
python3 -m unittest -v test_themes test_runtime test_relaunch test_native_settings test_host_environment
node --test test_engine.mjs
python3 server.py --http 8869
```

`--http` 只预览界面，不连接 Codex，也不写换肤状态。`python3 server.py --studio 8870` 启动完整本地面板；只有点击应用或确认连接才执行操作。

原创代码采用 [MIT](LICENSE)，第三方主题颜色的许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
