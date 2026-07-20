# MIDI2KEY for Genshin

<p align="center"><img src="assets/app-icon.png" width="144" alt="MIDI2KEY for Genshin 应用图标" /></p>

[English](README.md) · [下载最新版](https://github.com/Oceannn233/MIDI2KEY-for-Genshin/releases/latest)

这是一个面向 Windows 的 MIDI 电钢琴到《原神》21 键乐器映射工具。它会把你选择的原调移调到原琴可演奏的 C 大调键位，科学处理和弦按键冲突，实时显示“输入音符 → 映射音符 → 游戏按键”，并且只有在你主动开启输出后才向游戏发送按键。

![MIDI2KEY for Genshin 界面](public/og.png)

## 下载

打开 [最新 Release](https://github.com/Oceannn233/MIDI2KEY-for-Genshin/releases/latest)：

- `MIDI2KEY-for-Genshin-Setup-v1.0.0.exe`：推荐，一键安装 Windows 桌面版。
- `MIDI2KEY-for-Genshin.exe`：绿色单文件版，双击直接运行。

两个版本都不要求单独安装 Python、Node.js 或依赖。因为社区版本暂未购买代码签名证书，Windows 首次运行时可能显示 SmartScreen 提示。

## 使用方法

1. 关闭 DAW、旧版 MIDI 脚本，以及以前连接过 Web MIDI 的浏览器标签页。
2. 用 USB 连接电钢琴并启动 MIDI2KEY for Genshin。
3. 在界面中选择 MIDI 设备、乐曲原调、大小调、映射策略和音区。
4. 先看实时可视化是否符合预期，再开启“游戏输出”。
5. 切回《原神》弹奏；如出现按键未释放，立即点击“紧急释放”。

程序只监听 `127.0.0.1` 本机地址，不会把 MIDI 演奏或设置上传到云端。

## 更科学的映射逻辑

原琴只有 C 大调三个八度的 21 个音，对应 `Z–M`、`A–J`、`Q–U`。程序先按所选调式换算音级，再把结果放入这 21 个可演奏音中。

- **和声优先**：把很短时间内同时按下的音视作和弦，尽量保留和弦结构，为整组统一选择八度，并用唯一分配避免多个音抢同一个游戏键。
- **旋律优先**：每个音独立映射到最近的可演奏音，单音旋律响应更直接。
- **严格音阶**：无法保持音高类别的音直接舍弃，避免偷偷改音造成不和谐。

半音丰富的曲子不可能在纯自然音阶的 21 键原琴上完全无损。界面会把变音修正、冲突消解、八度移动和舍弃音直观显示出来，让你能调节策略，而不是让算法悄悄制造不和谐。

## MIDI 端口被占用

Windows 的 MIDI 输入经常是独占的。出现 `MidiInWinMM::openPort` 时，请关闭所有正在使用电钢琴的程序和网页，等待两秒后点击“重新连接”。本项目的网页界面不会再调用 Web MIDI，只有本地程序持有设备，从根源上避免网页和脚本抢端口。

## 从源码运行

需要 Windows 10/11 和 Python 3.11 以上版本。

```powershell
cd local_app
.\run-local.bat
```

脚本会自动建立隔离环境，并打开 `http://127.0.0.1:17321`。

## 构建 Windows 安装包

```powershell
.\scripts\build-windows.ps1
```

产物位于 `release/windows/`。脚本使用 PyInstaller 打包 Python 和全部运行依赖，再用 Inno Setup 6 生成安装程序。推送版本标签时，仓库内的 GitHub Actions 也会自动构建并发布附件。

## 测试

```powershell
cd local_app
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd ..
npm test
npm run lint
npm run build
```

## 项目结构

- `local_app/`：MIDI 映射核心、本地服务、桌面入口和实际产品界面。
- `app/`：可选的网页介绍及 Release 下载页。
- `scripts/`、`build/windows/`：可复现的 Windows 打包配置。
- `.github/workflows/`：版本标签自动发布流程。

## 安全与边界

本项目只发送普通键盘事件，不注入游戏进程、不读取游戏内存，也不自动演奏曲目。请合理使用，并自行确认适用的游戏规则。

项目采用 [MIT License](LICENSE) 开源。
