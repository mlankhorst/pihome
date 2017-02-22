#!/usr/bin/python3

import sys, gi, os, socket, time, subprocess

gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import GObject, Gst, GstRtspServer, GLib, GObject

def _unlink(what):
    try:
        os.unlink(what)
    except FileNotFoundError:
        return

def initialize_rtsp(name, rtsp, vidsrc, sndsrc):
    vidpipe = vidsrc + ' ! rtph264pay name=pay0'
    sndpipe = sndsrc + ' ! aacparse ! queue ! rtpmp4apay name=pay1'

    full_stream = GstRtspServer.RTSPMediaFactory()
    full_stream.set_shared(True)
    full_stream.set_launch(vidpipe + ' ' + sndpipe)
    rtsp.get_mount_points().add_factory('/%s' % name, full_stream)

    vidonly_stream = GstRtspServer.RTSPMediaFactory()
    vidonly_stream.set_shared(True)
    vidonly_stream.set_launch(vidpipe)

    rtsp.get_mount_points().add_factory('/%s.m4v' % name, vidonly_stream)

def initialize_cam(name, settings):
    vidsocket = '/tmp/%sv' % name

    _unlink(vidsocket)

    vidcaps = 'video/x-h264, stream-format=byte-stream, width=1280, height=720'

    if settings['video_source'] == 'rpicamsrc':
        vidcaps += ', alignment=nal, profile=baseline'
    else:
        vidcaps += ', alignment=au, profile=constrained-baseline'

    vidshmsrc = 'shmsrc name=camsrc is-live=0 do-timestamp=1 socket-path=%s ! %s' % (vidsocket, vidcaps)
    sndshmsrc = settings['audio_pipe']

    if settings['video_source'] == 'rpicamsrc':
        shmsink = Gst.parse_launch((
            'rpicamsrc do-timestamp=1 rotation=180 preview=0 inline-headers=1'
            ' name=rpicamsrc ! %s, framerate=0/1, alignment=nal ! '
            'shmsink socket-path=%s async=0 qos=0 sync=0 wait-for-connection=0'
            % (vidcaps, vidsocket)))
    elif settings['video_source'] == 'uvch264src':
        shmsink = Gst.parse_launch((
            'uvch264src do-timestamp=1 auto-start=1 mode=2 rate-control=vbr'
            ' iframe-period=500 post-previews=0 initial-bitrate=2000000'
            ' peak-bitrate=4500000 average-bitrate=3000000 name=uvch264src '
            'uvch264src.vfsrc ! image/jpeg,framerate=30/1 ! '
            'fakesink sync=0 qos=0 async=0 '
            'uvch264src.vidsrc ! %s, framerate=30/1 ! h264parse config-interval=1 ! '
            'shmsink socket-path=%s async=0 qos=0 sync=0 wait-for-connection=0'
            % (vidcaps, vidsocket)))

    vidsave = Gst.parse_launch((
        '%s ! h264parse config-interval=-1 ! mux.video '
        '%s ! aacparse ! queue ! mux.audio_0 '
        ''
        'splitmuxsink name=mux async=0 sync=0 qos=0 max-size-time=900000000000 '
        % (vidshmsrc, sndshmsrc)))

    # stream has do-timestamp=1 now, sadly.. hope nothing breaks!
    vidstream = Gst.parse_launch((
        '%s ! h264parse ! queue ! mux.video '
        '%s ! aacparse ! queue ! mux.audio '
        'flvmux name=mux streamable=true ! '
        'rtmpsink name=rtmpsink0 qos=0 sync=0 async=0'
        % (vidshmsrc, sndshmsrc)))

    initialize_rtsp(name, settings['rtsp'], vidshmsrc, sndshmsrc)
    return shmsink, vidsave, vidstream

class Camera:
    def __init__(self, name, settings):
        self.name = name
        self.cam, self.save, self.stream = initialize_cam(name, settings)

    def cam_message(self, obj, event):
        if event.src == self.cam:
            if event.type == Gst.MessageType.STATE_CHANGED or \
               event.type == Gst.MessageType.ASYNC_DONE:
                if event.type == Gst.MessageType.STATE_CHANGED:
                    prev, new, pending = event.parse_state_changed()
                else:
                    new = event.src.get_state(0)[0]
                    pending = event.src.get_state(0)[1]

                if pending == Gst.State.VOID_PENDING:
                    print("New state: %s " % new)
                    if new == Gst.State.NULL:
                        shmsink = self.cam.get_by_name('shmsink')
                        _unlink(shmsink.get_property('socket-path'))
            elif event.type == Gst.MessageType.EOS:
                self.shutdown()
            else:
                print('Streaming event: ', event.type)
        return

    def save_message(self, obj, event):
        if event.src == self.save:
            if event.type == Gst.MessageType.STATE_CHANGED:
                prev, new, pending = event.parse_state_changed()
                if pending == Gst.State.VOID_PENDING:
                    print("New recording state: %s " % new)
            elif event.type == Gst.MessageType.EOS:
                print('Received end of stream, shutting down recording.')
                self.save.set_state(Gst.State.NULL)
            else:
                print('Recording event: ', event.type)

    def stream_message(self, obj, event):
        if event.src == self.stream:
            if event.type == Gst.MessageType.STATE_CHANGED:
                prev, new, pending = event.parse_state_changed()
                if pending == Gst.State.VOID_PENDING:
                    print("New streaming state: %s " % new)
            else:
                print('Streaming event: ', event.type)
        else:
            if event.type == Gst.MessageType.ERROR:
                gthing, debug = event.parse_error()
                print('Streaming error: ', gthing, debug)
            else:
                print('Streaming element event: ', event.type)

    def save_location(self, splitmux, fragment_id):
        return time.strftime('/home/pi/vids/' + self.name + '-video-%Y-%02m-%02d-%02H-%02M.mp4')

    def startrecord(self):
        if self.save.get_state(0)[1] != Gst.State.NULL:
            return

        self.save.set_state(Gst.State.PLAYING)

    def stoprecord(self):
        if self.save.get_state(0)[1] > Gst.State.NULL:
            self.save.send_event(Gst.Event.new_eos())

    def startstream(self, url, text):
        cam = self.cam.get_by_name('rpicamsrc')
        if cam and text:
            cam.set_property('annotation-mode', 1)
            cam.set_property('annotation-text', text)

        rtmpsink = self.stream.get_by_name('rtmpsink0')
        rtmpsink.set_property('location', url)

        self.stream.set_state(Gst.State.PLAYING)

    def stopstream(self):
        cam = self.cam.get_by_name('rpicamsrc')
        if cam:
            cam.set_property('annotation-mode', 0)

        self.stream.set_state(Gst.State.NULL)

    def shutdown(self):
        self.stopstream()
        self.stoprecord()
        self.cam.set_state(Gst.State.NULL)

    def run(self):
        self.cam.get_bus().connect("message", self.cam_message)
        self.save.get_bus().connect("message", self.save_message)
        self.save.get_by_name("mux").connect("format-location", self.save_location)
        self.stream.get_bus().connect("message", self.stream_message)

        self.cam.set_state(Gst.State.PLAYING)

    def night_mode(self):
        cam = self.cam.get_by_name('uvch264src')
        if cam:
            dev = cam.get_property('device')

            subprocess.call(['v4l2-ctl', '-d', dev, '-c',
                            ('brightness=140,saturation=140,contrast=0,'
                             'gain=255,focus_auto=0,exposure_auto=1')])
            subprocess.call(['v4l2-ctl', '-d', dev, '-c',
                             'focus_absolute=30,exposure_absolute=2047'])
        else:
            cam = self.cam.get_by_name('rpicamsrc')

            cam.set_property('saturation', -100)
            cam.set_property('brightness', 60)
            cam.set_property('contrast', 20)
            cam.set_property('exposure-mode', 'night')
            cam.set_property('iso', 1600)
            cam.set_property('drc', 3)
            cam.set_property('metering-mode', 'spot')
            cam.set_property('sensor-mode', 5)
            cam.set_property('quantisation-parameter', 15)
            cam.set_property('bitrate', 0)
            cam.set_property('awb-mode', 0)
            cam.set_property('awb-gain-red', 2.)
            cam.set_property('awb-gain-blue', 2.)
            cam.set_property('shutter-speed', 250000) # in us

    def day_mode(self):
        cam = self.cam.get_by_name('uvch264src')
        if cam:
            dev = cam.get_property('device')

            subprocess.call(['v4l2-ctl', '-d', dev, '-c',
                            ('brightness=128,saturation=128,contrast=128'
                             'gain=255,focus_auto=0,exposure_auto=3')])
            subprocess.call(['v4l2-ctl', '-d', dev, '-c',
                             'focus_absolute=30'])
        else:
            cam = self.cam.get_by_name('rpicamsrc')

            cam.set_property('saturation', 0)
            cam.set_property('brightness', 50)
            cam.set_property('contrast', 0)
            cam.set_property('exposure-mode', 'auto')
            cam.set_property('iso', 0)
            cam.set_property('drc', 0)
            cam.set_property('metering-mode', 1)
            cam.set_property('sensor-mode', 5)
            cam.set_property('quantisation-parameter', 15)
            cam.set_property('bitrate', 0)
            cam.set_property('awb-mode', 'tungsten')
            cam.set_property('shutter-speed', 0) # Variable exposure

    def shimmer_mode(self):
        cam = self.cam.get_by_name('uvch264src')
        if cam:
            dev = cam.get_property('device')

            subprocess.call(['v4l2-ctl', '-d', dev, '-c',
                            ('brightness=128,saturation=128,contrast=128,'
                             'gain=255,focus_auto=0,exposure_auto=1')])
            subprocess.call(['v4l2-ctl', '-d', dev, '-c',
                             'focus_absolute=30,exposure_absolute=2047'])
        else:
            cam = self.cam.get_by_name('rpicamsrc')

            cam.set_property('saturation', -100)
            cam.set_property('brightness', 60)
            cam.set_property('contrast', 20)
            cam.set_property('exposure-mode', 'night')
            cam.set_property('iso', 1600)
            cam.set_property('drc', 3)
            cam.set_property('metering-mode', 'spot')
            cam.set_property('sensor-mode', 5)
            cam.set_property('quantisation-parameter', 15)
            cam.set_property('bitrate', 0)
            cam.set_property('awb-mode', 0)
            cam.set_property('awb-gain-red', 2.)
            cam.set_property('awb-gain-blue', 2.)
            cam.set_property('shutter-speed', 0) # variable

    def setprop(self, key, value):
        cam = self.cam.get_by_name('uvch264src')
        if cam:
            dev = cam.get_property('device')

            subprocess.call(['v4l2-ctl', '-d', dev, '-c', '%s=%s' % (key, value)])
        else:
            cam = self.cam.get_by_name('rpicamsrc')

            try:
                val = int(value)
            except ValueError:
                val = value

            cam.set_property(key, val)

    def run_command(self, socket, data):
        if ' ' in data:
            cmd, args = data.split(' ',  1)
        else:
            cmd = data
            args = None

        if cmd == 'save':
            self.startrecord()
        elif cmd == 'done':
            self.stoprecord()
        elif cmd == 'night':
            self.night_mode()
        elif cmd == 'day':
            self.day_mode()
        elif cmd == 'shimmer':
            self.shimmer_mode()
        elif cmd == 'setprop':
            if not '=' in args or ' ' in args:
                socket.write(b'Syntax: setprop key=value\n')
                return

            key, value = args.split('=', 1)
            self.setprop(key, value)
        elif cmd == 'startstream':
            if not args:
                socket.send(b'Syntax: startstream rtmp://stream <annotation text>\n')
                return

            if ' ' in args:
                url, text = args.split(' ', 1)
            else:
                url = args
                text = None

            self.startstream(url, text)
        elif cmd == 'stopstream':
            self.stopstream()
        else:
            socket.send(b'Unknown command: ' + cmd.split(' ', 1)[0].encode() + b'\n')
            return
        socket.send(b'OK\n')

