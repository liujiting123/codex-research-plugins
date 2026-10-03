# Codex Research Plugins

在 Codex 中并排读论文，并让阅读器跟随桌面主题。

Two local Codex plugins: an original-PDF reader beside chat, and an experimental macOS theme studio. No extra model API key is required.

| 插件 | 功能 | 状态 |
| --- | --- | --- |
| [论文阅读器](plugins/paper-reader/README.md) | 搜索 Zotero、读原始 PDF、选段问答、页码引用；跟随 Codex 配色 | 0.2.6，已在 macOS Codex 原生面板验证阅读与主题同步 |
| [皮肤工作室](plugins/codex-native-themes/README.md) | 8 套主题、壁纸、渐变、透明与玻璃效果；同步阅读器 | 0.1.2，macOS 实验版，依赖 Codex 运行时结构 |

这是社区维护的 GitHub 插件市场。两个插件可以分别安装，也可以组合使用。

## 安装

需要支持插件与 MCP Apps 的 Codex 桌面版，以及终端中可用的 `codex`、Git 和 Python 3.11+。`python3` 必须能被 Codex 插件进程找到。

```sh
codex plugin marketplace add liujiting123/codex-research-plugins
codex plugin add paper-reader@codex-research-plugins
codex plugin add codex-native-themes@codex-research-plugins
```

只需要读论文时，执行前两行即可。安装后重新打开 Codex，使新插件进入当前会话；在聊天里说「打开论文阅读器」或「打开皮肤工作室」。支持内容标签页入口的客户端，也可以从当前聊天右上角「＋」打开阅读器。

论文阅读器使用本机 Zotero Desktop 的本地 API。需要 Zotero 正在运行，并启用 `extensions.zotero.httpServer.localAPI.enabled`。也可在阅读器中直接选择本地 PDF，此模式不要求 Zotero。`pdftotext`、`pdfinfo`、`pdftoppm` 为可选的 Poppler 工具，分别用于模型读取原文、统计页数和核对页面图像；浏览器显示 PDF 不依赖它们。

皮肤工作室需要 macOS。优先使用 Codex 内置 Node，缺少时使用已有的 Node.js 22+，并检查是否支持 WebSocket。首次完整换肤需在面板中确认重开 Codex；重开可能中断正在运行的任务。具体行为与兼容限制见[皮肤工作室说明](plugins/codex-native-themes/README.md)。

## ZIP 分发

[Releases](https://github.com/liujiting123/codex-research-plugins/releases) 提供完整市场 ZIP。解压后，在包含 `.agents/` 与 `plugins/` 的目录中执行：

```sh
codex plugin marketplace add .
codex plugin add paper-reader@codex-research-plugins
codex plugin add codex-native-themes@codex-research-plugins
```

这是本地安装方式；需要保留解压后的市场目录，以便后续更新。ZIP 不包含 Python、Node、Codex、Zotero 或 Poppler。

## 数据与权限

论文阅读器只读本地 Zotero 与 PDF。PDF 字节按需送到阅读界面，用户选段、标题和页码在点击问答时进入当前聊天；模型可通过工具获取指定页的文字或图像。聊天消息由当前 Codex 会话及其模型处理。

皮肤工作室保存本地主题设置，修改 Codex 的原生外观字段，并通过 `127.0.0.1:9341` 调试连接更新窗口样式。开启连接与重开需要在面板明确确认。插件没有公网服务，不请求远端图片；壁纸保存在本机。暂停时恢复插件修改前的配色，并保留用户后来自行修改的外观字段。

卸载皮肤插件前，建议先在面板点击「暂停并还原」，否则已保存的原生配色会继续存在。普通启动 Codex 会结束这次调试连接。

## 开发与验证

Python 后端使用标准库，前端依赖随包提供。使用已有环境：

```sh
cd plugins/paper-reader
python3 -m unittest discover -s tests -v
node --check ui/reader.js
```

```sh
cd plugins/codex-native-themes
python3 -m unittest -v test_themes test_runtime test_relaunch test_native_settings test_host_environment
node --check skin.mjs
node --check engine.mjs
node --test test_engine.mjs
```

原生配色检查使用真实 Codex CLI 和临时配置目录。重开流程的进程边界使用模拟测试，尚未执行真实应用重开验收。当前实机验证平台为 macOS；Windows 与 Linux 未验证，皮肤插件的完整效果仅支持 macOS。Codex 更新后，运行时锚点与外观配置格式可能需要适配。

## 许可证

原创代码采用 [MIT](LICENSE)。阅读器包含 [PDF.js 5.6.205](https://github.com/mozilla/pdf.js)，保留其 [Apache 2.0 许可证](plugins/paper-reader/vendor/PDFJS-LICENSE)。主题颜色来自 [dsh-dream-skin 9.29.0](https://github.com/RevolutionLA/dsh-dream-skin)，保留其 [MIT 声明](plugins/codex-native-themes/THIRD_PARTY_NOTICES.md)。

插件结构参考 [Codex 插件开发文档](https://developers.openai.com/plugins/build/plugins)。
