#!/usr/bin/python3

import sys, gi, os, socket, time, subprocess, psutil

from cam import Camera

gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import GObject, Gst, GstRtspServer, GLib, GObject

def _unlink(what):
    try:
        os.unlink(what)
    except FileNotFoundError:
        return

class Controller:
    def __init__(self, sound='aac'):
        Gst.init(sys.argv)
        self.mainloop = GLib.MainLoop()
        self.socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('', 6780))
        self.socket.listen(8)
        self.socket.setblocking(0)
        self.conns = {}
        self.savemsgs = {}
        self.rtsp_server = GstRtspServer.RTSPServer.new()
        self.rtsp_server.set_service('8080')
        self.rtsp_server.set_address('::')
        self.rtsp_server.attach(None)

        GLib.io_add_watch(self.socket.fileno(),
                          GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                          self.server_msg)

        _unlink("/tmp/snd.m4a")
        _unlink("/tmp/snd.mp3")

        if sound == 'aac':
            self.use_aac()
        elif sound == 'mp3':
            self.use_mp3()
        else:
            self.no_sound()

        self.cams = []

    def add_camera(self, name, type):
        cam = Camera(name, { 'rtsp' : self.rtsp_server, 'audio_pipe' : self.audio_pipe, 'audiopay' : self.audiopay, 'video_source' : type})
        self.cams.append(cam)

        return cam

    def snd_message(self, obj, event):
        if event.src == self.snd:
            if event.type == Gst.MessageType.STATE_CHANGED:
                prev, new, pending = event.parse_state_changed()
                if pending == Gst.State.VOID_PENDING:
                    print("New state: %s" % new)
                    if new == Gst.State.PLAYING:
                        for cam in self.cams:
                            cam.run()
                    elif new == Gst.State.NULL:
                        _unlink("/tmp/snd.m4a")
                        _unlink("/tmp/snd.mp3")

    def server_msg(self, source, cond):
        if (cond & GLib.IO_IN):
            client, addr = self.socket.accept()
            client.setblocking(0)
            self.conns[client.fileno()] = client
            self.savemsgs[client.fileno()] = None
            GLib.io_add_watch(client.fileno(),
                              GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                              self.client_msg)
            print("New client from ", addr)
        else:
            print("cond: %x\n" % cond)

        return True

    def client_msg(self, source, cond):
        socket = self.conns[source]

        if cond & GLib.IO_IN:
            ba = socket.recv(4096)
            if not ba:
                cond |= GLib.IO_HUP

            if self.savemsgs[source]:
                ba = self.savemsgs[source] + ba

            nl = ba.find(b'\n')
            while nl >= 0:
                str = ba[0:nl].decode(errors='replace')
                self.run_command(socket, str)
                ba = ba[nl+1:]
                nl = ba.find(b'\n')

            self.savemsgs[source] = ba

        if cond & (GLib.IO_ERR | GLib.IO_HUP):
            socket.close()
            del self.conns[source]
            del self.savemsgs[source]
            return False

        return True

    def run_command(self, socket, str):
        if str.startswith(':'):
            name, cmd = str.split(' ', 1)
            name = name[1:]

            for cam in self.cams:
                if cam.name == name:
                    cam.run_command(socket, cmd)
                    return
            socket.send(b'Invalid camera ' + name.encode() + b'\n')
        elif str:
            for cam in self.cams:
                cam.run_command(socket, str)
        else:
            socket.send(b'Usage: (:camera) <command>\n')
        return

    def shutdown(self):
        for cam in self.cams:
            cam.shutdown()

        self.snd.set_state(Gst.State.NULL)

        self.mainloop.quit()

        self.socket.close()

        for socket in self.conns:
            socket.close()

        self.conns = {}
        self.savemsgs = {}

    def create_stream(self, ext, shared):
        sound_stream = GstRtspServer.RTSPMediaFactory()
        sound_stream.set_shared(shared)
        sound_stream.set_latency(100)
        sound_stream.set_launch(self.audio_pipe + ' ! queue ! ' + self.audiopay + ' name=pay0')
        self.rtsp_server.get_mount_points().add_factory('/snd.' + ext, sound_stream)
        self.rtsp_server.get_mount_points().add_factory('/snd', sound_stream)

    def use_aac(self):
        self.snd = Gst.parse_launch((
            "alsasrc latency-time=32000 buffer-time=256000 do-timestamp=1 device=hw:CARD=C920 ! "
            "audio/x-raw, format=S16LE, rate=32000, channels=2 ! "
            "voaacenc bitrate=64000 ! audio/mpeg, mpegversion=4, stream-format=raw ! aacparse ! "
            "rtpmp4apay ! application/x-rtp, clock-rate=32000, payload=96 ! "
            "shmsink wait-for-connection=0 socket-path=/tmp/snd.m4a shm-size=4194304 sync=0 async=0 qos=0"))
        self.audio_pipe = (
            'shmsrc socket-path=/tmp/snd.m4a is-live=1 do-timestamp=1 ! '
            'application/x-rtp, clock-rate=32000, payload=96 ! rtpmp4adepay ! '
            'audio/mpeg, mpegversion=4, stream-format=raw, codec_data=(buffer)1290, rate=32000 ! '
            'aacparse')
        self.audiopay = 'rtpmp4apay'
        self.create_stream('m4a', False)

    def use_mp3(self):
        self.snd = Gst.parse_launch((
            "pulsesrc latency-time=30000 buffer-time=180000 do-timestamp=1 ! "
            "audio/x-raw, format=S16LE, rate=44100, channels=2 ! "
            "lamemp3enc ! audio/mpeg ! mpegaudioparse ! "
            "shmsink wait-for-connection=0 socket-path=/tmp/snd.mp3 shm-size=4194304 sync=0 async=0 qos=0"))
        self.audio_pipe = (
            'shmsrc socket-path=/tmp/snd.mp3 is-live=1 do-timestamp=1 ! '
            'audio/mpeg, mpegversion=1, layer=3, rate=44100 ! '
            'mpegaudioparse')
        self.audiopay = 'rtpmpapay'
        self.create_stream('mp3', True)

    def no_sound(self):
        self.snd = None
        self.audio_pipe = None
        self.audiopay = None

    def run(self):
        if self.snd:
            self.snd.get_bus().connect("message", self.snd_message)
            self.snd.get_bus().add_signal_watch()
            self.snd.set_state(Gst.State.PLAYING)
        else:
            for cam in self.cams:
                cam.run()

        self.mainloop.run()

if __name__ == '__main__':
    sound = None
    for x in os.listdir('/sys/class/sound/'):
        if x.startswith('pcm') and x.endswith('c'):
            sound = 'aac' if psutil.cpu_count() > 1 else 'mp3'

    main = Controller(sound = sound)
    if socket.gethostname() == 'raspberry':
        main.add_camera('cam', 'rpicamsrc')
    elif socket.gethostname() == 'cam1':
        main.add_camera('cam2', 'libcamerasrc')
    elif socket.gethostname() == 'cam0':
        main.add_camera('cam0', 'libcamerasrc')
        main.add_camera('cam1', 'uvch264src')
    elif socket.gethostname() == 'cam4':
        main.add_camera('cam4', 'uvch264src')
    elif socket.gethostname() == 'cam5':
        main.add_camera('cam5', 'rpicamsrc')

    main.run()
