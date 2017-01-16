#!/usr/bin/python3

import sys, gi, os, socket

gi.require_version('Gst', '1.0')
gi.require_version('GstBase', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import GObject, Gst, GstBase, GLib, GObject

def _unlink(what):
    try:
        os.unlink(what)
    except FileNotFoundError:
        return

class Camera:
    def __init__(self, cam, save):
        self.cam = cam
        self.save = save

    def cam_message(self, obj, event):
        if event.src == self.cam:
            if event.type == Gst.MessageType.STATE_CHANGED:
                prev, new, pending = event.parse_state_changed()
                if pending == Gst.State.VOID_PENDING:
                    print("New state: %s " % new)
            elif event.type == Gst.MessageType.EOS:
                self.shutdown()
            else:
                print(event.type)
        return

    def save_message(self, obj, event):
        if event.src == self.save:
            print(event)
        return

    def stoprecord(self):
        if self.save.get_state(0)[1] > Gst.State.NULL:
            self.save.emit('event', Gst.event_new_eos())

    def shutdown(self):
        self.stoprecord()
        self.cam.set_state(Gst.State.NULL)

    def run(self):
        self.cam.get_bus().connect("message", self.cam_message)
        self.save.get_bus().connect("message", self.save_message)

        self.cam.set_state(Gst.State.PLAYING)

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

        GLib.io_add_watch(self.socket.fileno(),
                          GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                          self.server_msg)

        _unlink("/tmp/cam1v")
        _unlink("/tmp/cam3v")
        _unlink("/tmp/snd.mp3")

        save1 = Gst.parse_launch((
             "shmsrc name=camsrc is-live=0 do-timestamp=true socket-path=/tmp/cam1v ! "
             "video/x-h264,stream-format=byte-stream,alignment=au,profile=high,width=1280,height=720 ! "
             "h264parse config-interval=-1 ! mp4mux name=mux ! filesink name=file async=0 sync=0 qos=0 "
             "shmsrc socket-path=/tmp/snd.mp3 do-timestamp=1 is-live=1 ! "
             "audio/mpeg, mpegversion=1, layer=3, rate=44100, channels=2 ! mpegaudioparse ! queue ! mux."))

        save3 = Gst.parse_launch((
             "shmsrc name=camsrc is-live=0 do-timestamp=true socket-path=/tmp/cam3v ! "
             "video/x-h264,stream-format=byte-stream,alignment=au,profile=high,width=1280,height=720 ! "
             "h264parse config-interval=-1 ! mp4mux name=mux ! filesink name=file async=0 sync=0 qos=0 "
             "shmsrc socket-path=/tmp/snd.mp3 do-timestamp=1 is-live=1 ! "
             "audio/mpeg, mpegversion=1, layer=3, rate=44100, channels=2 ! mpegaudioparse ! queue ! mux."))

        cam1 = Gst.parse_launch((
             "uvch264src auto-start=true mode=2 rate-control=vbr "
                        "iframe-period=2000 post-previews=false "
                        "initial-bitrate=2000000 peak-bitrate=4500000 "
                        "average-bitrate=3000000 name=src do-timestamp=1"
             "src.vfsrc ! image/jpeg,framerate=30/1 ! fakesink sync=false async=false qos=false "
             "src.vidsrc ! video/x-h264,width=1280,height=720,framerate=30/1,stream-format=byte-stream ! "
             "tee name = t1 ! pay. "
             "t1. ! shmsink socket-path=/tmp/cam1v async=0 qos=0 sync=0 wait-for-connection=0"
             " "
             "rtpbin name=rtpbin do-retransmission=true"
             " "
             "rtph264pay name=pay config-interval=1 ! rtpbin.send_rtp_sink_0"
             " "
             "shmsrc socket-path=/tmp/snd.mp3 do-timestamp=1 !"
             "audio/mpeg,mpegversion=1 ! mpegaudioparse ! queue ! rtpmpapay ! rtpbin.send_rtp_sink_1"
             " "
             "rtpbin.send_rtp_src_0 ! udpsink host=224.1.1.4 port=2214 auto-multicast=true qos=0 sync=0 "
             "rtpbin.send_rtcp_src_0 ! udpsink host=224.1.1.4 port=2215 qos=0 sync=0 "
             "udpsrc address=0.0.0.0 port=2215 ! rtpbin.recv_rtcp_sink_0 "
             " "
             "rtpbin.send_rtp_src_1 ! udpsink host=224.1.1.4 port=2216 auto-multicast=true qos=0 sync=0 "
             "rtpbin.send_rtcp_src_1 ! udpsink host=224.1.1.4 port=2217 auto-multicast=true qos=0 sync=0 "
             "udpsrc address=0.0.0.0 port=2217 ! rtpbin.recv_rtcp_sink_1"))

        cam3 = Gst.parse_launch((
             "rpicamsrc name=camsrc do-timestamp=true hflip=1 vflip=1 preview=0 ! "
             "video/x-h264,width=1280,height=720,framerate=1/60,profile=high ! "
             "h264parse config-interval=1 ! "
             "video/x-h264,stream-format=byte-stream,alignment=au ! "
             "tee name=t1 ! pay. "
             "t1. ! shmsink socket-path=/tmp/cam3v async=0 qos=0 sync=0 wait-for-connection=0"
             " "
             "rtpbin name=rtpbin do-retransmission=true"
             " "
             "rtph264pay name=pay config-interval=1 ! rtpbin.send_rtp_sink_0"
             " "
             "shmsrc socket-path=/tmp/snd.mp3 do-timestamp=1 !"
             "audio/mpeg,mpegversion=1 ! mpegaudioparse ! queue ! rtpmpapay ! rtpbin.send_rtp_sink_1"
             " "
             "rtpbin.send_rtp_src_0 ! udpsink host=224.3.3.4 port=2234 auto-multicast=true qos=0 sync=0 "
             "rtpbin.send_rtcp_src_0 ! udpsink host=224.3.3.4 port=2235 qos=0 sync=0 "
             "udpsrc address=0.0.0.0 port=2235 ! rtpbin.recv_rtcp_sink_0 "
             " "
             "rtpbin.send_rtp_src_1 ! udpsink host=224.3.3.4 port=2236 auto-multicast=true qos=0 sync=0 "
             "rtpbin.send_rtcp_src_1 ! udpsink host=224.3.3.4 port=2237 auto-multicast=true qos=0 sync=0 "
             "udpsrc address=0.0.0.0 port=2237 ! rtpbin.recv_rtcp_sink_1"))

        self.snd = Gst.parse_launch((
             "pulsesrc latency-time=30000 buffer-time=180000 do-timestamp=1 ! "
             "audio/x-raw, format=S16LE, rate=44100, channels=2 ! "
             "lamemp3enc ! shmsink wait-for-connection=0 socket-path=/tmp/snd.mp3 shm-size=4194304 sync=0 async=0 qos=0"))

        self.cam1 = Camera(cam1, save1)
        self.cam3 = Camera(cam3, save3)

        cam1.get_bus().connect("message", self.cam1_message)
        cam3.get_bus().connect("message", self.cam3_message)
        self.snd.get_bus().connect("message", self.snd_message)

        for pipeline in [self.snd, cam1, cam3, save1, save3]:
            pipeline.get_bus().add_signal_watch()

    def cam1_message(self, obj, event):
        if event.src == self.cam1.cam:
            if event.type == Gst.MessageType.STATE_CHANGED:
                prev, new, pending = event.parse_state_changed()
                if pending == Gst.State.VOID_PENDING:
                    if new == Gst.State.NULL:
                        _unlink("/tmp/cam1v")

    def cam3_message(self, obj, event):
        if event.src == self.cam3.cam:
            if event.type == Gst.MessageType.STATE_CHANGED:
                prev, new, pending = event.parse_state_changed()
                if pending == Gst.State.VOID_PENDING:
                    if new == Gst.State.NULL:
                        _unlink("/tmp/cam3v")

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
                print('Bla bla: %s' % str)
                ba = ba[nl+1:]
                nl = ba.find(b'\n')

            self.savemsgs[source] = ba

        if cond & (GLib.IO_ERR | GLib.IO_HUP):
            socket.close()
            del self.conns[source]
            del self.savemsgs[source]
            return False

        return True

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
