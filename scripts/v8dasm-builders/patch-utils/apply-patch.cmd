@echo off
REM apply-patch.cmd - 多级退避 V8 Patch 应用脚本 (Windows 版本)
REM
REM 用法: apply-patch.cmd <patch_file> <v8_dir> <log_file> [abort_on_failure]
REM
REM 参数:
REM   patch_file        - patch 文件的绝对路径
REM   v8_dir           - V8 源码目录的绝对路径
REM   log_file         - 日志文件的绝对路径
REM   abort_on_failure - 失败时是否中止 (true/false, 默认: true)

setlocal enabledelayedexpansion

REM 参数解析
set PATCH_FILE=%~1
set V8_DIR=%~2
set LOG_FILE=%~3
set ABORT_ON_FAILURE=%~4
if "%ABORT_ON_FAILURE%"=="" set ABORT_ON_FAILURE=true

REM 参数验证
if "%PATCH_FILE%"=="" (
    echo 错误: 缺少必需参数
    echo 用法: %~nx0 ^<patch_file^> ^<v8_dir^> ^<log_file^> [abort_on_failure]
    exit /b 1
)

if "%V8_DIR%"=="" (
    echo 错误: 缺少必需参数
    echo 用法: %~nx0 ^<patch_file^> ^<v8_dir^> ^<log_file^> [abort_on_failure]
    exit /b 1
)

if "%LOG_FILE%"=="" (
    echo 错误: 缺少必需参数
    echo 用法: %~nx0 ^<patch_file^> ^<v8_dir^> ^<log_file^> [abort_on_failure]
    exit /b 1
)

if not exist "%PATCH_FILE%" (
    echo 错误: Patch 文件不存在: %PATCH_FILE%
    exit /b 1
)

if not exist "%V8_DIR%" (
    echo 错误: V8 目录不存在: %V8_DIR%
    exit /b 1
)

REM 确保日志目录存在
for %%F in ("%LOG_FILE%") do set LOG_DIR=%%~dpF
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM 初始化日志文件
echo =====[ V8 Patch Application - Multi-level Fallback ]===== > "%LOG_FILE%"
echo Patch 文件: %PATCH_FILE% >> "%LOG_FILE%"
echo V8 目录: %V8_DIR% >> "%LOG_FILE%"
echo 日志文件: %LOG_FILE% >> "%LOG_FILE%"
echo 失败时中止: %ABORT_ON_FAILURE% >> "%LOG_FILE%"
echo 时间戳: %date% %time% >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

echo =====[ V8 Patch Application - Multi-level Fallback ]=====
echo Patch 文件: %PATCH_FILE%
echo V8 目录: %V8_DIR%
echo 日志文件: %LOG_FILE%
echo 失败时中止: %ABORT_ON_FAILURE%
echo 时间戳: %date% %time%
echo.

REM 第0级：强制重置到干净状态
:reset_to_clean_state
echo [第0级] 重置 V8 仓库到干净状态...
echo [第0级] 重置 V8 仓库到干净状态... >> "%LOG_FILE%"
cd /d "%V8_DIR%"

REM 检查是否有未提交的更改
git diff --quiet >nul 2>&1
if errorlevel 1 (
    echo [RESET] 检测到未提交的更改，正在重置...
    echo [RESET] 检测到未提交的更改，正在重置... >> "%LOG_FILE%"
    git reset --hard HEAD >> "%LOG_FILE%" 2>&1
    git clean -fd >> "%LOG_FILE%" 2>&1
    echo [RESET] ✅ 仓库已重置到干净状态
    echo [RESET] ✅ 仓库已重置到干净状态 >> "%LOG_FILE%"
) else (
    echo [RESET] ✅ 仓库已经是干净状态
    echo [RESET] ✅ 仓库已经是干净状态 >> "%LOG_FILE%"
)
echo.
echo. >> "%LOG_FILE%"

REM 检查 patch 是否已经应用（反向检查）
:check_already_applied
echo [检查] 检测 patch 是否已经应用...
echo [检查] 检测 patch 是否已经应用... >> "%LOG_FILE%"
cd /d "%V8_DIR%"

git apply --check --reverse "%PATCH_FILE%" >nul 2>&1
if %errorlevel% equ 0 (
    echo [检查] ✅ Patch 已经应用过，跳过
    echo [检查] ✅ Patch 已经应用过，跳过 >> "%LOG_FILE%"
    exit /b 0
)

echo [检查] Patch 尚未应用
echo [检查] Patch 尚未应用 >> "%LOG_FILE%"
echo.
echo. >> "%LOG_FILE%"

REM 第1级：git apply（最干净的方式）
:try_git_apply
echo [第1级] 尝试使用 git apply...
echo [第1级] 尝试使用 git apply... >> "%LOG_FILE%"
cd /d "%V8_DIR%"

git apply --check "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
if %errorlevel% equ 0 (
    echo [LEVEL 1] ✓ Patch 检查通过，正在应用...
    echo [LEVEL 1] ✓ Patch 检查通过，正在应用... >> "%LOG_FILE%"
    git apply --verbose "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
    if %errorlevel% equ 0 (
        echo [LEVEL 1] ✅ 成功: Patch 已通过 git apply 应用
        echo [LEVEL 1] ✅ 成功: Patch 已通过 git apply 应用 >> "%LOG_FILE%"
        exit /b 0
    )
)

echo [LEVEL 1] ✗ git apply 失败
echo [LEVEL 1] ✗ git apply 失败 >> "%LOG_FILE%"
echo.
echo. >> "%LOG_FILE%"

REM 重置后再试第2级
call :reset_to_clean_state

REM 第2级：git apply 三向合并
:try_git_apply_3way
echo [第2级] 尝试使用 git apply 三向合并...
echo [第2级] 尝试使用 git apply 三向合并... >> "%LOG_FILE%"
cd /d "%V8_DIR%"

git apply -3 --verbose "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
if %errorlevel% equ 0 (
    REM 检查是否有冲突标记
    git diff --check 2>&1 | findstr /C:"conflict" >nul
    if errorlevel 1 (
        echo [LEVEL 2] ✅ 成功: Patch 已通过三向合并应用
        echo [LEVEL 2] ✅ 成功: Patch 已通过三向合并应用 >> "%LOG_FILE%"
        exit /b 0
    ) else (
        echo [LEVEL 2] ✗ 三向合并产生了冲突
        echo [LEVEL 2] ✗ 三向合并产生了冲突 >> "%LOG_FILE%"
    )
)

echo [LEVEL 2] ✗ git apply -3 失败
echo [LEVEL 2] ✗ git apply -3 失败 >> "%LOG_FILE%"
echo.
echo. >> "%LOG_FILE%"

REM 重置后再试第3级
call :reset_to_clean_state

REM 第3级：git apply --ignore-whitespace
:try_git_apply_ignore_whitespace
echo [第3级] 尝试使用 git apply --ignore-whitespace...
echo [第3级] 尝试使用 git apply --ignore-whitespace... >> "%LOG_FILE%"
cd /d "%V8_DIR%"

git apply --ignore-whitespace --verbose "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
if %errorlevel% equ 0 (
    echo [LEVEL 3] ✅ 成功: Patch 已通过 --ignore-whitespace 应用
    echo [LEVEL 3] ✅ 成功: Patch 已通过 --ignore-whitespace 应用 >> "%LOG_FILE%"
    exit /b 0
)

echo [LEVEL 3] ✗ git apply --ignore-whitespace 失败
echo [LEVEL 3] ✗ git apply --ignore-whitespace 失败 >> "%LOG_FILE%"
echo.
echo. >> "%LOG_FILE%"

REM 重置后再试第4级
call :reset_to_clean_state

REM 第4级：语义化替换（Python 脚本）
:try_semantic_patches
echo [第4级] 尝试使用语义化替换...
echo [第4级] 尝试使用语义化替换... >> "%LOG_FILE%"

set SCRIPT_DIR=%~dp0
set SEMANTIC_SCRIPT=%SCRIPT_DIR%semantic-patches.py

if not exist "%SEMANTIC_SCRIPT%" (
    echo [LEVEL 4] ✗ 语义化替换脚本不存在: %SEMANTIC_SCRIPT%
    echo [LEVEL 4] ✗ 语义化替换脚本不存在: %SEMANTIC_SCRIPT% >> "%LOG_FILE%"
    echo.
    echo. >> "%LOG_FILE%"
    goto :all_failed
)

REM 检查 Python 3 是否可用
where python3 >nul 2>&1
if errorlevel 1 (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [LEVEL 4] ✗ Python 未安装
        echo [LEVEL 4] ✗ Python 未安装 >> "%LOG_FILE%"
        echo.
        echo. >> "%LOG_FILE%"
        goto :all_failed
    )
    set PYTHON_CMD=python
) else (
    set PYTHON_CMD=python3
)

echo [LEVEL 4] 正在执行语义化替换脚本...
echo [LEVEL 4] 正在执行语义化替换脚本... >> "%LOG_FILE%"
%PYTHON_CMD% "%SEMANTIC_SCRIPT%" "%V8_DIR%" "%LOG_FILE%" >> "%LOG_FILE%" 2>&1
if %errorlevel% equ 0 (
    echo [LEVEL 4] ✅ 成功: Patch 已通过语义化替换应用
    echo [LEVEL 4] ✅ 成功: Patch 已通过语义化替换应用 >> "%LOG_FILE%"
    exit /b 0
)

echo [LEVEL 4] ✗ 语义化替换失败
echo [LEVEL 4] ✗ 语义化替换失败 >> "%LOG_FILE%"
echo.
echo. >> "%LOG_FILE%"

REM 所有方法都失败
:all_failed
echo.
echo ========================================
echo ❌ 失败: 所有 patch 应用方法都失败了
echo ========================================
echo.
echo. >> "%LOG_FILE%"
echo ======================================== >> "%LOG_FILE%"
echo ❌ 失败: 所有 patch 应用方法都失败了 >> "%LOG_FILE%"
echo ======================================== >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

if /i "%ABORT_ON_FAILURE%"=="true" (
    echo 🛑 由于 patch 应用失败，构建已中止
    echo 请检查日志文件: %LOG_FILE%
    echo 🛑 由于 patch 应用失败，构建已中止 >> "%LOG_FILE%"
    echo 请检查日志文件: %LOG_FILE% >> "%LOG_FILE%"
    exit /b 1
) else (
    echo ⚠️  警告: 继续构建但未应用 patch
    echo 注意: v8dasm 可能功能不完整
    echo ⚠️  警告: 继续构建但未应用 patch >> "%LOG_FILE%"
    echo 注意: v8dasm 可能功能不完整 >> "%LOG_FILE%"
    exit /b 0
)
