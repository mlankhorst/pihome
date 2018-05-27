#!/usr/bin/python3

import sys, gi, os, socket, time, subprocess

gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
gi.require_version('GstRtspServer', '1.0')
gi.require_version('GstVideo', '1.0')

from gi.repository import GObject, Gst, GstRtspServer, GstVideo, GLib, GObject

def _unlink(what):
    try:
        os.unlink(what)
    except FileNotFoundError:
        return

class Camera:
    def __init__(self, name, settings):
        self.name = name
        self.timer = 0
        self.key_count = 0

        vidsocket = '/tmp/%sv' % name
        _unlink(vidsocket)

        if settings['video_source'] == 'rpicamsrc':
            self.cam = self.rpicamsrc(vidsocket)
        elif settings['video_source'] == 'uvch264src':
            self.cam = self.uvch264src(vidsocket)

        vidshmsrc = ('shmsrc name=camsrc is-live=1 do-timestamp=1 socket-path=%s ! '
                     'application/x-rtp ! rtph264depay ! '
                     'video/x-h264, stream-format=byte-stream, alignment=au, profile=baseline'
                     % vidsocket)
        sndshmsrc = settings['audio_pipe']

        self.initialize_streams(vidshmsrc, sndshmsrc)
        self.initialize_rtsp(settings['rtsp'], vidshmsrc, sndshmsrc)

    def uvch264src(self, vidsocket):
        return Gst.parse_launch((
            'uvch264src do-timestamp=1 auto-start=1 mode=2 rate-control=vbr'
            ' iframe-period=500 post-previews=0 initial-bitrate=2000000 io-mode=userptr'
            ' peak-bitrate=4500000 average-bitrate=3000000 name=uvch264src '
            'uvch264src.vfsrc ! image/jpeg,framerate=30/1 ! '
            'fakesink sync=0 qos=0 async=0 '
            'uvch264src.vidsrc ! '
            'video/x-h264, stream-format=byte-stream, width=1280, height=720, alignment=au, profile=constrained-baseline, framerate=30/1 ! '
            'h264parse config-interval=-1 ! '
            'rtph264pay mtu=4194304 ! '
            'shmsink socket-path=%s async=0 qos=0 sync=0 wait-for-connection=0 shm-size=33554432'
            % vidsocket))

    def rpicamsrc(self, vidsocket):
        return Gst.parse_launch((
            'rpicamsrc do-timestamp=1 rotation=180 preview=0 bitrate=0 sensor-mode=5 quantisation-parameter=20 name=rpicamsrc ! '
            'video/x-h264, stream-format=byte-stream, width=1280, height=720, alignment=nal, profile=baseline, framerate=0/1 ! '
            'h264parse config-interval=-1 ! '
            'video/x-h264,stream-format=byte-stream,alignment=au ! '
            'rtph264pay mtu=4194304 ! '
            'shmsink socket-path=%s async=0 qos=0 sync=0 wait-for-connection=0 shm-size=33554432'
            % vidsocket))

    def initialize_streams(self, vidsrc, sndsrc):
        if sndsrc:
            self.save = Gst.parse_launch((
                '%s ! h264parse config-interval=-1 ! mux.video '
                '%s ! queue ! mux.audio_0 '
                ''
                'splitmuxsink name=mux async=0 sync=0 qos=0 max-size-time=900000000000 '
                % (vidsrc, sndsrc)))
        else:
            self.save = Gst.parse_launch((
                '%s ! h264parse config-interval=-1 ! mux.video '
                'splitmuxsink name=mux async=0 sync=0 qos=0 max-size-time=900000000000 ' % vidsrc))

        # stream has do-timestamp=1 now, sadly.. hope nothing breaks!
        if sndsrc:
            self.stream = Gst.parse_launch((
                '%s ! h264parse ! queue ! mux.video '
                '%s ! queue ! mux.audio '
                'flvmux name=mux streamable=true ! '
                'rtmpsink name=rtmpsink0 qos=0 sync=0 async=0'
                % (vidsrc, sndsrc)))
        else:
            self.stream = Gst.parse_launch((
                '%s ! h264parse ! queue ! mux.video '
                'flvmux name=mux streamable=true ! '
                'rtmpsink name=rtmpsink0 qos=0 sync=0 async=0'
                % vidsrc))

    def initialize_rtsp(self, rtsp, vidsrc, sndsrc):
        vidpipe = vidsrc + ', framerate=30/1 ! h264parse ! queue ! rtph264pay name=pay0'
        if sndsrc:
            sndpipe = sndsrc + ' ! queue ! rtpmp4apay name=pay1'
        else:
            sndpipe = ''

        full_stream = GstRtspServer.RTSPMediaFactory()
        #full_stream.set_shared(True)
        full_stream.set_latency(100)
        full_stream.set_suspend_mode(GstRtspServer.RTSPSuspendMode.NONE)
        full_stream.set_eos_shutdown(False)
        full_stream.set_launch(vidpipe + ' ' + sndpipe)
        full_stream.connect('media-configure', self.media_configure)
        rtsp.get_mount_points().add_factory('/%s' % self.name, full_stream)

        vidonly_stream = GstRtspServer.RTSPMediaFactory()
        #vidonly_stream.set_shared(True)
        vidonly_stream.set_latency(100)
        vidonly_stream.set_suspend_mode(GstRtspServer.RTSPSuspendMode.NONE)
        vidonly_stream.set_eos_shutdown(False)
        vidonly_stream.set_launch(vidpipe)
        vidonly_stream.connect('media-configure', self.media_configure)
        rtsp.get_mount_points().add_factory('/%s.m4v' % self.name, vidonly_stream)

    def media_configure(self, mediafactory, media):
        print("Request for media configure\n")

        bin = media.get_element()
        camsrc = bin.get_by_name('camsrc')

        print('Camsrc: ', camsrc)
        print('Bus: ', camsrc.get_bus())

    def cam_message(self, obj, event):
        if event.src == self.cam:
            if event.type == Gst.MessageType.STATE_CHANGED or \
               event.type == Gst.MessageType.ASYNC_DONE:
                if event.type == Gst.MessageType.STATE_CHANGED:
                    prev, new, pending = event.parse_state_changed()

                    if prev == Gst.State.PLAYING and self.timer > 0:
                        GLib.source_remove(self.timer)
                        self.timer = 0
                else:
                    new = event.src.get_state(0)[0]
                    pending = event.src.get_state(0)[1]

                if pending == Gst.State.VOID_PENDING:
                    print("New state: %s " % new)
                    if new == Gst.State.NULL:
                        shmsink = self.cam.get_by_name('shmsink')
                        _unlink(shmsink.get_property('socket-path'))

                    if new == Gst.State.PLAYING and self.timer <= 0:
                        self.timer = GLib.timeout_add_seconds(3, self.send_keyframe)
            elif event.type == Gst.MessageType.EOS:
                self.shutdown()
            else:
                print('Camera event: ', event.type)
        return

    def send_keyframe(self):
        ev = GstVideo.video_event_new_upstream_force_key_unit(Gst.CLOCK_TIME_NONE, True, self.key_count)
        self.key_count += 1

        sink = self.cam.get_by_name('rpicamsrc')
        if not sink:
            sink = self.cam.get_by_name('uvch264src')

        sink.send_event(ev)

        return True

    def save_message(self, obj, event):
        if event.src == self.save:
            if event.type == Gst.MessageType.STATE_CHANGED:
                prev, new, pending = event.parse_state_changed()
                if pending == Gst.State.VOID_PENDING:
                    print("New recording state: %s " % new)
                elif pending == Gst.State.PLAYING and new == Gst.State.READY:
                    self.send_keyframe()
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
                elif pending == Gst.State.PLAYING and new == Gst.State.READY:
                    self.send_keyframe()
            else:
                print('Streaming event: ', event.type)
        else:
            if event.type == Gst.MessageType.ERROR:
                gthing, debug = event.parse_error()
                print('Streaming error: ', gthing, debug)
            elif event.type == Gst.MessageType.WARNING:
                gthing, debug = event.parse_warning()
                print('Streaming event warning: ', gthing, debug)
            else:
                print('Streaming element event: ', event.type)

    def save_location(self, splitmux, fragment_id):
        file = time.strftime('~/' + self.name + '-video-%Y-%02m-%02d-%02H-%02M.mp4')

        return os.path.expanduser(file)

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
        self.cam.get_bus().add_signal_watch()

        self.save.get_by_name("mux").connect("format-location", self.save_location)
        self.save.get_bus().connect("message", self.save_message)
        self.save.get_bus().add_signal_watch()

        self.stream.get_bus().connect("message", self.stream_message)
        self.stream.get_bus().add_signal_watch()

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
            if not args or not '=' in args or ' ' in args:
                socket.send(b'Syntax: setprop key=value\n')
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

