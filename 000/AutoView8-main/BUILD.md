# V8 Disassembler (v8dasm) 本地编译指南

本指南说明如何在本地环境编译 v8dasm 反汇编器。

## 目录

- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [详细步骤](#详细步骤)
- [常见问题](#常见问题)

---

## 环境要求

### Linux

```bash
sudo apt-get update
sudo apt-get install -y \
    pkg-config \
    git \
    curl \
    wget \
    build-essential \
    python3 \
    python3-pip \
    xz-utils \
    zip \
    clang \
    lld
```

### macOS

```bash
# 安装 Xcode Command Line Tools
xcode-select --install

# 安装 Homebrew (如果未安装)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 可选: 安装 Python 3
brew install python@3
```

### Windows

1. 安装 [Visual Studio 2022](https://visualstudio.microsoft.com/downloads/) (Community 版本即可)
   - 选择 "Desktop development with C++" 工作负载
   - 确保安装了 Clang 编译器组件

2. 安装 [Python 3](https://www.python.org/downloads/)

3. 安装 [Git](https://git-scm.com/download/win)

---

## 快速开始

### 1. 克隆仓库

```bash
git clone <your-repo-url>
cd AutoView8
```

### 2. 选择要编译的 V8 版本

查看可用版本:

```bash
cat configs/v8-versions.json
```

当前支持的版本:
- **9.4.146.24** (Node.js v16.x)
- **10.2.154.26** (Node.js v18.x)
- **11.3.244.8** (Node.js v20.x)

### 3. 运行编译脚本

#### Linux

```bash
cd scripts/v8dasm-builders
chmod +x build-linux.sh
./build-linux.sh 10.2.154.26 "v8_enable_pointer_compression=false"
```

#### macOS Intel

```bash
cd scripts/v8dasm-builders
chmod +x build-macos-intel.sh
./build-macos-intel.sh 10.2.154.26 "v8_enable_pointer_compression=false"
```

#### macOS Apple Silicon

```bash
cd scripts/v8dasm-builders
chmod +x build-macos-arm.sh
./build-macos-arm.sh 10.2.154.26 "v8_enable_pointer_compression=false"
```

#### Windows

```cmd
cd scripts\v8dasm-builders
build-windows.cmd 10.2.154.26 "v8_enable_pointer_compression=false"
```

### 4. 查找编译产物

编译成功后,可执行文件位于:

```
~/v8/v8/v8dasm-{版本号}
```

例如:
- Linux/macOS: `~/v8/v8/v8dasm-10.2.154.26`
- Windows: `%HOMEPATH%\v8\v8\v8dasm-10.2.154.26.exe`

---

## 详细步骤

### 编译流程详解

编译脚本会执行以下步骤:

1. **环境检测** - 自动检测是本地环境还是 GitHub Actions 环境
2. **获取 Depot Tools** - 下载 Chromium 的构建工具
3. **获取 V8 源码** - 使用 `fetch v8` 获取完整的 V8 源码
4. **Checkout 指定版本** - 切换到指定的 V8 版本标签
5. **应用补丁** - 应用 `view8-jsc-decode/Disassembler/v8.patch` 补丁
   - 支持多级回退策略 (直接应用 → 三路合并 → 忽略空白)
6. **配置构建** - 使用 GN 生成构建配置
7. **构建 V8** - 使用 Ninja 构建 `v8_monolith` 静态库
8. **编译 v8dasm** - 链接 V8 静态库编译反汇编器

### 构建参数说明

```bash
./build-linux.sh <V8_VERSION> <BUILD_ARGS>
```

- **V8_VERSION**: V8 版本号 (如 `10.2.154.26`)
- **BUILD_ARGS**: 额外的 GN 构建参数 (可选)

常用构建参数:
- `v8_enable_pointer_compression=false` - 禁用指针压缩 (Node.js 版本需要)
- `v8_enable_pointer_compression=true` - 启用指针压缩 (Electron 版本需要)
- `v8_enable_sandbox=true` - 启用沙箱 (Electron 版本需要)

### 为不同目标编译

#### Node.js 版本

```bash
./build-linux.sh 10.2.154.26 "v8_enable_pointer_compression=false"
```

#### Electron 版本

```bash
./build-linux.sh 10.8.168.25 "v8_enable_pointer_compression=true v8_enable_sandbox=true"
```

---

## 使用编译的 v8dasm

### 基本用法

```bash
# 反汇编 JSC 文件
~/v8/v8/v8dasm-10.2.154.26 input.jsc > output.txt
```

### 配合 View8 使用

```bash
# 使用 View8 完整反编译
python view8.py input.jsc output.js --path ~/v8/v8/v8dasm-10.2.154.26
```

### 复制到系统路径 (可选)

#### Linux/macOS

```bash
# 复制到本地 bin 目录
cp ~/v8/v8/v8dasm-10.2.154.26 ~/bin/v8dasm
chmod +x ~/bin/v8dasm

# 或复制到系统目录
sudo cp ~/v8/v8/v8dasm-10.2.154.26 /usr/local/bin/v8dasm
```

#### Windows

```cmd
REM 复制到 PATH 中的目录
copy %HOMEPATH%\v8\v8\v8dasm-10.2.154.26.exe C:\Windows\System32\v8dasm.exe
```

---

## 常见问题

### Q: 编译需要多长时间?

**A:** 首次编译:
- Linux: 约 45-60 分钟
- macOS: 约 50-70 分钟
- Windows: 约 60-90 分钟

后续编译 (如果 V8 源码未变化): 约 10-20 分钟

### Q: 补丁应用失败怎么办?

**A:** 脚本使用多级回退策略:
1. 直接应用补丁
2. 检查是否已应用 (跳过)
3. 三路合并
4. 忽略空白字符差异

如果全部失败,可能需要手动解决冲突:
```bash
cd ~/v8/v8
git apply -3 /path/to/v8.patch
# 手动解决冲突后
git add .
git am --continue
```

### Q: 如何清理构建缓存?

**A:** 删除 V8 目录重新编译:
```bash
rm -rf ~/v8
```

### Q: 编译时内存不足怎么办?

**A:** 限制 Ninja 并行任务数:
```bash
# 修改脚本中的 ninja 命令
ninja -C out.gn/x64.release -j2 v8_monolith
```

### Q: 如何编译其他 V8 版本?

**A:** 找到目标 V8 版本号:
1. 访问 [V8 Releases](https://chromium.googlesource.com/v8/v8.git/+refs)
2. 查找对应的 Node.js 或 Electron 版本
3. 使用版本号运行编译脚本

例如 Node.js v22 (V8 12.4.254.14):
```bash
./build-linux.sh 12.4.254.14 "v8_enable_pointer_compression=false"
```

### Q: Windows 下找不到 clang++?

**A:** 确保在 Visual Studio Developer Command Prompt 中运行:
1. 打开 "x64 Native Tools Command Prompt for VS 2022"
2. 运行编译脚本

或者在普通命令行中初始化 VS 环境:
```cmd
"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
```

### Q: macOS 下提示 xcrun: error?

**A:** 安装或重新安装 Xcode Command Line Tools:
```bash
sudo rm -rf /Library/Developer/CommandLineTools
xcode-select --install
```

### Q: 如何验证编译产物?

**A:** 检查文件信息:
```bash
# Linux/macOS
file ~/v8/v8/v8dasm-10.2.154.26
ldd ~/v8/v8/v8dasm-10.2.154.26  # 查看依赖库

# 测试运行
~/v8/v8/v8dasm-10.2.154.26 --help  # 可能无输出,这是正常的
```

---

## 高级用法

### 并行编译多个版本

```bash
# 编译所有支持的版本
for version in 9.4.146.24 10.2.154.26 11.3.244.8; do
    echo "编译 V8 $version..."
    ./build-linux.sh $version "v8_enable_pointer_compression=false" &
done
wait
echo "所有版本编译完成"
```

### 自定义构建配置

创建自定义构建参数文件 `custom-build.args`:
```
target_os = "linux"
target_cpu = "x64"
is_component_build = false
is_debug = true  # 启用调试模式
v8_monolithic = true
v8_enable_disassembler = true
v8_enable_object_print = true
symbol_level = 2  # 包含完整调试符号
```

修改脚本使用自定义配置。

---

## 相关资源

- [V8 官方文档](https://v8.dev/docs)
- [V8 构建指南](https://v8.dev/docs/build)
- [Depot Tools 文档](https://commondatastorage.googleapis.com/chrome-infra-docs/flat/depot_tools/docs/html/depot_tools_tutorial.html)
- [View8 项目](./README-View8.md)

---

## 故障排查

如遇到问题,请按以下步骤排查:

1. **检查日志** - 编译脚本会输出详细日志
2. **验证环境** - 确保所有依赖都已安装
3. **检查磁盘空间** - V8 编译需要约 20-30 GB 空间
4. **查看 V8 官方文档** - 参考最新的构建说明
5. **提交 Issue** - 如果问题持续,请在 GitHub 提交 Issue

---

**最后更新**: 2026-01-30
