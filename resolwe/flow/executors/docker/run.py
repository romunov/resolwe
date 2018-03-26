"""Docker workflow executor."""
from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import shlex
import subprocess
import tempfile

from . import constants
from ..global_settings import PROCESS_META, SETTINGS
from ..local.run import FlowExecutor as LocalFlowExecutor
from ..protocol import ExecutorFiles
from .seccomp import SECCOMP_POLICY


class FlowExecutor(LocalFlowExecutor):
    """Docker executor."""

    name = 'docker'

    def __init__(self, *args, **kwargs):
        """Initialize attributes."""
        super(FlowExecutor, self).__init__(*args, **kwargs)

        self.container_name_prefix = None
        self.tools_volumes = None
        self.temporary_files = []
        self.command = SETTINGS.get('FLOW_DOCKER_COMMAND', 'docker')

    def _generate_container_name(self):
        """Generate unique container name."""
        return '{}_{}'.format(self.container_name_prefix, self.data_id)

    def start(self):
        """Start process execution."""
        # arguments passed to the Docker command
        command_args = {
            'command': self.command,
            'container_image': self.requirements.get('image', constants.DEFAULT_CONTAINER_IMAGE),
        }

        # Get limit defaults.
        limit_defaults = SETTINGS.get('FLOW_PROCESS_RESOURCE_DEFAULTS', {})

        # Set resource limits.
        limits = []
        # Each core is equivalent to 1024 CPU shares. The default for Docker containers
        # is 1024 shares (we don't need to explicitly set that).
        limits.append('--cpu-shares={}'.format(int(self.process['resource_limits']['cores']) * 1024))

        memory = self.process['resource_limits']['memory']

        # Set both memory and swap limits as we want to enforce the total amount of memory
        # used (otherwise swap would not count against the limit).
        limits.append('--memory={0}m --memory-swap={0}m'.format(memory))

        # Set ulimits for interactive processes to prevent them from running too long.
        if self.process['scheduling_class'] == PROCESS_META['SCHEDULING_CLASS_INTERACTIVE']:
            # TODO: This is not very good as each child gets the same limit.
            limits.append('--ulimit cpu={}'.format(limit_defaults.get('cpu_time_interactive', 30)))

        command_args['limits'] = ' '.join(limits)

        # set container name
        self.container_name_prefix = SETTINGS.get('FLOW_EXECUTOR', {}).get('CONTAINER_NAME_PREFIX', 'resolwe')
        command_args['container_name'] = '--name={}'.format(self._generate_container_name())

        if 'network' in self.resources:
            # Configure Docker network mode for the container (if specified).
            # By default, current Docker versions use the 'bridge' mode which
            # creates a network stack on the default Docker bridge.
            network = SETTINGS.get('FLOW_EXECUTOR', {}).get('NETWORK', '')
            command_args['network'] = '--net={}'.format(network) if network else ''
        else:
            # No network if not specified.
            command_args['network'] = '--net=none'

        # Security options.
        security = []

        # Generate and set seccomp policy to limit syscalls.
        policy_file = tempfile.NamedTemporaryFile(mode='w')
        json.dump(SECCOMP_POLICY, policy_file)
        policy_file.file.flush()
        if not SETTINGS.get('FLOW_DOCKER_DISABLE_SECCOMP', False):
            security.append('--security-opt seccomp={}'.format(policy_file.name))
        self.temporary_files.append(policy_file)

        # Drop all capabilities and only add ones that are needed.
        security.append('--cap-drop=all')

        command_args['security'] = ' '.join(security)

        # Setup Docker volumes.
        def new_volume(kind, base_dir_name, volume, path=None, read_only=True):
            """Generate a new volume entry.

            :param kind: Kind of volume, which is used for getting extra options from
                settings (the ``FLOW_DOCKER_VOLUME_EXTRA_OPTIONS`` setting)
            :param base_dir_name: Name of base directory setting for volume source path
            :param volume: Destination volume mount point
            :param path: Optional additional path atoms appended to source path
            :param read_only: True to make the volume read-only
            """
            if path is None:
                path = []

            path = [str(atom) for atom in path]

            options = set(SETTINGS.get('FLOW_DOCKER_VOLUME_EXTRA_OPTIONS', {}).get(kind, '').split(','))
            options.discard('')
            # Do not allow modification of read-only option.
            options.discard('ro')
            options.discard('rw')

            if read_only:
                options.add('ro')
            else:
                options.add('rw')

            return {
                'src': os.path.join(SETTINGS['FLOW_EXECUTOR'].get(base_dir_name, ''), *path),
                'dest': volume,
                'options': ','.join(options),
            }

        volumes = [
            new_volume('data', 'DATA_DIR', constants.DATA_VOLUME, [self.data_id], read_only=False),
            new_volume('data_all', 'DATA_DIR', constants.DATA_ALL_VOLUME),
            new_volume('upload', 'UPLOAD_DIR', constants.UPLOAD_VOLUME, read_only=False),
            new_volume('secrets', 'RUNTIME_DIR', constants.SECRETS_VOLUME, [self.data_id, ExecutorFiles.SECRETS_DIR]),
        ]

        # Generate dummy passwd and create mappings for it. This is required because some tools
        # inside the container may try to lookup the given UID/GID and will crash if they don't
        # exist. So we create minimal user/group files.
        passwd_file = tempfile.NamedTemporaryFile(mode='w')
        passwd_file.write('root:x:0:0:root:/root:/bin/bash\n')
        passwd_file.write('user:x:{}:{}:user:/:/bin/bash\n'.format(os.getuid(), os.getgid()))
        passwd_file.file.flush()
        self.temporary_files.append(passwd_file)

        group_file = tempfile.NamedTemporaryFile(mode='w')
        group_file.write('root:x:0:\n')
        group_file.write('user:x:{}:user\n'.format(os.getgid()))
        group_file.file.flush()
        self.temporary_files.append(group_file)

        volumes += [
            new_volume('users', None, '/etc/passwd', [passwd_file.name]),
            new_volume('users', None, '/etc/group', [group_file.name]),
        ]

        # Create volumes for tools.
        # NOTE: To prevent processes tampering with tools, all tools are mounted read-only
        self.tools_volumes = []
        for index, tool in enumerate(self.get_tools_paths()):
            self.tools_volumes.append(new_volume(
                'tools',
                None,
                os.path.join('/usr/local/bin/resolwe', str(index)),
                [tool]
            ))

        volumes += self.tools_volumes

        # Add any extra volumes verbatim.
        volumes += SETTINGS.get('FLOW_DOCKER_EXTRA_VOLUMES', [])

        # Create Docker --volume parameters from volumes.
        command_args['volumes'] = ' '.join(['--volume="{src}":"{dest}":{options}'.format(**volume)
                                            for volume in volumes])

        # Set working directory to the data volume.
        command_args['workdir'] = '--workdir={}'.format(constants.DATA_VOLUME)

        # Change user inside the container.
        command_args['user'] = '--user={}:{}'.format(os.getuid(), os.getgid())

        # A non-login Bash shell should be used here (a subshell will be spawned later).
        command_args['shell'] = '/bin/bash'

        self.proc = subprocess.Popen(
            shlex.split(
                '{command} run --rm --interactive {container_name} {network} {volumes} {limits} '
                '{security} {workdir} {user} {container_image} {shell}'.format(**command_args)),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)

        self.stdout = self.proc.stdout

    def run_script(self, script):
        """Execute the script and save results."""
        # Create a Bash command to add all the tools to PATH.
        tools_paths = ':'.join([map_["dest"] for map_ in self.tools_volumes])
        add_tools_path = 'export PATH=$PATH:{}'.format(tools_paths)
        # Spawn another child bash, to avoid running anything as PID 1, which has special
        # signal handling (e.g., cannot be SIGKILL-ed from inside).
        # A login Bash shell is needed to source /etc/profile.
        self.proc.stdin.write('/bin/bash --login; exit $?' + os.linesep)
        self.proc.stdin.write(os.linesep.join(['set -x', 'set +B', add_tools_path, script]) + os.linesep)
        self.proc.stdin.close()

    def end(self):
        """End process execution."""
        try:
            self.proc.wait()
        finally:
            # Cleanup temporary files.
            for temporary_file in self.temporary_files:
                temporary_file.close()
            self.temporary_files = []

        return self.proc.returncode

    def terminate(self):
        """Terminate a running script."""
        subprocess.call(shlex.split('{} rm -f {}'.format(self.command, self._generate_container_name())))

        super().terminate()
