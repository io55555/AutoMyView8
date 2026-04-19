@echo off
setlocal enabledelayedexpansion

set V8_VERSION=%~1
set BUILD_ARGS=%~2

echo ==========================================
echo Building v8dasm for Windows x64
echo V8 Version: %V8_VERSION%
echo Build Args: %BUILD_ARGS%
echo ==========================================

if "%V8_VERSION%"=="" (
    echo ERROR: Missing V8 version argument.
    exit /b 1
)

REM 检测运行环境 (GitHub Actions 或本地)
if "%GITHUB_WORKSPACE%"=="" (
    echo 检测到本地环境
    set WORKSPACE_DIR=%~dp0\..\..
    set IS_LOCAL=true
    echo 本地环境，跳过依赖安装 (请确保已安装: git, python, Visual Studio/clang^)
) else (
    echo 检测到 GitHub Actions 环境
    set WORKSPACE_DIR=%GITHUB_WORKSPACE%
    set IS_LOCAL=false
)

for %%I in ("%WORKSPACE_DIR%") do set WORKSPACE_DIR=%%~fI
echo 工作空间: %WORKSPACE_DIR%

if not exist "%WORKSPACE_DIR%\artifacts" mkdir "%WORKSPACE_DIR%\artifacts"
if not exist "%WORKSPACE_DIR%\artifacts\logs" mkdir "%WORKSPACE_DIR%\artifacts\logs"

set BUILD_LOG=%WORKSPACE_DIR%\artifacts\logs\build-windows-%V8_VERSION%.log
set FETCH_LOG=%WORKSPACE_DIR%\artifacts\logs\fetch-v8-%V8_VERSION%.log
set SYNC_LOG=%WORKSPACE_DIR%\artifacts\logs\gclient-sync-%V8_VERSION%.log
set GN_LOG=%WORKSPACE_DIR%\artifacts\logs\gn-gen-%V8_VERSION%.log
set NINJA_LOG=%WORKSPACE_DIR%\artifacts\logs\ninja-%V8_VERSION%.log
set CLANG_LOG=%WORKSPACE_DIR%\artifacts\logs\clang-%V8_VERSION%.log
set PATCH_LOG=%WORKSPACE_DIR%\artifacts\logs\patch-%V8_VERSION%.log

del /q "%BUILD_LOG%" "%FETCH_LOG%" "%SYNC_LOG%" "%GN_LOG%" "%NINJA_LOG%" "%CLANG_LOG%" "%PATCH_LOG%" 2>nul

echo =====[ Environment Summary ]=====
echo Workspace: %WORKSPACE_DIR%
echo Home: %HOMEDRIVE%%HOMEPATH%
echo Runner temp: %RUNNER_TEMP%
echo BUILD_LOG: %BUILD_LOG%
echo PATCH_LOG: %PATCH_LOG%
echo GN_LOG: %GN_LOG%
echo NINJA_LOG: %NINJA_LOG%
echo CLANG_LOG: %CLANG_LOG%
echo =====[ Environment Summary ]===== > "%BUILD_LOG%"
echo Workspace: %WORKSPACE_DIR% >> "%BUILD_LOG%"
echo Home: %HOMEDRIVE%%HOMEPATH% >> "%BUILD_LOG%"
echo Runner temp: %RUNNER_TEMP% >> "%BUILD_LOG%"
echo PATH: %PATH% >> "%BUILD_LOG%"
echo GITHUB_WORKSPACE: %GITHUB_WORKSPACE% >> "%BUILD_LOG%"
echo. >> "%BUILD_LOG%"

echo =====[ Tool Versions ]=====
where git
git --version
where python
python --version
where clang++
clang++ --version
where link
where gn
where ninja
where fetch
where gclient
(
    echo =====[ Tool Versions ]=====
    where git
    git --version
    where python
    python --version
    where clang++
    clang++ --version
    where link
    where gn
    where ninja
    where fetch
    where gclient
) >> "%BUILD_LOG%" 2>&1
echo. >> "%BUILD_LOG%"

REM 配置 Git
git config --global user.name "V8 Disassembler Builder"
git config --global user.email "v8dasm.builder@localhost"
git config --global core.autocrlf false
git config --global core.filemode false

cd /d %HOMEDRIVE%%HOMEPATH%
echo 当前目录: %CD%
echo 当前目录: %CD% >> "%BUILD_LOG%"

REM 获取 Depot Tools
if not exist depot_tools (
    echo =====[ Getting Depot Tools ]=====
    powershell -command "Invoke-WebRequest https://storage.googleapis.com/chrome-infra/depot_tools.zip -O depot_tools.zip"
    if errorlevel 1 (
        echo ERROR: Failed to download depot_tools.
        exit /b 1
    )
    powershell -command "Expand-Archive depot_tools.zip -DestinationPath depot_tools"
    if errorlevel 1 (
        echo ERROR: Failed to extract depot_tools.
        exit /b 1
    )
    del depot_tools.zip
)

set PATH=%CD%\depot_tools;%PATH%
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
echo DEPOT_TOOLS_WIN_TOOLCHAIN=%DEPOT_TOOLS_WIN_TOOLCHAIN%
echo PATH after depot_tools: %PATH% >> "%BUILD_LOG%"

echo =====[ Verify depot_tools commands ]=====
where gclient
where fetch
where gn
where ninja
where clang++

REM 创建工作目录
if not exist v8 mkdir v8
cd v8
echo V8 root parent: %CD%

REM 获取 V8 源码
if not exist v8 (
    echo =====[ Fetching V8 ]=====
    call fetch v8 > "%FETCH_LOG%" 2>&1
    if errorlevel 1 (
        echo ERROR: fetch v8 failed. Dumping %FETCH_LOG%
        type "%FETCH_LOG%"
        exit /b 1
    )
    if not exist .gclient (
        echo ERROR: fetch v8 succeeded but .gclient was not created.
        type "%FETCH_LOG%"
        exit /b 1
    )
    echo target_os = ['win'] >> .gclient
) else (
    echo =====[ Reusing existing V8 checkout ]=====
    dir
)

if exist .gclient (
    echo =====[ .gclient ]=====
    type .gclient
) else (
    echo WARNING: .gclient not found in %CD%
)

cd v8
set V8_DIR=%CD%
echo V8_DIR=%V8_DIR%
echo V8_DIR=%V8_DIR% >> "%BUILD_LOG%"

echo =====[ V8 Repo Status Before Checkout ]=====
git status --short
git rev-parse --is-inside-work-tree

REM Checkout 指定版本
echo =====[ Checking out V8 %V8_VERSION% ]=====
call git fetch --all --tags
if errorlevel 1 (
    echo ERROR: git fetch --all --tags failed.
    exit /b 1
)
call git checkout %V8_VERSION%
if errorlevel 1 (
    echo ERROR: git checkout %V8_VERSION% failed.
    exit /b 1
)

echo =====[ Running gclient sync ]=====
call gclient sync > "%SYNC_LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: gclient sync failed. Dumping %SYNC_LOG%
    type "%SYNC_LOG%"
    exit /b 1
)
echo gclient sync completed successfully.

echo =====[ V8 Repo Status After Sync ]=====
git status --short
git rev-parse HEAD

REM 应用补丁（内联多级回退，避免外部脚本在 CI 中异常退出）
echo =====[ Applying v8.patch ]=====
set PATCH_FILE=%WORKSPACE_DIR%\Disassembler\v8.patch

if not exist "%PATCH_FILE%" (
    echo ERROR: Patch file not found: %PATCH_FILE%
    exit /b 1
)

echo =====[ V8 Patch Application - Inline Fallback ]===== > "%PATCH_LOG%"
echo Patch 文件: %PATCH_FILE% >> "%PATCH_LOG%"
echo V8 目录: %V8_DIR% >> "%PATCH_LOG%"
echo 日志文件: %PATCH_LOG% >> "%PATCH_LOG%"
echo 时间戳: %DATE% %TIME% >> "%PATCH_LOG%"

cd /d "%V8_DIR%"
git reset --hard HEAD >> "%PATCH_LOG%" 2>&1
git clean -fd >> "%PATCH_LOG%" 2>&1

git apply --check --reverse "%PATCH_FILE%" >> "%PATCH_LOG%" 2>&1
if not errorlevel 1 (
    echo Patch already applied, skip.
    echo Patch already applied, skip. >> "%PATCH_LOG%"
    goto :patch_done
)

git apply --check "%PATCH_FILE%" >> "%PATCH_LOG%" 2>&1
if not errorlevel 1 (
    git apply --verbose "%PATCH_FILE%" >> "%PATCH_LOG%" 2>&1
    if not errorlevel 1 goto :patch_done
)

git apply -3 --verbose "%PATCH_FILE%" >> "%PATCH_LOG%" 2>&1
if not errorlevel 1 goto :patch_done

git apply --ignore-whitespace --verbose "%PATCH_FILE%" >> "%PATCH_LOG%" 2>&1
if not errorlevel 1 goto :patch_done

python "%WORKSPACE_DIR%\scripts\v8dasm-builders\patch-utils\semantic-patches.py" "%V8_DIR%" "%PATCH_LOG%" >> "%PATCH_LOG%" 2>&1
if not errorlevel 1 goto :patch_done

echo ❌ Patch application failed. Build aborted.
echo 请检查日志文件: %PATCH_LOG%
type "%PATCH_LOG%"
exit /b 1

:patch_done
echo =====[ Patch Step Completed ]=====
echo =====[ Patch Log ]=====
type "%PATCH_LOG%"

REM 配置构建
echo =====[ Configuring V8 Build ]=====
set GN_ARGS=target_os=\"win\" target_cpu=\"x64\" is_component_build=false is_debug=false use_custom_libcxx=false v8_monolithic=true v8_static_library=true v8_enable_disassembler=true v8_enable_object_print=true v8_use_external_startup_data=false dcheck_always_on=false symbol_level=0 is_clang=true

REM 如果有额外的构建参数，追加
if not "%BUILD_ARGS%"=="" (
    set GN_ARGS=%GN_ARGS% %BUILD_ARGS%
)

echo GN Args: %GN_ARGS%
echo GN Args: %GN_ARGS% >> "%BUILD_LOG%"

REM 直接使用 gn gen 生成构建配置
call gn gen out.gn\x64.release --args="%GN_ARGS%" > "%GN_LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: gn gen failed. Dumping %GN_LOG%
    type "%GN_LOG%"
    exit /b 1
)
echo gn gen completed successfully.
type "%GN_LOG%"

REM 构建 V8 静态库
echo =====[ Building V8 Monolith ]=====
call ninja -C out.gn\x64.release v8_monolith > "%NINJA_LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: ninja build failed. Dumping %NINJA_LOG%
    type "%NINJA_LOG%"
    exit /b 1
)
echo ninja completed successfully.
type "%NINJA_LOG%"

REM 编译 v8dasm
echo =====[ Compiling v8dasm ]=====
set DASM_SOURCE=%WORKSPACE_DIR%\Disassembler\v8dasm.cpp
set OUTPUT_NAME=v8dasm-%V8_VERSION%.exe

if not exist "%DASM_SOURCE%" (
    echo ERROR: Source file not found: %DASM_SOURCE%
    exit /b 1
)

if not "%GITHUB_WORKSPACE%"=="" (
    if not exist "%GITHUB_WORKSPACE%\artifacts" mkdir "%GITHUB_WORKSPACE%\artifacts"
    set OUTPUT_PATH=%GITHUB_WORKSPACE%\artifacts\%OUTPUT_NAME%
) else (
    set OUTPUT_PATH=%CD%\%OUTPUT_NAME%
)

echo DASM_SOURCE=%DASM_SOURCE%
echo OUTPUT_PATH=%OUTPUT_PATH%
dir include
dir out.gn\x64.release\obj

clang++ "%DASM_SOURCE%" ^
    -std=c++20 ^
    -O2 ^
    -Iinclude ^
    -Lout.gn\x64.release\obj ^
    -lv8_libbase ^
    -lv8_libplatform ^
    -lv8_monolith ^
    -o "%OUTPUT_PATH%" > "%CLANG_LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: clang++ link failed. Dumping %CLANG_LOG%
    type "%CLANG_LOG%"
    exit /b 1
)
echo clang++ completed successfully.
type "%CLANG_LOG%"

REM 验证编译
if exist "%OUTPUT_PATH%" (
    echo =====[ Build Successful ]=====
    dir "%OUTPUT_PATH%"
    echo.
    echo ✅ 编译完成: %OUTPUT_NAME%
    echo    位置: %OUTPUT_PATH%
) else (
    echo ERROR: %OUTPUT_PATH% not found!
    echo =====[ Artifact Directory Listing ]=====
    dir "%WORKSPACE_DIR%\artifacts"
    exit /b 1
)
