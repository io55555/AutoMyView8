import json
import subprocess
import os
from Parser.sfi_file_parser import parse_file


def load_version_configs(view8_dir):
    config_path = os.path.join(view8_dir, 'configs', 'v8-versions.json')
    if not os.path.isfile(config_path):
        return []
    with open(config_path, 'r', encoding='utf-8') as infile:
        return json.load(infile).get('versions', [])


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
        print(
            f"[parse_v8cache] Version detector failed exit_code={e.returncode} stdout={stdout_text} stderr={stderr_text}"
        )
        return None


def build_candidate_binaries(view8_dir, detected_version=None, override_binary=None):
    candidates = []
    seen = set()

    def add_candidate(binary_path, reason):
        normalized = os.path.abspath(binary_path)
        if normalized in seen or not os.path.isfile(normalized):
            return
        seen.add(normalized)
        candidates.append((normalized, reason))

    if override_binary:
        add_candidate(override_binary, 'caller override')

    version_configs = load_version_configs(view8_dir)
    candidate_dirs = [
        os.path.join(view8_dir, 'Bin'),
        view8_dir,
    ]

    if detected_version:
        for candidate_dir in candidate_dirs:
            detected_default = os.path.join(candidate_dir, f'{detected_version}.exe')
            add_candidate(detected_default, f'detected version {detected_version}')
        for config in version_configs:
            if config.get('v8_version') == detected_version:
                for candidate_dir in candidate_dirs:
                    add_candidate(
                        os.path.join(candidate_dir, config.get('binary_name', f'{detected_version}.exe')),
                        f'configured match for {detected_version}',
                    )

    for config in version_configs:
        if 'Electron' in config.get('node_version', ''):
            for candidate_dir in candidate_dirs:
                add_candidate(
                    os.path.join(candidate_dir, config.get('binary_name', f"{config['v8_version']}.exe")),
                    f"electron candidate {config['v8_version']}",
                )

    for config in version_configs:
        if 'Electron' not in config.get('node_version', ''):
            for candidate_dir in candidate_dirs:
                add_candidate(
                    os.path.join(candidate_dir, config.get('binary_name', f"{config['v8_version']}.exe")),
                    f"node candidate {config['v8_version']}",
                )

    return candidates


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
    with open(out_file_name, 'w', encoding='utf-8') as outfile:
        result = subprocess.run([binary_path, file_name], stdout=outfile, stderr=subprocess.PIPE, text=True)

    stderr_text = (result.stderr or '').strip()
    print(f"[parse_v8cache] Disassembler exit_code={result.returncode}")
    if stderr_text:
        print(f"[parse_v8cache] Disassembler stderr={stderr_text}")

    return result.returncode, stderr_text


def output_looks_parseable(out_file_name):
    if not os.path.isfile(out_file_name):
        return False, 'output file missing'
    file_size = os.path.getsize(out_file_name)
    if file_size == 0:
        return False, 'output file empty'
    with open(out_file_name, 'r', encoding='utf-8', errors='replace') as infile:
        content = infile.read()
    if 'Start SharedFunctionInfo' not in content:
        return False, 'missing Start SharedFunctionInfo marker'
    return True, ''


def parse_v8cache_file(file_name, out_name, view8_dir, binary_path):
    detected_version = None
    if binary_path:
        print(f"[parse_v8cache] Using caller-provided binary={os.path.abspath(binary_path)}")
    else:
        detected_version = get_version(view8_dir, file_name)

    candidates = build_candidate_binaries(view8_dir, detected_version=detected_version, override_binary=binary_path)
    if not candidates:
        raise FileNotFoundError(
            'No disassembler candidates were found. Build candidate binaries under Bin/ or pass --path.'
        )

    failures = []
    for candidate_path, reason in candidates:
        print(
            f"[parse_v8cache] Trying candidate binary={candidate_path} reason={reason}"
        )
        exit_code, stderr_text = run_disassembler_binary(candidate_path, file_name, out_name)
        if exit_code != 0:
            failure_reason = stderr_text or f'exit_code={exit_code}'
            failures.append(f'{os.path.basename(candidate_path)} -> {failure_reason}')
            continue

        looks_parseable, parse_reason = output_looks_parseable(out_name)
        if looks_parseable:
            print(f"[parse_v8cache] Candidate accepted binary={candidate_path}")
            print(f"[parse_v8cache] Disassembly completed output={os.path.abspath(out_name)}")
            return

        failure_reason = parse_reason
        if stderr_text:
            failure_reason = f'{failure_reason}; stderr={stderr_text}'
        failures.append(f'{os.path.basename(candidate_path)} -> {failure_reason}')
        print(f"[parse_v8cache] Candidate rejected binary={candidate_path} reason={failure_reason}")

    raise RuntimeError(
        'All disassembler candidates failed: ' + ' | '.join(failures)
    )


def parse_disassembled_file(out_name):
    print(f"[parse_v8cache] Parsing disassembled file={os.path.abspath(out_name)}")
    if not os.path.isfile(out_name):
        raise FileNotFoundError(f"Disassembly output file does not exist: {out_name}")

    file_size = os.path.getsize(out_name)
    if file_size == 0:
        raise ValueError(
            f"Disassembly output is empty: {out_name}. "
            "The disassembler binary ran but did not emit View8-compatible text output."
        )

    all_func = parse_file(out_name)
    print(f"[parse_v8cache] Parsing completed successfully")
    return all_func
