import asyncio
import os
import pkgutil
import typing

import aiohttp
import pychromecast
from aiohttp import web
import aiohttp_cors


def replace_all(template, **kwargs):
    t = template
    for k, v in kwargs.items():
        t = t.replace(f'%({k})', str(v))
    return t


async def cast_server_factory(
        video_path, host, port, cast: pychromecast.Chromecast, loop=None,
        logger=None, start=True, stopper=None, is_stopped=None, subtitles=None,
):
    async def handle_video(_):
        return web.FileResponse(video_path)

    async def handle_pause(_):
        cast.media_controller.pause()
        return web.Response()

    async def handle_play(_):
        cast.media_controller.play()
        return web.Response()

    async def handle_status(_):
        return web.Response(text=cast.media_controller.status.player_state)

    async def handle_stop(_):
        cast.media_controller.stop()
        stopper()
        return web.Response()

    async def handle_media(_):
        output = replace_all(
            pkgutil.get_data('aiocast', 'controls.html').decode(),
            server=f'{host}:{port}',
            title=cast.media_controller.title,
            duration=cast.media_controller.status.duration,
            current=cast.media_controller.status.current_time,
            state=cast.status,
        )

        return web.Response(body=output, content_type='text/html')

    async def handle_subtitles(_):
        return web.FileResponse(subtitles,
                                headers={'Content-Type': 'text/vtt'})

    async def handle_ws(request: aiohttp.web.Request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        def get_info():
            return {
                'state': cast.media_controller.status.player_state,
                'current_time':
                    cast.media_controller.status.adjusted_current_time,
                'duration': cast.media_controller.status.duration
            }

        await ws.send_json(get_info())

        async def send_info():
            while not is_stopped():
                await ws.send_json(get_info())
                await asyncio.sleep(0.1, loop=loop)
            await ws.send_json(get_info())
            await ws.close()

        info_co = asyncio.ensure_future(send_info(), loop=loop)

        async def get_command():
            async for msg in ws:  # type: typing.Union[aiohttp.WSMessage]
                if msg.type == aiohttp.WSMsgType.TEXT:
                    logger.debug(f'WSMessage: {msg}')
                    if msg.data == 'pause':
                        cast.media_controller.pause()
                    elif msg.data == 'play':
                        cast.media_controller.play()
                    elif msg.data == 'stop':
                        cast.media_controller.stop()
                    await ws.send_json(get_info())
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.exception(ws.exception())

        await asyncio.gather(info_co, get_command())

        logger.debug('WS connection closed %s', request.remote)

        return ws

    app = web.Application(loop=loop)
    app.add_routes([
        web.get(f'/{os.path.basename(video_path)}', handle_video),
        web.get('/media/', handle_media),
        web.get('/media/pause', handle_pause),
        web.get('/media/play', handle_play),
        web.get('/media/status', handle_status),
        web.get('/media/stop', handle_stop),
        web.get('/media/ws', handle_ws),
        web.get('/subtitles', handle_subtitles)
    ])
    if subtitles:
        app.add_routes([web.get(f'/subtitles/{os.path.basename(subtitles)}', handle_subtitles)])

    # Subtitles needs cors.
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })

    for route in app.router.routes():
        cors.add(route)

    runner = web.AppRunner(app)

    await runner.setup()
    site = web.TCPSite(runner, host, port)

    if start:
        await site.start()

    return site
