from precept import Config, ConfigProperty


class AiocastConfig(Config):
    """Aiocast configuration"""

    default_device = ConfigProperty(
        default='',
        comment='The default device to use if no device is provided.'
    )
    cast_server_port = ConfigProperty(
        default=5416, comment='Port for the cast server to use'
    )

    def __init__(self):
        super().__init__(root_name='aiocast')
