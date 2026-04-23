@echo off
setlocal enabledelayedexpansion

set V8_VERSION=%~1
set BUILD_ARGS=%~2

if "%V8_VERSION%"=="" (
    echo ERROR: Missing V8 version argument.
    exit /b 1
)

if "%GITHUB_WORKSPACE%"=="" (
    set WORKSPACE_DIR=%~dp0\..\..
    set IS_LOCAL=true
) else (
    set WORKSPACE_DIR=%GITHUB_WORKSPACE%
    set IS_LOCAL=false
)

for %%I in ("%WORKSPACE_DIR%") do set WORKSPACE_DIR=%%~fI

if "%V8_BUILD_ROOT%"=="" (
    if /i "%IS_LOCAL%"=="false" (
        set BUILD_ROOT=%RUNNER_TEMP%\v8dasm-%V8_VERSION%
    ) else (
        set BUILD_ROOT=%USERPROFILE%\v8dasm-build\%V8_VERSION%
    )
) else (
    set BUILD_ROOT=%V8_BUILD_ROOT%
)

for %%I in ("%BUILD_ROOT%") do set BUILD_ROOT=%%~fI
set V8_PARENT_DIR=%BUILD_ROOT%
set V8_DIR=%V8_PARENT_DIR%\v8

if not exist "%WORKSPACE_DIR%\artifacts" mkdir "%WORKSPACE_DIR%\artifacts"
if not exist "%WORKSPACE_DIR%\artifacts\logs" mkdir "%WORKSPACE_DIR%\artifacts\logs"

set BUILD_LOG=%WORKSPACE_DIR%\artifacts\logs\build-windows-%V8_VERSION%.log
set FETCH_LOG=%WORKSPACE_DIR%\artifacts\logs\fetch-v8-%V8_VERSION%.log
set SYNC_LOG=%WORKSPACE_DIR%\artifacts\logs\gclient-sync-%V8_VERSION%.log
set GN_LOG=%WORKSPACE_DIR%\artifacts\logs\gn-gen-%V8_VERSION%.log
set NINJA_LOG=%WORKSPACE_DIR%\artifacts\logs\ninja-%V8_VERSION%.log
set CLANG_LOG=%WORKSPACE_DIR%\artifacts\logs\clang-%V8_VERSION%.log
set PATCH_LOG=%WORKSPACE_DIR%\artifacts\logs\patch-%V8_VERSION%.log
set CHECKOUT_LOG=%WORKSPACE_DIR%\artifacts\logs\checkout-%V8_VERSION%.log
set STATE_LOG=%WORKSPACE_DIR%\artifacts\logs\state-%V8_VERSION%.log
set OUT_DIR=%V8_DIR%\out.gn\x64.release
if "%V8DASM_OUTPUT_NAME%"=="" (
    set OUTPUT_NAME=v8dasm-%V8_VERSION%.exe
) else (
    set OUTPUT_NAME=%V8DASM_OUTPUT_NAME%
)
set OUTPUT_PATH=%WORKSPACE_DIR%\artifacts\%OUTPUT_NAME%
set PATCH_HELPER=%WORKSPACE_DIR%\scripts\v8dasm-builders\patch-utils\apply-patch.cmd
set PATCH_FILE=%WORKSPACE_DIR%\Disassembler\v8.patch
set DASM_SOURCE=%WORKSPACE_DIR%\Disassembler\v8dasm.cpp

for %%I in ("%WORKSPACE_DIR%\artifacts") do set ARTIFACTS_DIR=%%~fI

del /q "%BUILD_LOG%" "%FETCH_LOG%" "%SYNC_LOG%" "%GN_LOG%" "%NINJA_LOG%" "%CLANG_LOG%" "%PATCH_LOG%" "%CHECKOUT_LOG%" "%STATE_LOG%" 2>nul

call :log_header
call :stage "INIT"
call :log_line "Building v8dasm for Windows x64"
call :log_line "V8 Version: %V8_VERSION%"
call :log_line "Build Args: %BUILD_ARGS%"
call :log_line "Workspace: %WORKSPACE_DIR%"
call :log_line "Build root: %BUILD_ROOT%"
call :log_line "V8 parent dir: %V8_PARENT_DIR%"
call :log_line "V8 dir: %V8_DIR%"
call :log_line "Output path: %OUTPUT_PATH%"
call :log_line "Build log: %BUILD_LOG%"
call :log_line "Patch log: %PATCH_LOG%"
call :log_line "GN log: %GN_LOG%"
call :log_line "Ninja log: %NINJA_LOG%"
call :log_line "Clang log: %CLANG_LOG%"

set DEPOT_TOOLS_WIN_TOOLCHAIN=0
set DEPOT_TOOLS_DIR=%USERPROFILE%\depot_tools
set GIT_CACHE_PATH=%DEPOT_TOOLS_DIR%\.git_cache
if not exist "%DEPOT_TOOLS_DIR%" (
    call :log_line "depot_tools not found at %DEPOT_TOOLS_DIR%; downloading fresh copy"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest 'https://storage.googleapis.com/chrome-infra/depot_tools.zip' -OutFile '%USERPROFILE%\depot_tools.zip'"
    if errorlevel 1 call :fail "INIT" "Failed to download depot_tools.zip"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%USERPROFILE%\depot_tools.zip' -DestinationPath '%DEPOT_TOOLS_DIR%' -Force"
    if errorlevel 1 call :fail "INIT" "Failed to extract depot_tools.zip"
    del /q "%USERPROFILE%\depot_tools.zip"
    if errorlevel 1 call :fail "INIT" "Failed to remove depot_tools.zip"
    call "%DEPOT_TOOLS_DIR%\update_depot_tools.bat" >nul 2>&1
    if errorlevel 1 call :log_line "update_depot_tools.bat returned non-zero after fresh extract"
)
if not exist "%GIT_CACHE_PATH%" mkdir "%GIT_CACHE_PATH%"
if not exist "%DEPOT_TOOLS_DIR%\git.bat" (
    > "%DEPOT_TOOLS_DIR%\git.bat" echo @echo off
    >> "%DEPOT_TOOLS_DIR%\git.bat" echo git.exe %%*
)
set PATH=%DEPOT_TOOLS_DIR%;%PATH%
set DEPOT_TOOLS_UPDATE=0
call :log_line "DEPOT_TOOLS_WIN_TOOLCHAIN=%DEPOT_TOOLS_WIN_TOOLCHAIN%"
call :log_line "DEPOT_TOOLS_UPDATE=%DEPOT_TOOLS_UPDATE%"
call :log_line "GIT_CACHE_PATH=%GIT_CACHE_PATH%"
call :log_line "Prepended depot_tools to PATH: %DEPOT_TOOLS_DIR%"

call :require_tool git
call :require_tool python
call :require_tool clang++
call :require_tool gclient
call :require_tool fetch
call :require_tool gn
call :require_tool ninja

call :log_line "Initializing depot_tools Python bootstrap"
call gclient.bat >nul 2>&1
if errorlevel 1 (
    call "%DEPOT_TOOLS_DIR%\update_depot_tools.bat" >nul 2>&1
    if errorlevel 1 call :fail "INIT" "depot_tools bootstrap failed"
)

call :append_command_output "%BUILD_LOG%" "where git"
call :append_command_output "%BUILD_LOG%" "git.exe --version"
call :append_command_output "%BUILD_LOG%" "where python"
call :append_command_output "%BUILD_LOG%" "python --version"
call :append_command_output "%BUILD_LOG%" "where clang++"
call :append_command_output "%BUILD_LOG%" "clang++ --version"
call :append_command_output "%BUILD_LOG%" "where gclient"
call :append_command_output "%BUILD_LOG%" "where fetch"
call :append_command_output "%BUILD_LOG%" "where gn"
call :append_command_output "%BUILD_LOG%" "where ninja"

if not exist "%V8_PARENT_DIR%" mkdir "%V8_PARENT_DIR%"
if errorlevel 1 call :fail "INIT" "Failed to create build root %V8_PARENT_DIR%"

call :stage "PREPARE_CHECKOUT"
if exist "%V8_PARENT_DIR%\.gclient" (
    call :log_line "Existing .gclient found in build root"
) else (
    call :log_line "No .gclient found in build root yet"
)
call :append_command_output "%STATE_LOG%" "dir /a %V8_PARENT_DIR%"
if exist "%V8_PARENT_DIR%\.gclient" if not exist "%V8_DIR%" (
    call :log_line "Build root contains .gclient without v8 checkout; deleting isolated build root"
    rmdir /s /q "%V8_PARENT_DIR%"
    if errorlevel 1 call :fail "PREPARE_CHECKOUT" "Failed to remove incomplete build root %V8_PARENT_DIR%"
    mkdir "%V8_PARENT_DIR%"
    if errorlevel 1 call :fail "PREPARE_CHECKOUT" "Failed to recreate build root %V8_PARENT_DIR%"
)

if exist "%V8_DIR%" (
    call :log_line "Existing V8 checkout detected"
    call :append_command_output "%STATE_LOG%" "dir /a %V8_PARENT_DIR%"
    call :checkout_is_healthy "%V8_DIR%"
    if errorlevel 1 (
        call :log_line "Existing V8 checkout is corrupt; deleting isolated build root"
        rmdir /s /q "%V8_PARENT_DIR%"
        if errorlevel 1 call :fail "PREPARE_CHECKOUT" "Failed to remove corrupt build root %V8_PARENT_DIR%"
        mkdir "%V8_PARENT_DIR%"
        if errorlevel 1 call :fail "PREPARE_CHECKOUT" "Failed to recreate build root %V8_PARENT_DIR%"
    )
)

pushd "%V8_PARENT_DIR%" >nul 2>&1 || call :fail "PREPARE_CHECKOUT" "Failed to enter %V8_PARENT_DIR%"

if not exist "%V8_DIR%" (
    call :stage "FETCH"
    call :log_line "Fetching V8 into %V8_PARENT_DIR%"
    call fetch.bat v8 > "%FETCH_LOG%" 2>&1
    if errorlevel 1 (
        popd
        call :fail_with_log "FETCH" "%FETCH_LOG%" "fetch v8 failed"
    )
    if not exist "%V8_PARENT_DIR%\.gclient" (
        popd
        call :fail_with_log "FETCH" "%FETCH_LOG%" "fetch v8 succeeded but .gclient was not created"
    )
) else (
    call :log_line "Reusing isolated V8 checkout"
)

if not exist "%V8_PARENT_DIR%\.gclient" (
    popd
    call :fail "PREPARE_CHECKOUT" ".gclient missing under %V8_PARENT_DIR%"
)

findstr /c:"target_os = ['win']" "%V8_PARENT_DIR%\.gclient" >nul 2>&1
if errorlevel 1 (
    >> "%V8_PARENT_DIR%\.gclient" echo target_os = ['win']
    findstr /c:"target_os = ['win']" "%V8_PARENT_DIR%\.gclient" >nul 2>&1
    if errorlevel 1 (
        popd
        call :fail "PREPARE_CHECKOUT" "Failed to append target_os to .gclient"
    )
)

call :append_file "%BUILD_LOG%" "%V8_PARENT_DIR%\.gclient"
popd >nul

if not exist "%V8_DIR%" call :fail "FETCH" "V8 directory missing after fetch"
if not exist "%V8_DIR%\.git" call :fail "PREPARE_CHECKOUT" "%V8_DIR% is not a git repository"

call :stage "CHECKOUT"
pushd "%V8_DIR%" >nul 2>&1 || call :fail "CHECKOUT" "Failed to enter %V8_DIR%"
call :append_command_output "%STATE_LOG%" "git.exe status --short"
git.exe reset --hard HEAD >> "%CHECKOUT_LOG%" 2>&1
if errorlevel 1 (
    popd
    call :fail_with_log "CHECKOUT" "%CHECKOUT_LOG%" "git.exe reset --hard HEAD failed"
)
git.exe clean -ffd -e out.gn >> "%CHECKOUT_LOG%" 2>&1
if errorlevel 1 (
    popd
    call :fail_with_log "CHECKOUT" "%CHECKOUT_LOG%" "git.exe clean -ffd -e out.gn failed"
)
git.exe fetch --all --tags >> "%CHECKOUT_LOG%" 2>&1
if errorlevel 1 (
    popd
    call :fail_with_log "CHECKOUT" "%CHECKOUT_LOG%" "git.exe fetch --all --tags failed"
)
git.exe checkout %V8_VERSION% >> "%CHECKOUT_LOG%" 2>&1
if errorlevel 1 (
    git.exe tag --list "%V8_VERSION%" >> "%CHECKOUT_LOG%" 2>&1
    git.exe status --short >> "%CHECKOUT_LOG%" 2>&1
    popd
    call :fail_with_log "CHECKOUT" "%CHECKOUT_LOG%" "git.exe checkout %V8_VERSION% failed"
)
git.exe rev-parse HEAD >> "%CHECKOUT_LOG%" 2>&1
if errorlevel 1 (
    popd
    call :fail_with_log "CHECKOUT" "%CHECKOUT_LOG%" "git.exe rev-parse HEAD failed after checkout"
)
popd >nul

call :stage "SYNC"
pushd "%V8_DIR%" >nul 2>&1 || call :fail "SYNC" "Failed to enter %V8_DIR%"
call gclient.bat sync -D > "%SYNC_LOG%" 2>&1
if errorlevel 1 (
    popd
    call :fail_with_log "SYNC" "%SYNC_LOG%" "gclient sync -D failed"
)
if not exist "%V8_DIR%\include" (
    popd
    call :fail_with_log "SYNC" "%SYNC_LOG%" "V8 include directory missing after sync"
)
call :append_command_output "%STATE_LOG%" "git.exe status --short"
popd >nul

if not exist "%PATCH_FILE%" call :fail "PATCH" "Patch file not found: %PATCH_FILE%"
if not exist "%PATCH_HELPER%" call :fail "PATCH" "Patch helper not found: %PATCH_HELPER%"

call :stage "PATCH"
call :log_line "Patch helper: %PATCH_HELPER%"
call :log_line "Patch file: %PATCH_FILE%"
pushd "%V8_DIR%" >nul 2>&1 || call :fail "PATCH" "Failed to enter %V8_DIR% for patch summary"
for /f %%I in ('git.exe rev-parse HEAD') do set V8_HEAD=%%I
popd >nul
call :log_line "V8 HEAD before patch: %V8_HEAD%"
call "%PATCH_HELPER%" "%PATCH_FILE%" "%V8_DIR%" "%PATCH_LOG%" true
if errorlevel 1 call :fail_with_log "PATCH" "%PATCH_LOG%" "Patch helper failed"
findstr /c:"PATCH_STATUS=" "%PATCH_LOG%" >nul 2>&1
if errorlevel 1 call :fail_with_log "PATCH" "%PATCH_LOG%" "Patch helper did not emit PATCH_STATUS"
set PATCH_STATUS_VALUE=
for /f "tokens=1,* delims==" %%A in ('findstr /c:"PATCH_STATUS=" "%PATCH_LOG%"') do set PATCH_STATUS_VALUE=%%B
if "%PATCH_STATUS_VALUE%"=="" call :fail_with_log "PATCH" "%PATCH_LOG%" "Patch helper emitted PATCH_STATUS lines but none could be parsed"
call :log_line "Patch helper summary: PATCH_STATUS=%PATCH_STATUS_VALUE%"

if not exist "%DASM_SOURCE%" call :fail "CLANG" "Source file not found: %DASM_SOURCE%"

set GN_ARGS=target_os=\"win\" target_cpu=\"x64\" is_component_build=false is_debug=false use_custom_libcxx=false v8_monolithic=true v8_static_library=true v8_enable_disassembler=true v8_enable_object_print=true v8_use_external_startup_data=false dcheck_always_on=false symbol_level=0 is_clang=true
if not "%BUILD_ARGS%"=="" set GN_ARGS=%GN_ARGS% %BUILD_ARGS%
set V8DASM_DEFINES=
call :append_define_from_build_args "v8_enable_pointer_compression=true" "-DV8_COMPRESS_POINTERS"
call :append_define_from_build_args "v8_enable_sandbox=true" "-DV8_ENABLE_SANDBOX"
set CL=/D_SILENCE_CXX20_OLD_SHARED_PTR_ATOMIC_SUPPORT_DEPRECATION_WARNING %CL%
call :log_line "GN Args: %GN_ARGS%"
call :log_line "v8dasm extra defines: %V8DASM_DEFINES%"
call :log_line "CL env: %CL%"

call :stage "GN"
pushd "%V8_DIR%" >nul 2>&1 || call :fail "GN" "Failed to enter %V8_DIR%"
call gn.bat gen out.gn\x64.release --args="%GN_ARGS%" > "%GN_LOG%" 2>&1
if errorlevel 1 (
    popd
    call :fail_with_log "GN" "%GN_LOG%" "gn gen failed"
)
if not exist "%V8_DIR%\out.gn\x64.release\args.gn" (
    popd
    call :fail_with_log "GN" "%GN_LOG%" "args.gn missing after gn gen"
)
popd >nul

call :stage "NINJA"
pushd "%V8_DIR%" >nul 2>&1 || call :fail "NINJA" "Failed to enter %V8_DIR%"
call ninja.bat -C out.gn\x64.release v8_monolith > "%NINJA_LOG%" 2>&1
if errorlevel 1 (
    popd
    call :fail_with_log "NINJA" "%NINJA_LOG%" "ninja build failed"
)
if not exist "%V8_DIR%\out.gn\x64.release\obj\v8_monolith.lib" (
    if not exist "%V8_DIR%\out.gn\x64.release\obj\libv8_monolith.a" (
        popd
        call :fail_with_log "NINJA" "%NINJA_LOG%" "v8_monolith output not found after ninja"
    )
)
popd >nul

call :stage "CLANG"
pushd "%V8_DIR%" >nul 2>&1 || call :fail "CLANG" "Failed to enter %V8_DIR%"
clang++ "%DASM_SOURCE%" ^
    -std=c++20 ^
    -O2 ^
    %V8DASM_DEFINES% ^
    -Iinclude ^
    -Lout.gn\x64.release\obj ^
    -lv8_monolith ^
    -ladvapi32 ^
    -ldbghelp ^
    -lwinmm ^
    -o "%OUTPUT_PATH%" > "%CLANG_LOG%" 2>&1
if errorlevel 1 (
    popd
    call :fail_with_log "CLANG" "%CLANG_LOG%" "clang++ link failed"
)
popd >nul

call :stage "VERIFY_ARTIFACT"
if not exist "%OUTPUT_PATH%" (
    call :append_command_output "%STATE_LOG%" "dir /a %ARTIFACTS_DIR%"
    call :fail_with_log "VERIFY_ARTIFACT" "%CLANG_LOG%" "Expected artifact not found: %OUTPUT_PATH%"
)
call :append_command_output "%STATE_LOG%" "dir /a %ARTIFACTS_DIR%"
call :log_line "Build successful: %OUTPUT_PATH%"
call :log_line "STATE_LOG: %STATE_LOG%"
exit /b 0

:log_header
> "%BUILD_LOG%" echo =====[ Environment Summary ]=====
>> "%BUILD_LOG%" echo Workspace: %WORKSPACE_DIR%
>> "%BUILD_LOG%" echo Build root: %BUILD_ROOT%
>> "%BUILD_LOG%" echo V8 dir: %V8_DIR%
>> "%BUILD_LOG%" echo Artifacts dir: %ARTIFACTS_DIR%
>> "%BUILD_LOG%" echo Home: %HOMEDRIVE%%HOMEPATH%
>> "%BUILD_LOG%" echo Runner temp: %RUNNER_TEMP%
>> "%BUILD_LOG%" echo GITHUB_WORKSPACE: %GITHUB_WORKSPACE%
>> "%BUILD_LOG%" echo BUILD_LOG: %BUILD_LOG%
>> "%BUILD_LOG%" echo FETCH_LOG: %FETCH_LOG%
>> "%BUILD_LOG%" echo CHECKOUT_LOG: %CHECKOUT_LOG%
>> "%BUILD_LOG%" echo SYNC_LOG: %SYNC_LOG%
>> "%BUILD_LOG%" echo PATCH_LOG: %PATCH_LOG%
>> "%BUILD_LOG%" echo GN_LOG: %GN_LOG%
>> "%BUILD_LOG%" echo NINJA_LOG: %NINJA_LOG%
>> "%BUILD_LOG%" echo CLANG_LOG: %CLANG_LOG%
>> "%BUILD_LOG%" echo STATE_LOG: %STATE_LOG%
>> "%BUILD_LOG%" echo.
exit /b 0

:stage
set STAGE_NAME=%~1
call :log_line "===== [STAGE:%STAGE_NAME%] ====="
exit /b 0

:log_line
echo %~1
>> "%BUILD_LOG%" echo %~1
exit /b 0

:append_file
if exist "%~2" (
    >> "%~1" echo =====[ FILE:%~2 ]=====
    type "%~2" >> "%~1"
    >> "%~1" echo.
)
exit /b 0

:append_command_output
set COMMAND_TEXT=%~2
>> "%~1" echo =====[ CMD:!COMMAND_TEXT! ]=====
cmd /d /c !COMMAND_TEXT! >> "%~1" 2>&1
>> "%~1" echo.
exit /b 0

:require_tool
where %~1 >nul 2>&1
if errorlevel 1 (
    call :log_line "ERROR[INIT]: Required tool not found: %~1"
    call :append_command_output "%BUILD_LOG%" "dir /a %ARTIFACTS_DIR%"
    exit 1
)
exit /b 0

:append_define_from_build_args
set ARG_NEEDLE=%~1
set ARG_DEFINE=%~2
if not "!BUILD_ARGS:%ARG_NEEDLE%=!"=="%BUILD_ARGS%" (
    set V8DASM_DEFINES=!V8DASM_DEFINES! %ARG_DEFINE%
)
exit /b 0

:checkout_is_healthy
if not exist "%~1\.git" exit /b 1
if exist "%~1\.git\objects\info\alternates" (
    set ALT_OBJECTS_PATH=
    set /p ALT_OBJECTS_PATH=<"%~1\.git\objects\info\alternates"
    if "!ALT_OBJECTS_PATH!"=="" exit /b 1
    if not exist "!ALT_OBJECTS_PATH!" exit /b 1
)
git.exe -C "%~1" rev-parse HEAD >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:fail_with_log
call :log_line "ERROR[%~1]: %~3"
call :log_line "See log: %~2"
if exist "%~2" type "%~2"
call :append_command_output "%BUILD_LOG%" "dir /a %ARTIFACTS_DIR%"
exit 1

:fail
call :log_line "ERROR[%~1]: %~2"
call :append_command_output "%BUILD_LOG%" "dir /a %ARTIFACTS_DIR%"
exit 1
