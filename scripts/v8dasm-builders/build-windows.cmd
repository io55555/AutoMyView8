@echo off
setlocal enabledelayedexpansion

set V8_VERSION=%1
set BUILD_ARGS=%2

echo ==========================================
echo Building v8dasm for Windows x64
echo V8 Version: %V8_VERSION%
echo Build Args: %BUILD_ARGS%
echo ==========================================

REM 检测运行环境 (GitHub Actions 或本地)
if "%GITHUB_WORKSPACE%"=="" (
    echo 检测到本地环境
    set WORKSPACE_DIR=%~dp0..\..
    set IS_LOCAL=true
    echo 本地环境，跳过依赖安装 (请确保已安装: git, python, Visual Studio/clang^)
) else (
    echo 检测到 GitHub Actions 环境
    set WORKSPACE_DIR=%GITHUB_WORKSPACE%
    set IS_LOCAL=false
)

echo 工作空间: %WORKSPACE_DIR%

REM 配置 Git
git config --global user.name "V8 Disassembler Builder"
git config --global user.email "v8dasm.builder@localhost"
git config --global core.autocrlf false
git config --global core.filemode false

cd /d %HOMEDRIVE%%HOMEPATH%

REM 获取 Depot Tools
if not exist depot_tools (
    echo =====[ Getting Depot Tools ]=====
    powershell -command "Invoke-WebRequest https://storage.googleapis.com/chrome-infra/depot_tools.zip -O depot_tools.zip"
    powershell -command "Expand-Archive depot_tools.zip -DestinationPath depot_tools"
    del depot_tools.zip
)

set PATH=%CD%\depot_tools;%PATH%
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
call gclient

REM 创建工作目录
if not exist v8 mkdir v8
cd v8

REM 获取 V8 源码
if not exist v8 (
    echo =====[ Fetching V8 ]=====
    call fetch v8
    echo target_os = ['win'] >> .gclient
)

cd v8
set V8_DIR=%CD%

REM Checkout 指定版本
echo =====[ Checking out V8 %V8_VERSION% ]=====
call git fetch --all --tags
call git checkout %V8_VERSION%
call gclient sync

REM 应用补丁（内联多级回退，避免外部脚本在 CI 中异常退出）
echo =====[ Applying v8.patch ]=====
set PATCH_FILE=%WORKSPACE_DIR%\Disassembler\v8.patch
set PATCH_LOG=%WORKSPACE_DIR%\scripts\v8dasm-builders\patch-utils\patch-state.log

echo =====[ V8 Patch Application - Inline Fallback ]===== > "%PATCH_LOG%"
echo Patch 文件: %PATCH_FILE% >> "%PATCH_LOG%"
echo V8 目录: %V8_DIR% >> "%PATCH_LOG%"
echo 日志文件: %PATCH_LOG% >> "%PATCH_LOG%"

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
exit /b 1

:patch_done
echo ✅ Patch applied successfully


REM 配置构建
echo =====[ Configuring V8 Build ]=====
REM 构建 GN 参数字符串
set GN_ARGS=target_os=\"win\" target_cpu=\"x64\" is_component_build=false is_debug=false use_custom_libcxx=false v8_monolithic=true v8_static_library=true v8_enable_disassembler=true v8_enable_object_print=true v8_use_external_startup_data=false dcheck_always_on=false symbol_level=0 is_clang=true

REM 如果有额外的构建参数，追加
if not "%BUILD_ARGS%"=="" (
    set GN_ARGS=%GN_ARGS% %BUILD_ARGS%
)

echo GN Args: %GN_ARGS%

REM 直接使用 gn gen 生成构建配置
call gn gen out.gn\x64.release --args="%GN_ARGS%"

REM 构建 V8 静态库
echo =====[ Building V8 Monolith ]=====
call ninja -C out.gn\x64.release v8_monolith

REM 编译 v8dasm
echo =====[ Compiling v8dasm ]=====
set DASM_SOURCE=%WORKSPACE_DIR%\Disassembler\v8dasm.cpp
set OUTPUT_NAME=v8dasm-%V8_VERSION%.exe

clang++ %DASM_SOURCE% ^
    -std=c++20 ^
    -O2 ^
    -Iinclude ^
    -Lout.gn\x64.release\obj ^
    -lv8_libbase ^
    -lv8_libplatform ^
    -lv8_monolith ^
    -o %OUTPUT_NAME%

REM 验证编译
if exist %OUTPUT_NAME% (
    echo =====[ Build Successful ]=====
    dir %OUTPUT_NAME%
    echo.
    echo ✅ 编译完成: %OUTPUT_NAME%
    echo    位置: %CD%\%OUTPUT_NAME%

    if not "%GITHUB_WORKSPACE%"=="" (
        if not exist "%GITHUB_WORKSPACE%\artifacts" mkdir "%GITHUB_WORKSPACE%\artifacts"
        copy /Y "%CD%\%OUTPUT_NAME%" "%GITHUB_WORKSPACE%\artifacts\%OUTPUT_NAME%" >nul
        if not exist "%GITHUB_WORKSPACE%\artifacts\%OUTPUT_NAME%" (
            echo ERROR: failed to stage artifact to %GITHUB_WORKSPACE%\artifacts\%OUTPUT_NAME%
            exit /b 1
        )
        echo ✅ 已暂存产物: %GITHUB_WORKSPACE%\artifacts\%OUTPUT_NAME%
    )
) else (
    echo ERROR: %OUTPUT_NAME% not found!
    exit /b 1
)
