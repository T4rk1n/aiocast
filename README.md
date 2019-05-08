# aiocast

Cast videos to chromecast devices from the terminal.

## Install

`$ pip install aiocast`

## Usage

- `$ aiocast play video.mp4`
- `$ aiocast list-devices`
- `$ aiocast device-info "Home"`

```
$ aiocast play --help                                                                                                                                                                                                                ✔  19:31 
usage: aiocast play [-h] [-d DEVICE_NAME] [-p PORT] [-t TIMEOUT] [-i IDLE]
                    [--local-ip LOCAL_IP] [--mimetype MIMETYPE]
                    media

Cast a video

positional arguments:
  media                 Path to the video to cast.

optional arguments:
  -h, --help            show this help message and exit
  -d DEVICE_NAME, --device-name DEVICE_NAME
                        The target cast device name (default: None)
  -p PORT, --port PORT  Port of the local cast server (default: None)
  -t TIMEOUT, --timeout TIMEOUT
                        Timeout after which the program will close if stuck on
                        buffering. (default: 60)
  -i IDLE, --idle IDLE  Time to stay idle after a stop or media ends (default:
                        2.5)
  --local-ip LOCAL_IP   Local ip to use, otherwise get the first private ip
                        available. (default: None)
  --mimetype MIMETYPE   Set the mimetype of the media, otherwise will guess.
                        (default: None)

```
