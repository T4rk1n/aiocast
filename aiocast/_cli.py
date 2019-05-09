"""
Cast to chromecast devices from the commandline.
"""
import asyncio
import os
import socket
import sys
import mimetypes
import time
from concurrent.futures.thread import ThreadPoolExecutor

import pychromecast
import appdirs

from precept import CliApp, Argument, Command, spinner, KeyHandler

from aiocast._cast_server import cast_server_factory
from aiocast._constants import BUFFERING, IDLE, STOPPED_STATES, PLAYING, PAUSED
from aiocast._version import __version__


def get_own_ip(host='8.8.8.8', port=80):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, port))
        ip = s.getsockname()[0]
    except socket.error:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


class Aiocast(CliApp):
    """Cast videos to chromecast devices."""
    default_configs = {
        'default_device': '',
        'cast_server_port': 5416,
    }
    version = __version__

    def __init__(self):
        self.cache_dir = appdirs.user_cache_dir('aiocast')
        super().__init__(
            config_file=[
                'aiocast.yml',
                os.path.join(
                    appdirs.user_config_dir('aiocast'),
                    'configs.yml'
                ),
            ],
            executor=ThreadPoolExecutor(),
            add_dump_config_command=True,
        )

    async def _get_cast(self, device_name=None, first=True, timeout=None) -> pychromecast.Chromecast:
        if not device_name:
            device_name = self.configs.get('default_device')
        if not device_name and not first:
            self.logger.error('No device targeted!')
            self.logger.info(
                f'Set a default target device in {self.cli.config_file} or '
                f'specify a --device-name'
            )
            await self.list_devices()
            sys.exit(1)

        ns = {}

        def _on_found(c):
            self.logger.debug(f'Found device: {c.device.friendly_name}')

            if c.device.friendly_name == device_name or (
                    not device_name and first
            ):
                ns['cast'] = c
                ns['stop']()

        ns['stop'] = pychromecast.get_chromecasts(
            callback=_on_found, blocking=False, timeout=timeout
        )
        await asyncio.sleep(0.5)
        await spinner(
            lambda: ns.get('cast'),
            message=f'Searching for {device_name or "cast destination"}... '
        )

        cast: pychromecast.Chromecast = ns['cast']
        self.logger.debug(f'Found cast: {cast}')

        return cast

    @Command(
        Argument('media', help='Path to the video to cast.'),
        Argument('-d', '--device-name', help='The target cast device name'),
        Argument('-p', '--port', help='Port of the local cast server'),
        Argument(
            '-t', '--timeout',
            type=float,
            default=60,
            help='Timeout after which the program will close if '
                 'stuck on buffering.'
        ),
        Argument(
            '-i', '--idle',
            type=float, default=2.5,
            help='Time to stay idle after a stop or media ends'
        ),
        Argument(
            '--local-ip',
            help='Local ip to use, otherwise get the'
                 ' first private ip available.'
        ),
        Argument(
            '--mimetype',
            help='Set the mimetype of the media, otherwise will guess.'
        ),
        Argument(
            '-s', '--subtitles',
            help='Path to a subtitle files (Only VTT supported)',
        ),
        description='Cast a video'
    )
    async def play(self, media, device_name, port, timeout, idle, local_ip, mimetype, subtitles):
        path = os.path.expanduser(media)
        server_port = port or self.configs.get('cast_server_port')

        ns = {
            'buffer_start': 0,
            'buffer_warning': '',
            'stopped': False,
            'idle_time': 0,
        }

        def is_stopped():
            return ns['stopped']

        if mimetype:
            content_type = mimetype
        else:
            content_type, _ = mimetypes.guess_type(path)

        if not os.path.exists(path):
            raise FileNotFoundError(path)

        cast = await self._get_cast(
            device_name, first=not device_name, timeout=timeout
        )
        cast.socket_client.start()

        def play_stopper():
            cast.quit_app()
            ns['stopped'] = True

        site = None

        sp = spinner(
            lambda: cast.socket_client.is_connected and site is not None,
            message='Preparing sockets ... '
        )

        await self.executor.execute(cast.wait)

        own_ip = local_ip or get_own_ip(cast.host, cast.port)
        cast_server = f'{own_ip}:{server_port}'

        if subtitles:
            sub_type = subtitles.split('.')[-1]
            if sub_type != 'vtt':
                self.logger.warn(
                    f'Subtitle type not supported {sub_type}, '
                    f'convert at: https://www.3playmedia.com/solutions'
                    f'/features/tools/captions-format-converter/'
                )
            sub_type = f'text/{sub_type}'
            sub_uri = f'http://{cast_server}/subtitles/{os.path.basename(subtitles)}'

            self.logger.debug(f'Using subtitles {subtitles}:{sub_type}:{sub_uri}')
        else:
            sub_type = None
            sub_uri = None

        site = await cast_server_factory(
            path, own_ip, server_port, cast,
            logger=self.logger,
            loop=self.executor.loop,
            stopper=play_stopper,
            is_stopped=is_stopped,
            subtitles=subtitles,
        )
        await sp

        self.logger.debug(f'Cast server started at {cast_server}')
        self.logger.debug(f'Content-Type: {content_type}')

        cast.media_controller.play_media(
            f'http://{cast_server}/{os.path.basename(media)}',
            content_type=content_type,
            title=os.path.basename(media),
            subtitles=sub_uri,
            subtitles_mime=sub_type,
        )

        sp = spinner(
            lambda: cast.media_controller.is_active,
            message='Waiting for the player to be ready...'
        )

        # Here we block until active with asyncio deferred in a PoolExecutor
        await asyncio.gather(
            sp, self.executor.execute(cast.media_controller.block_until_active)
        )
        cast.media_controller.play()

        if subtitles:
            cast.media_controller.update_status()
            cast.media_controller.enable_subtitle(1)

        def on_continue():
            return cast.media_controller.status.player_is_playing

        def on_rewind(*args):
            """Rewind"""
            self.logger.debug('rewind')
            cast.media_controller.rewind()

        def on_play(*args):
            """Play"""
            self.logger.debug('play')
            cast.media_controller.play()

        def on_pause(*args):
            """Pause"""
            self.logger.debug('pause')
            cast.media_controller.pause()

        def on_toggle(*args):
            """<Space> Toggle play/pause."""
            state = cast.media_controller.status.player_state
            self.logger.debug(f'toggle {state}')
            if state == PLAYING:
                cast.media_controller.pause()
            elif state == PAUSED:
                cast.media_controller.play()
            else:
                self.logger.error(f'Bad toggle state: {state}')

        def on_stop(*args):
            """Stop"""
            self.logger.debug('stop')
            cast.media_controller.stop()

        def on_quit(_, stop):
            """Quit"""
            self.logger.debug('quit')
            cast.media_controller.stop()
            play_stopper()
            stop()  # This stop the keyhandler loop.

        handlers = {
            'r': on_rewind,
            'x': on_play,
            'p': on_pause,
            's': on_stop,
            ' ': on_toggle,
            'q': on_quit,
        }

        keyhandler = KeyHandler(handlers, loop=self.loop)

        # Wait for it to start play
        await asyncio.sleep(0.1)
        await spinner(
            on_continue,
            message='Waiting for the player to start playing...'
        )

        self.logger.info(f'Playing {media} on {cast.device.friendly_name}')
        self.logger.info(f'Control the cast at http://{cast_server}/media/')
        # Wait until complete
        await asyncio.sleep(0.1)

        def on_spin():
            if is_stopped():
                return True
            state = cast.media_controller.status.player_state
            if state == BUFFERING and timeout is not None:
                if not ns['buffer_start']:
                    ns['buffer_start'] = time.time()
                    return False
                delay = time.time() - ns['buffer_start']
                if delay >= timeout:
                    ns['buffer_warning'] = f'Stopped after {timeout} seconds' \
                        f' stuck on buffering.'
                    play_stopper()
                    return True
                return False
            elif state == IDLE:
                if not ns['idle_time']:
                    ns['idle_time'] = time.time()
                    return False
                delay = time.time() - ns['idle_time']
                if delay >= idle:
                    play_stopper()
                    return True
                return False
            if ns['buffer_start']:
                ns['buffer_start'] = 0
            if ns['idle_time']:
                ns['idle_time'] = 0
            return state in STOPPED_STATES

        keyhandler.print_keys()
        spin = spinner(
            on_spin,
            message=lambda: f'{cast.media_controller.status.player_state} ...'
        )

        async with keyhandler:
            await spin

        if ns['buffer_warning']:
            self.logger.warn(ns['buffer_warning'])

        self.logger.debug('Stopping')

        # Stop the server
        await site.stop()

        self.logger.debug('Stopped server')

    @Command(
        Argument('-r', '--raw', action='store_true', help='names only.'),
        description='List the available cast devices on the network.'
    )
    async def list_devices(self, raw=False):
        self.logger.debug('\nListing devices\n')
        for i, cc in enumerate(pychromecast.get_chromecasts()):
            if raw:
                print(cc.device.friendly_name)
            else:
                print(f'{i + 1}. {cc.device.friendly_name}')

    @Command(
        Argument('device_name', help='Device to display info'),
        Argument('-r', '--raw',
                 help='Print the cast directly.', action='store_true'),
        description='Display the device information'
    )
    async def device_info(self, device_name, raw):
        cast = await self._get_cast(device_name)
        if raw:
            print(cast)
        else:
            print(f'Address: {cast.host}:{cast.port}')
            print(f'Name: {cast.device.friendly_name}')
            print(f'Model: {cast.device.manufacturer}, '
                  f'{cast.device.model_name}')
            print(f'UUID: {cast.device.uuid}')
            print(f'Type: {cast.cast_type}')


def cli():
    c = Aiocast()
    c.start()


if __name__ == '__main__':
    cli()
