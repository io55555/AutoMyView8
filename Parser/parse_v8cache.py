import subprocess
import os
from Parser.sfi_file_parser import parse_file


def get_version(view8_dir, file_name):
    binary_path = os.path.join(view8_dir, 'Bin', 'VersionDetector.exe')
    print(f"[parse_v8cache] Detecting version input={os.path.abspath(file_name)} detector={binary_path}")

    if not os.path.isfile(binary_path):
        raise FileNotFoundError(f"The binary '{binary_path}' does not exist.")

    try:
        result = subprocess.run([binary_path, '-f', file_name], capture_output=True, text=True, check=True)
        version = result.stdout.strip()
        stderr_text = result.stderr.strip()
        print(f"[parse_v8cache] Version detector exit_code={result.returncode}")
        if stderr_text:
            print(f"[parse_v8cache] Version detector stderr={stderr_text}")
        print(f"[parse_v8cache] Detected version={version}")
        return version
    except subprocess.CalledProcessError as e:
        stderr_text = (e.stderr or '').strip()
        stdout_text = (e.stdout or '').strip()
        raise RuntimeError(
            f"Failed to detect version for file {file_name}. exit_code={e.returncode} stdout={stdout_text} stderr={stderr_text}"
        )


def run_disassembler_binary(binary_path, file_name, out_file_name):
    if not os.path.isfile(binary_path):
        raise FileNotFoundError(
            f"The binary '{binary_path}' does not exist. "
            "You can specify a path to a similar disassembler version using the --path (-p) argument."
        )

    print(
        f"[parse_v8cache] Running disassembler binary={os.path.abspath(binary_path)} "
        f"input={os.path.abspath(file_name)} output={os.path.abspath(out_file_name)}"
    )
    with open(out_file_name, 'w') as outfile:
        result = subprocess.run([binary_path, file_name], stdout=outfile, stderr=subprocess.PIPE, text=True)

    stderr_text = (result.stderr or '').strip()
    print(f"[parse_v8cache] Disassembler exit_code={result.returncode}")
    if stderr_text:
        print(f"[parse_v8cache] Disassembler stderr={stderr_text}")

    if result.returncode != 0:
        raise RuntimeError(
            f"Binary execution failed with status code {result.returncode}: {stderr_text}"
        )


def parse_v8cache_file(file_name, out_name, view8_dir, binary_path):
    if not binary_path:
        version = get_version(view8_dir, file_name)
        binary_name = f"{version}.exe"
        binary_path = os.path.join(view8_dir, 'Bin', binary_name)
    else:
        print(f"[parse_v8cache] Using caller-provided binary={os.path.abspath(binary_path)}")

    print(f"[parse_v8cache] Executing disassembler binary={os.path.abspath(binary_path)}")
    run_disassembler_binary(binary_path, file_name, out_name)
    print(f"[parse_v8cache] Disassembly completed output={os.path.abspath(out_name)}")


def parse_disassembled_file(out_name):
    print(f"[parse_v8cache] Parsing disassembled file={os.path.abspath(out_name)}")
    all_func = parse_file(out_name)
    print(f"[parse_v8cache] Parsing completed successfully")
    return all_func
