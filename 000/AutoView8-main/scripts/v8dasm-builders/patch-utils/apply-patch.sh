#!/bin/bash
# apply-patch.sh - 多级退避 V8 Patch 应用脚本
#
# 用法: apply-patch.sh <patch_file> <v8_dir> <log_file> [abort_on_failure]
#
# 参数:
#   patch_file        - patch 文件的绝对路径
#   v8_dir           - V8 源码目录的绝对路径
#   log_file         - 日志文件的绝对路径
#   abort_on_failure - 失败时是否中止 (true/false, 默认: true)

set -e  # 遇到错误时退出（除非显式处理）
set -o pipefail  # 管道中任何命令失败时返回失败状态

# 参数解析
PATCH_FILE="$1"
V8_DIR="$2"
LOG_FILE="$3"
ABORT_ON_FAILURE="${4:-true}"

# 参数验证
if [ -z "$PATCH_FILE" ] || [ -z "$V8_DIR" ] || [ -z "$LOG_FILE" ]; then
    echo "错误: 缺少必需参数"
    echo "用法: $0 <patch_file> <v8_dir> <log_file> [abort_on_failure]"
    exit 1
fi

if [ ! -f "$PATCH_FILE" ]; then
    echo "错误: Patch 文件不存在: $PATCH_FILE"
    exit 1
fi

if [ ! -d "$V8_DIR" ]; then
    echo "错误: V8 目录不存在: $V8_DIR"
    exit 1
fi

# 确保日志目录存在
LOG_DIR=$(dirname "$LOG_FILE")
mkdir -p "$LOG_DIR"

# 初始化日志文件
echo "=====[ V8 Patch Application - Multi-level Fallback ]=====" | tee "$LOG_FILE"
echo "Patch 文件: $PATCH_FILE" | tee -a "$LOG_FILE"
echo "V8 目录: $V8_DIR" | tee -a "$LOG_FILE"
echo "日志文件: $LOG_FILE" | tee -a "$LOG_FILE"
echo "失败时中止: $ABORT_ON_FAILURE" | tee -a "$LOG_FILE"
echo "时间戳: $(date)" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 第0级：强制重置到干净状态
reset_to_clean_state() {
    echo "[第0级] 重置 V8 仓库到干净状态..." | tee -a "$LOG_FILE"
    cd "$V8_DIR"

    # 检查是否有未提交的更改
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "[RESET] 检测到未提交的更改，正在重置..." | tee -a "$LOG_FILE"
        git reset --hard HEAD 2>&1 | tee -a "$LOG_FILE"
        git clean -fd 2>&1 | tee -a "$LOG_FILE"
        echo "[RESET] ✅ 仓库已重置到干净状态" | tee -a "$LOG_FILE"
    else
        echo "[RESET] ✅ 仓库已经是干净状态" | tee -a "$LOG_FILE"
    fi
    echo "" | tee -a "$LOG_FILE"
}

# 第1级：git apply（最干净的方式）
try_git_apply() {
    echo "[第1级] 尝试使用 git apply..." | tee -a "$LOG_FILE"
    cd "$V8_DIR"

    # 先检查是否可以应用
    if git apply --check "$PATCH_FILE" 2>&1 | tee -a "$LOG_FILE"; then
        echo "[LEVEL 1] ✓ Patch 检查通过，正在应用..." | tee -a "$LOG_FILE"
        if git apply --verbose "$PATCH_FILE" 2>&1 | tee -a "$LOG_FILE"; then
            echo "[LEVEL 1] ✅ 成功: Patch 已通过 git apply 应用" | tee -a "$LOG_FILE"
            return 0
        fi
    fi

    echo "[LEVEL 1] ✗ git apply 失败" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    return 1
}

# 检查 patch 是否已经应用（反向检查）
check_already_applied() {
    echo "[检查] 检测 patch 是否已经应用..." | tee -a "$LOG_FILE"
    cd "$V8_DIR"

    if git apply --check --reverse "$PATCH_FILE" 2>&1 | tee -a "$LOG_FILE"; then
        echo "[检查] ✅ Patch 已经应用过，跳过" | tee -a "$LOG_FILE"
        return 0
    fi

    echo "[检查] Patch 尚未应用" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    return 1
}

# 第2级：git apply 三向合并
try_git_apply_3way() {
    echo "[第2级] 尝试使用 git apply 三向合并..." | tee -a "$LOG_FILE"
    cd "$V8_DIR"

    if git apply -3 --verbose "$PATCH_FILE" 2>&1 | tee -a "$LOG_FILE"; then
        # 检查是否有冲突标记
        if git diff --check 2>&1 | grep -q "conflict"; then
            echo "[LEVEL 2] ✗ 三向合并产生了冲突" | tee -a "$LOG_FILE"
            echo "" | tee -a "$LOG_FILE"
            return 1
        fi
        echo "[LEVEL 2] ✅ 成功: Patch 已通过三向合并应用" | tee -a "$LOG_FILE"
        return 0
    fi

    echo "[LEVEL 2] ✗ git apply -3 失败" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    return 1
}

# 第3级：wiggle 模糊匹配（如果可用）
try_wiggle() {
    echo "[第3级] 尝试使用 wiggle 模糊匹配..." | tee -a "$LOG_FILE"

    if ! command -v wiggle &> /dev/null; then
        echo "[LEVEL 3] ⚠️  wiggle 工具未安装，跳过此级别" | tee -a "$LOG_FILE"
        echo "[LEVEL 3] 提示: 可通过以下命令安装 wiggle:" | tee -a "$LOG_FILE"
        echo "[LEVEL 3]   - macOS: brew install wiggle" | tee -a "$LOG_FILE"
        echo "[LEVEL 3]   - Linux: apt-get install wiggle 或 yum install wiggle" | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
        return 1
    fi

    cd "$V8_DIR"

    # wiggle 需要逐个文件处理
    # 这里简化处理：尝试对整个 patch 使用 wiggle
    # 注意：wiggle 的用法比较复杂，这里提供基础实现
    echo "[LEVEL 3] ⚠️  wiggle 集成尚未完全实现（需要拆分 patch 文件）" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    return 1
}

# 第4级：语义化替换（Python 脚本）
try_semantic_patches() {
    echo "[第4级] 尝试使用语义化替换..." | tee -a "$LOG_FILE"

    SCRIPT_DIR=$(dirname "$0")
    SEMANTIC_SCRIPT="$SCRIPT_DIR/semantic-patches.py"

    if [ ! -f "$SEMANTIC_SCRIPT" ]; then
        echo "[LEVEL 4] ✗ 语义化替换脚本不存在: $SEMANTIC_SCRIPT" | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
        return 1
    fi

    # 检查 Python 3 是否可用
    if ! command -v python3 &> /dev/null; then
        echo "[LEVEL 4] ✗ Python 3 未安装" | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
        return 1
    fi

    echo "[LEVEL 4] 正在执行语义化替换脚本..." | tee -a "$LOG_FILE"
    if python3 "$SEMANTIC_SCRIPT" "$V8_DIR" "$LOG_FILE" 2>&1 | tee -a "$LOG_FILE"; then
        echo "[LEVEL 4] ✅ 成功: Patch 已通过语义化替换应用" | tee -a "$LOG_FILE"
        return 0
    fi

    echo "[LEVEL 4] ✗ 语义化替换失败" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
    return 1
}

# 主流程
main() {
    # 第0级：重置到干净状态
    reset_to_clean_state

    # 检查是否已经应用
    if check_already_applied; then
        exit 0
    fi

    # 第1级：git apply
    if try_git_apply; then
        exit 0
    fi

    # 重置后再试第2级
    reset_to_clean_state

    # 第2级：三向合并
    if try_git_apply_3way; then
        exit 0
    fi

    # 重置后再试第3级
    reset_to_clean_state

    # 第3级：wiggle
    if try_wiggle; then
        exit 0
    fi

    # 重置后再试第4级
    reset_to_clean_state

    # 第4级：语义化替换
    if try_semantic_patches; then
        exit 0
    fi

    # 所有方法都失败
    echo "" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"
    echo "❌ 失败: 所有 patch 应用方法都失败了" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"

    if [ "$ABORT_ON_FAILURE" = "true" ]; then
        echo "🛑 由于 patch 应用失败，构建已中止" | tee -a "$LOG_FILE"
        echo "请检查日志文件: $LOG_FILE" | tee -a "$LOG_FILE"
        exit 1
    else
        echo "⚠️  警告: 继续构建但未应用 patch" | tee -a "$LOG_FILE"
        echo "注意: v8dasm 可能功能不完整" | tee -a "$LOG_FILE"
        exit 0
    fi
}

# 执行主流程
main
