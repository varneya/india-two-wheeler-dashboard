"""Deployment contract tests; host mutation/network commands are executable mocks.

Only temporary files and Bash/Python parsing run for real. No package installation,
service operation, model download, remote Git command or HTTP call is performed.
"""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/setup_oracle_vm.sh'
TOKEN = '01234567-89ab-cdef-0123-456789abcdef'

MOCK = r'''
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as log:
    log.write(json.dumps([name, *args]) + '\n')
if name == os.environ.get('FAIL_COMMAND'):
    sys.exit(1)
if name == 'envsubst':
    allowed = set(re.findall(r'\$(\w+)', args[0]))
    sys.stdout.write(re.sub(
        r'\$\{(\w+)\}|\$(\w+)',
        lambda m: os.environ.get(m[1] or m[2], '') if (m[1] or m[2]) in allowed else m[0],
        sys.stdin.read(),
    ))
elif name == 'id':
    if os.environ.get('USER_MISSING') == 'true' and not Path(os.environ['CREATED']).exists():
        sys.exit(1)
    print(os.environ.get('SERVICE_UID', '995') if args[0] == '-u' else 'servicegroup')
elif name == 'useradd':
    Path(os.environ['CREATED']).touch()
elif name == 'sudo':
    assert args[:1] == ['-u'], args
    command = args[2:]
    if command[0] == 'git':
        sys.exit(subprocess.call(command))
    assert command[0] == 'bash' and command[1].endswith('/scripts/install_backend.sh'), command
elif name == 'git':
    operation = args[2:] if args[:1] == ['-C'] else args
    if operation[0] == 'status':
        print(os.environ.get('GIT_DIRTY', ''), end='')
    elif operation[0] == 'symbolic-ref':
        print('refs/remotes/origin/trunk')
    elif operation[0] == 'merge-base':
        sys.exit(int(os.environ.get('UNMERGED_COMMITS', '0')))
    elif operation[0] == 'clone':
        (Path(operation[-1]) / '.git').mkdir(parents=True)
elif name == 'curl':
    counter = Path(os.environ['CURL_COUNT'])
    count = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(count + 1))
    sys.exit(22 if count < int(os.environ.get('CURL_FAILURES', '0')) else 0)
elif name == 'install':
    # Never create host directories. Tests pre-create their own output dirs.
    if '-d' not in args:
        target = Path(args[-1]).resolve()
        assert target.is_relative_to(Path(os.environ['TEST_ROOT']).resolve()), target
        shutil.copyfile(args[-2], target)
        os.chmod(target, int(args[args.index('-m') + 1], 8))
elif name not in {'systemctl', 'apt-get', 'chown', 'sleep', 'caddy', 'ollama', 'gpg'}:
    raise AssertionError('Unexpected external command: ' + name)
'''


@pytest.fixture
def deploy(tmp_path):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name in (
        'envsubst', 'systemctl', 'apt-get', 'sudo', 'useradd', 'id', 'chown',
        'curl', 'sleep', 'caddy', 'ollama', 'git', 'install', 'gpg',
    ):
        executable = bin_dir / name
        executable.write_text(f'#!{sys.executable}\n' + MOCK)
        executable.chmod(0o755)
    (bin_dir / 'python3').symlink_to(sys.executable)
    repo = tmp_path / 'repo'
    (repo / '.git').mkdir(parents=True)
    shutil.copytree(ROOT / 'deploy', repo / 'deploy')
    # Contract fixtures keep this suite independent of the parallel unit author.
    (repo / 'deploy/themes-batch.service').write_text(
        '[Service]\nUser=${TWB_USER}\nGroup=${TWB_USER}\n'
        'WorkingDirectory=${TWB_REPO}/backend\n'
        'EnvironmentFile=-/etc/twowheeler/env\n'
        'ExecStart=${TWB_REPO}/backend/venv/bin/python batch_themes.py\n'
    )
    (repo / 'deploy/themes-batch.timer').write_text('[Timer]\nUnit=themes-batch.service\n')
    for directory in ('config', 'units', 'caddy'):
        (tmp_path / directory).mkdir()
    env = {
        'PATH': f'{bin_dir}:/usr/bin:/bin',
        'SETUP_SCRIPT': str(SCRIPT),
        'TEST_ROOT': str(tmp_path),
        'CALLS': str(tmp_path / 'calls.jsonl'),
        'CREATED': str(tmp_path / 'created-user'),
        'CURL_COUNT': str(tmp_path / 'curl-count'),
        'TWB_DUCKDNS_DOMAIN': 'my-bikes',
        'TWB_DUCKDNS_TOKEN': TOKEN,
        'TWB_REPO': str(repo),
    }

    class Deployment:
        root = tmp_path

        def run(self, commands, **overrides):
            return subprocess.run(
                ['/bin/bash', '-c', 'source "$SETUP_SCRIPT"\n' + commands],
                env={**env, **overrides}, capture_output=True, text=True, timeout=20,
            )

        def calls(self):
            path = Path(env['CALLS'])
            return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    return Deployment()


def succeeded(result):
    assert result.returncode == 0, result.stdout + result.stderr


def test_script_syntax_and_source_have_no_side_effects(deploy):
    result = subprocess.run(['/bin/bash', '-n', str(SCRIPT)], capture_output=True, text=True)
    succeeded(result)
    succeeded(deploy.run(':'))
    assert deploy.calls() == []


@pytest.mark.parametrize('name,value', [
    ('TWB_DUCKDNS_DOMAIN', ''),
    ('TWB_DUCKDNS_DOMAIN', 'a' * 64),
    ('TWB_DUCKDNS_DOMAIN', '-bad'),
    ('TWB_DUCKDNS_DOMAIN', 'bad-'),
    ('TWB_DUCKDNS_DOMAIN', 'bad.duckdns.org'),
    ('TWB_DUCKDNS_DOMAIN', 'x;touch /tmp/injected'),
    ('TWB_DUCKDNS_DOMAIN', 'x\nExecStart=evil'),
    ('TWB_DUCKDNS_TOKEN', ''),
    ('TWB_DUCKDNS_TOKEN', '$(touch /tmp/injected)'),
    ('TWB_DUCKDNS_TOKEN', TOKEN + '&ip=bad'),
    ('TWB_DUCKDNS_TOKEN', TOKEN + '\nOTHER=bad'),
    ('TWB_USER', 'root'),
    ('TWB_USER', 'foo\nGroup=root'),
    ('TWB_REPO', '/opt/repo%h'),
    ('TWB_REPO', '/opt/repo space'),
    ('TWB_INSTALL_OLLAMA', 'yes'),
])
def test_invalid_inputs_fail_before_any_boundary_call(deploy, name, value):
    result = deploy.run('main', **{name: value})
    assert result.returncode != 0
    assert deploy.calls() == []
    if name == 'TWB_DUCKDNS_TOKEN' and value:
        assert value not in result.stdout + result.stderr


def test_default_account_and_ollama_opt_in(deploy):
    result = deploy.run('validate_inputs; printf "%s %s" "$TWB_USER" "$TWB_INSTALL_OLLAMA"; install_ollama')
    succeeded(result)
    assert result.stdout == 'twowheeler false'
    assert deploy.calls() == []


def test_create_system_user_and_use_actual_primary_group(deploy):
    result = deploy.run('validate_inputs; ensure_service_user; printf "%s" "$TWB_GROUP"', USER_MISSING='true')
    succeeded(result)
    assert result.stdout == 'servicegroup'
    call = next(call for call in deploy.calls() if call[0] == 'useradd')
    assert '--system' in call and '--user-group' in call
    assert '/usr/sbin/nologin' in call
    assert call[-1] == 'twowheeler'


def test_existing_user_does_not_get_recreated_and_uid_zero_is_rejected(deploy):
    succeeded(deploy.run('validate_inputs; ensure_service_user'))
    assert not any(call[0] == 'useradd' for call in deploy.calls())
    result = deploy.run('validate_inputs; ensure_service_user', SERVICE_UID='0')
    assert result.returncode != 0


def test_admin_token_generation_preserves_credentials_and_is_idempotent(deploy):
    envfile = deploy.root / 'config/env'
    original = b'# Provider secrets\nGROQ_API_KEY="secret-groq"\nANTHROPIC_API_KEY=secret-ant\nADMIN_TOKEN=""\n'
    envfile.write_bytes(original)
    succeeded(deploy.run('prepare_env "$TEST_ROOT/config/env"'))
    content = envfile.read_bytes()
    assert content.startswith(original)
    token = re.findall(rb'^ADMIN_TOKEN=([A-Za-z0-9_-]+)$', content, re.M)[-1]
    assert len(token) >= 43
    result = deploy.run('prepare_env "$TEST_ROOT/config/env"')
    succeeded(result)
    assert result.stdout == 'false\n'
    assert envfile.read_bytes() == content
    assert envfile.stat().st_mode & 0o777 == 0o600
    for secret in (token.decode(), 'secret-groq', 'secret-ant'):
        assert secret not in result.stdout + result.stderr


def test_missing_envfile_is_created_with_secure_token(deploy):
    result = deploy.run('prepare_env "$TEST_ROOT/new-config/env"')
    succeeded(result)
    envfile = deploy.root / 'new-config/env'
    assert re.fullmatch(r'ADMIN_TOKEN=[A-Za-z0-9_-]{64}\n', envfile.read_text())
    assert envfile.stat().st_mode & 0o777 == 0o600
    assert envfile.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('backend,configured', [
    ('', False), ('""', False), ("'   '", False),
    ('groq:llama-3.1-8b-instant', True), ('"groq:model"', True), ("'groq:model'", True),
])
def test_scheduler_flag_uses_envfile_not_caller_environment(deploy, backend, configured):
    envfile = deploy.root / 'config/env'
    original = f'ADMIN_TOKEN="existing-admin"\nTHEMES_LLM_BACKEND={backend}\n'
    envfile.write_text(original)
    result = deploy.run('prepare_env "$TEST_ROOT/config/env"', THEMES_LLM_BACKEND='groq:ignored')
    succeeded(result)
    assert result.stdout == f'{str(configured).lower()}\n'
    assert envfile.read_text() == original
    assert 'existing-admin' not in result.stdout + result.stderr


def test_envfile_is_data_never_shell_code(deploy):
    sentinel = deploy.root / 'executed'
    original = (
        f'GROQ_API_KEY="$(touch {sentinel})"\n'
        f'ADMIN_TOKEN=existing-admin\nTHEMES_LLM_BACKEND="`touch {sentinel}`"\n'
    )
    envfile = deploy.root / 'config/env'
    envfile.write_text(original)
    succeeded(deploy.run('prepare_env "$TEST_ROOT/config/env"'))
    assert not sentinel.exists()
    assert envfile.read_text() == original


@pytest.mark.parametrize('content', [
    'ADMIN_TOKEN="unterminated\n',
    'ADMIN_TOKEN=value\\\nNEXT=value\n',
    'GROQ_API_KEY="multiline\nADMIN_TOKEN=hidden\n"\n',
    'GROQ_API_KEY=secret\\\nADMIN_TOKEN=hidden\n',
    'export ADMIN_TOKEN=secret\n',
    'THEMES_LLM_BACKEND="groq:model" trailing\n',
])
def test_ambiguous_envfile_fails_closed_without_changing_or_echoing_it(deploy, content):
    envfile = deploy.root / 'config/env'
    envfile.write_text(content)
    result = deploy.run('prepare_env "$TEST_ROOT/config/env"')
    assert result.returncode != 0
    assert envfile.read_text() == content
    assert content not in result.stdout + result.stderr


def test_envfile_symlink_is_rejected(deploy):
    target = deploy.root / 'target'
    target.write_text('preserve')
    (deploy.root / 'config/env').symlink_to(target)
    assert deploy.run('prepare_env "$TEST_ROOT/config/env"').returncode != 0
    assert target.read_text() == 'preserve'


def test_last_effective_env_assignment_controls_token_and_timer(deploy):
    envfile = deploy.root / 'config/env'
    envfile.write_text('ADMIN_TOKEN=old\nADMIN_TOKEN=\nTHEMES_LLM_BACKEND=groq:model\nTHEMES_LLM_BACKEND=\n')
    result = deploy.run('prepare_env "$TEST_ROOT/config/env"')
    succeeded(result)
    assert result.stdout == 'false\n'
    assert re.search(r'ADMIN_TOKEN=[A-Za-z0-9_-]{64}\n$', envfile.read_text())


def test_repo_tracks_remote_default_without_autostash(deploy):
    succeeded(deploy.run('validate_inputs; ensure_service_user; update_repo'))
    calls = deploy.calls()
    git = [call[3:] for call in calls if call[:2] == ['git', '-C']]
    assert ['remote', 'set-head', 'origin', '--auto'] in git
    assert ['checkout', 'trunk'] in git
    assert ['merge', '--ff-only', 'refs/remotes/origin/trunk'] in git
    assert not any(word in {'--autostash', '--rebase', 'reset', 'stash'} for call in calls for word in call)
    assert ['chown', '-R', 'twowheeler:servicegroup', str(deploy.root / 'repo')] in calls


@pytest.mark.parametrize('override', [{'GIT_DIRTY': ' M server.py'}, {'UNMERGED_COMMITS': '1'}])
def test_repo_edits_or_unmerged_commits_stop_before_checkout(deploy, override):
    result = deploy.run('validate_inputs; ensure_service_user; update_repo', **override)
    assert result.returncode != 0
    assert not any('checkout' in call or 'merge' in call for call in deploy.calls())


def test_new_checkout_uses_service_account(deploy):
    target = deploy.root / 'new-repo'
    succeeded(deploy.run('validate_inputs; ensure_service_user; update_repo', TWB_REPO=str(target)))
    assert any(call[:5] == ['sudo', '-u', 'twowheeler', 'git', 'clone'] for call in deploy.calls())


@pytest.mark.parametrize('configured', [False, True])
def test_units_render_group_restart_backend_and_gate_theme_timer(deploy, configured):
    result = deploy.run(
        'validate_inputs; ensure_service_user; umask 077; '
        'THEMES_CONFIGURED=' + str(configured).lower() + '; '
        'install_units "$TEST_ROOT/units" "$TEST_ROOT/config"'
    )
    succeeded(result)
    units = deploy.root / 'units'
    backend = (units / 'twowheeler-backend.service').read_text()
    assert 'User=twowheeler\n' in backend
    assert 'Group=servicegroup\n' in backend
    assert f'WorkingDirectory={deploy.root}/repo/backend' in backend
    assert 'EnvironmentFile=-/etc/twowheeler/env' in backend
    calls = deploy.calls()
    assert ['systemctl', 'restart', 'twowheeler-backend.service'] in calls
    restart = calls.index(['systemctl', 'restart', 'twowheeler-backend.service'])
    health = next(i for i, c in enumerate(calls) if c[0] == 'curl')
    timer = calls.index(['systemctl', 'enable', '--now', 'refresh-all.timer'])
    assert restart < health < timer
    assert (units / 'themes-batch.service').exists() is configured
    assert (units / 'themes-batch.timer').exists() is configured
    assert (['systemctl', 'enable', '--now', 'themes-batch.timer'] in calls) is configured
    if configured:
        content = (units / 'themes-batch.service').read_text()
        assert '${TWB_' not in content
        assert 'Group=servicegroup' in content
    duck = deploy.root / 'config/duckdns.env'
    assert duck.stat().st_mode & 0o777 == 0o600
    assert TOKEN not in result.stdout + result.stderr
    assert '${ADMIN_TOKEN}' in (units / 'refresh-all.service').read_text()


def test_reconfiguration_disables_existing_theme_timer(deploy):
    (deploy.root / 'units/themes-batch.timer').touch()
    succeeded(deploy.run(
        'validate_inputs; ensure_service_user; THEMES_CONFIGURED=false; '
        'install_units "$TEST_ROOT/units" "$TEST_ROOT/config"'
    ))
    assert ['systemctl', 'disable', '--now', 'themes-batch.timer'] in deploy.calls()
    assert ['systemctl', 'enable', '--now', 'themes-batch.timer'] not in deploy.calls()


def test_missing_theme_template_fails_before_starting_services(deploy):
    (deploy.root / 'repo/deploy/themes-batch.service').unlink()
    result = deploy.run(
        'validate_inputs; ensure_service_user; THEMES_CONFIGURED=true; '
        'install_units "$TEST_ROOT/units" "$TEST_ROOT/config"'
    )
    assert result.returncode != 0
    assert not any(call[0] == 'systemctl' for call in deploy.calls())


def test_ollama_explicit_opt_in(deploy):
    result = deploy.run('validate_inputs; install_ollama', TWB_INSTALL_OLLAMA='true')
    succeeded(result)
    calls = deploy.calls()
    assert ['systemctl', 'enable', '--now', 'ollama.service'] in calls
    assert ['ollama', 'pull', 'nomic-embed-text'] in calls
    assert ['ollama', 'pull', 'qwen3:8b'] in calls


def test_caddy_validation_precedes_replacement_and_reload(deploy):
    succeeded(deploy.run('validate_inputs; configure_caddy "$TEST_ROOT/caddy"'))
    calls = deploy.calls()
    validate = next(i for i, call in enumerate(calls) if call[:2] == ['caddy', 'validate'])
    copy = next(i for i, call in enumerate(calls) if call[:3] == ['install', '-m', '644'])
    reload = calls.index(['systemctl', 'reload', 'caddy'])
    assert validate < copy < reload
    assert 'my-bikes.duckdns.org {' in (deploy.root / 'caddy/Caddyfile').read_text()


def test_invalid_caddy_config_keeps_previous_config_and_never_reloads(deploy):
    config = deploy.root / 'caddy/Caddyfile'
    config.write_text('previous config')
    result = deploy.run('validate_inputs; configure_caddy "$TEST_ROOT/caddy"', FAIL_COMMAND='caddy')
    assert result.returncode != 0
    assert config.read_text() == 'previous config'
    assert not any(call[0] == 'systemctl' for call in deploy.calls())
    assert not list(config.parent.glob('.Caddyfile.*'))


def test_health_retries_until_actual_curl_success(deploy):
    succeeded(deploy.run('wait_for_health https://my-bikes.duckdns.org/api/health', CURL_FAILURES='2'))
    curls = [call for call in deploy.calls() if call[0] == 'curl']
    assert len(curls) == 3
    assert all('--fail' in call and '--max-time' in call and '--output' in call for call in curls)


def test_health_failure_is_fatal(deploy):
    result = deploy.run('wait_for_health http://127.0.0.1:8000/api/health; info "Setup complete"', CURL_FAILURES='99')
    assert result.returncode != 0
    assert 'Setup complete' not in result.stdout
    assert len([c for c in deploy.calls() if c[0] == 'curl']) == 30


def test_main_prepares_auth_before_exposure_and_checks_public_health(deploy):
    # Stub high-level boundaries here to test orchestration without any /etc
    # writes; individual helpers above exercise real temp-file rendering.
    result = deploy.run('''
require_root() { :; }
prepare_env() { printf 'auth\\n' >> "$TEST_ROOT/order"; printf false; }
install_packages() { printf 'packages\\n' >> "$TEST_ROOT/order"; }
ensure_service_user() { :; }
update_repo() { :; }
install_backend() { :; }
install_ollama() { :; }
install_units() { printf 'units\\n' >> "$TEST_ROOT/order"; }
configure_caddy() { printf 'caddy\\n' >> "$TEST_ROOT/order"; }
wait_for_health() { printf '%s\\n' "$1" >> "$TEST_ROOT/order"; }
main
''')
    succeeded(result)
    assert (deploy.root / 'order').read_text().splitlines() == [
        'auth', 'packages', 'units', 'caddy', 'https://my-bikes.duckdns.org/api/health',
    ]
    assert 'Setup complete' in result.stdout
    assert TOKEN not in result.stdout + result.stderr
