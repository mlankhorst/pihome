#!/usr/bin/python3

import sys, gi, os, socket, time, subprocess

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
    def __init__(self):
        Gst.init(sys.argv)
        self.mainloop = GLib.MainLoop()
        self.socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        self.socket.bind(('', 6780))
        self.socket.listen(8)
        self.socket.setblocking(0)
        self.conns = {}
        self.savemsgs = {}
        self.rtsp_server = GstRtspServer.RTSPServer.new()
        self.rtsp_server.set_service('8080')
        self.rtsp_server.attach(None)

        GLib.io_add_watch(self.socket.fileno(),
                          GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                          self.server_msg)

        _unlink("/tmp/snd.m4a")

        self.snd = Gst.parse_launch((
             "pulsesrc latency-time=30000 buffer-time=180000 do-timestamp=1 ! "
             "audio/x-raw, format=S16LE, rate=44100, channels=2 ! "
             "voaacenc bitrate=64000 ! audio/mpeg, mpegversion=4, stream-format=raw ! "
             "shmsink wait-for-connection=0 socket-path=/tmp/snd.m4a shm-size=4194304 sync=0 async=0 qos=0"))

        audio_pipe = (
            'shmsrc socket-path=/tmp/snd.m4a is-live=1 do-timestamp=1 ! '
            'audio/mpeg, mpegversion=4, stream-format=raw, codec_data=(buffer)1210, channels=2, rate=44100')

        self.cam1 = Camera("cam1", { 'rtsp' : self.rtsp_server, 'audio_pipe' : audio_pipe, 'video_source' : 'uvch264src'})
        self.cam3 = Camera("cam3", { 'rtsp' : self.rtsp_server, 'audio_pipe' : audio_pipe, 'video_source' : 'rpicamsrc'})

        self.snd.get_bus().connect("message", self.snd_message)
        self.snd.get_bus().add_signal_watch()

        for cam in [self.cam1, self.cam3]:
            for pipeline in [cam.cam, cam.save, cam.stream]:
                pipeline.get_bus().add_signal_watch()

    def snd_message(self, obj, event):
        if event.src == self.snd:
            if event.type == Gst.MessageType.STATE_CHANGED:
                prev, new, pending = event.parse_state_changed()
                if pending == Gst.State.VOID_PENDING:
                    print("New state: %s" % new)
                    if new == Gst.State.PLAYING:
                        self.cam1.run()
                        self.cam3.run()
                    elif new == Gst.State.NULL:
                        _unlink("/tmp/snd.m4a")

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
            cam, cmd = str.split(' ', 1)
            if cam == ':cam1':
                self.cam1.run_command(socket, cmd)
            elif cam == ':cam3':
                self.cam3.run_command(socket, cmd)
            else:
                socket.send(b'Invalid camera ' + cam[1:].encode() + b'\n')
            return
        return

    def shutdown(self):
        self.cam1.shutdown()
        self.cam3.shutdown()

        self.snd.set_state(Gst.State.NULL)

        self.mainloop.quit()

        self.socket.close()

        for socket in self.conns:
            socket.close()

        self.conns = {}
        self.savemsgs = {}

    def run(self):
        self.snd.set_state(Gst.State.PLAYING)
        self.mainloop.run()

if __name__ == '__main__':
    main = Controller()
    main.run()
