@echo off
REM apply-patch.cmd - multi-level V8 patch application helper (Windows)
REM
REM Usage: apply-patch.cmd <patch_file> <v8_dir> <log_file> [abort_on_failure]

setlocal enabledelayedexpansion

set PATCH_FILE=%~1
set V8_DIR=%~2
set LOG_FILE=%~3
set ABORT_ON_FAILURE=%~4
set PATCH_STATUS=failed
set PYTHON_CMD=
set SCRIPT_DIR=%~dp0
set SEMANTIC_SCRIPT=%SCRIPT_DIR%semantic-patches.py
if "%ABORT_ON_FAILURE%"=="" set ABORT_ON_FAILURE=true

if "%PATCH_FILE%"=="" (
    echo ERROR: Missing patch_file argument
    exit /b 1
)

if "%V8_DIR%"=="" (
    echo ERROR: Missing v8_dir argument
    exit /b 1
)

if "%LOG_FILE%"=="" (
    echo ERROR: Missing log_file argument
    exit /b 1
)

if not exist "%PATCH_FILE%" (
    echo ERROR: Patch file not found: %PATCH_FILE%
    exit /b 1
)

if not exist "%V8_DIR%" (
    echo ERROR: V8 directory not found: %V8_DIR%
    exit /b 1
)

for %%F in ("%LOG_FILE%") do set LOG_DIR=%%~dpF
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

> "%LOG_FILE%" echo =====[ V8 Patch Application - Multi-level Fallback ]=====
>> "%LOG_FILE%" echo Patch file: %PATCH_FILE%
>> "%LOG_FILE%" echo V8 dir: %V8_DIR%
>> "%LOG_FILE%" echo Log file: %LOG_FILE%
>> "%LOG_FILE%" echo Abort on failure: %ABORT_ON_FAILURE%
>> "%LOG_FILE%" echo Timestamp: %date% %time%
>> "%LOG_FILE%" echo.

call :log_line "===== [PATCH_HELPER] START ====="
call :log_line "Patch file: %PATCH_FILE%"
call :log_line "V8 dir: %V8_DIR%"
call :log_line "Semantic script: %SEMANTIC_SCRIPT%"
call :do_reset

call :log_line "[CHECK] Testing whether patch is already applied"
cd /d "%V8_DIR%"
git.exe rev-parse HEAD >> "%LOG_FILE%" 2>&1

git.exe apply --check --reverse "%PATCH_FILE%" >nul 2>&1
if not errorlevel 1 (
    set PATCH_STATUS=already_applied
    call :log_line "[CHECK] Patch is already applied"
    call :log_status
    exit /b 0
)

call :log_line "[CHECK] Patch is not applied yet"
call :log_line "[LEVEL 1] Trying git apply"
git.exe apply --check "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
if not errorlevel 1 (
    call :log_line "[LEVEL 1] git apply --check passed"
    git.exe apply --verbose "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
    if not errorlevel 1 (
        set PATCH_STATUS=applied_git
        call :verify_patch_state
        if errorlevel 1 goto :verification_failed
        call :log_line "[LEVEL 1] Patch applied successfully"
        call :log_status
        exit /b 0
    )
)
call :log_line "[LEVEL 1] git apply failed"
call :log_git_apply_failures
call :do_reset

call :log_line "[LEVEL 2] Trying git apply -3"
git.exe apply -3 --verbose "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
if not errorlevel 1 (
    git.exe diff --check 2>&1 | findstr /C:"conflict" >nul
    if errorlevel 1 (
        set PATCH_STATUS=applied_3way
        call :verify_patch_state
        if errorlevel 1 goto :verification_failed
        call :log_line "[LEVEL 2] Three-way patch apply succeeded"
        call :log_status
        exit /b 0
    ) else (
        call :log_line "[LEVEL 2] Three-way merge introduced conflicts"
    )
)
call :log_line "[LEVEL 2] git apply -3 failed"
call :log_git_apply_failures
call :do_reset

call :log_line "[LEVEL 3] Trying git apply --ignore-whitespace"
git.exe apply --ignore-whitespace --verbose "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
if not errorlevel 1 (
    set PATCH_STATUS=applied_ignore_whitespace
    call :verify_patch_state
    if errorlevel 1 goto :verification_failed
    call :log_line "[LEVEL 3] Patch applied with --ignore-whitespace"
    call :log_status
    exit /b 0
)
call :log_line "[LEVEL 3] git apply --ignore-whitespace failed"
call :log_git_apply_failures
call :do_reset

call :log_line "[LEVEL 4] Trying semantic fallback"
if not exist "%SEMANTIC_SCRIPT%" (
    call :log_line "[LEVEL 4] Semantic script is missing"
    goto :all_failed
)

where python3 >nul 2>&1
if errorlevel 1 (
    where python >nul 2>&1
    if errorlevel 1 (
        call :log_line "[LEVEL 4] Python executable was not found"
        goto :all_failed
    )
    set PYTHON_CMD=python
) else (
    set PYTHON_CMD=python3
)

call :log_line "[LEVEL 4] Python command: %PYTHON_CMD%"
call :append_command_output "%LOG_FILE%" "git.exe rev-parse HEAD"
call :append_command_output "%LOG_FILE%" "where %PYTHON_CMD%"
call :log_line "[LEVEL 4] Semantic script writes directly to the patch log"
call %PYTHON_CMD% "%SEMANTIC_SCRIPT%" "%V8_DIR%" "%LOG_FILE%"
if not errorlevel 1 (
    set PATCH_STATUS=applied_semantic
    call :verify_patch_state
    if errorlevel 1 goto :verification_failed
    call :log_line "[LEVEL 4] Semantic fallback succeeded"
    call :log_status
    exit /b 0
)

call :log_line "[LEVEL 4] Semantic fallback failed"
set PATCH_STATUS=failed_semantic
call :log_status
goto :all_failed

:verification_failed
call :log_line "[VERIFY] Patch state verification failed"
set PATCH_STATUS=failed_verification
call :log_status

:all_failed
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo ========================================
>> "%LOG_FILE%" echo FAILURE: all patch application methods failed
>> "%LOG_FILE%" echo ========================================
call :log_line "========================================"
call :log_line "FAILURE: all patch application methods failed"
call :log_line "========================================"
call :log_status
if /i "%ABORT_ON_FAILURE%"=="true" (
    call :log_line "Build is stopping because patch application failed"
    call :log_line "Review patch log: %LOG_FILE%"
    exit /b 1
) else (
    call :log_line "Continuing without patch application"
    exit /b 0
)

:do_reset
call :log_line "[RESET] Resetting V8 checkout to a clean state"
pushd "%V8_DIR%" >nul 2>&1 || (
    call :log_line "[RESET] Could not enter V8 dir"
    exit /b 0
)

git.exe rev-parse --is-inside-work-tree >nul 2>&1 || (
    call :log_line "[RESET] Directory is not a git worktree; skipping reset"
    popd
    exit /b 0
)

git.exe reset --hard HEAD >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log_line "[RESET] git reset --hard failed; continuing"
    popd
    exit /b 0
)

git.exe clean -fd >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log_line "[RESET] git clean -fd failed; continuing"
    popd
    exit /b 0
)

call :log_line "[RESET] Checkout is clean"
popd
exit /b 0

:verify_patch_state
git.exe apply --check --reverse "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
if not errorlevel 1 (
    call :log_line "[VERIFY] Reverse patch check passed"
    exit /b 0
)

call :log_line "[VERIFY] Reverse patch check failed; trying semantic verification"
if "%PYTHON_CMD%"=="" (
    where python3 >nul 2>&1
    if errorlevel 1 (
        where python >nul 2>&1
        if errorlevel 1 exit /b 1
        set PYTHON_CMD=python
    ) else (
        set PYTHON_CMD=python3
    )
)
call %PYTHON_CMD% "%SEMANTIC_SCRIPT%" --verify "%V8_DIR%" "%LOG_FILE%"
if errorlevel 1 exit /b 1
call :log_line "[VERIFY] Semantic verification passed"
exit /b 0

:log_git_apply_failures
>> "%LOG_FILE%" echo -----[ git apply failure summary ]-----
git.exe apply --check --verbose "%PATCH_FILE%" >> "%LOG_FILE%" 2>&1
>> "%LOG_FILE%" echo --------------------------------------
exit /b 0

:append_command_output
>> "%~1" echo =====[ CMD:%~2 ]=====
cmd /d /c "%~2" >> "%~1" 2>&1
>> "%~1" echo.
exit /b 0

:log_status
call :log_line "PATCH_STATUS=%PATCH_STATUS%"
exit /b 0

:log_line
echo %~1
>> "%LOG_FILE%" echo %~1
exit /b 0
