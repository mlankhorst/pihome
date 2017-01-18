#!/usr/bin/python3

import sys, gi, os, socket, time, subprocess

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
        return

    def startrecord(self):
        if self.save.get_state(0)[1] != Gst.State.NULL:
            return

        filename = time.strftime('/home/pi/video-%Y-%02m-%02d-%02H-%02M.mp4')
        filesink = self.save.get_by_name('file')
        filesink.set_property('location', filename)

        self.save.set_state(Gst.State.PLAYING)

    def stoprecord(self):
        if self.save.get_state(0)[1] > Gst.State.NULL:
            self.save.send_event(Gst.Event.new_eos())

    def shutdown(self):
        self.stoprecord()
        self.cam.set_state(Gst.State.NULL)

    def run(self):
        self.cam.get_bus().connect("message", self.cam_message)
        self.save.get_bus().connect("message", self.save_message)

        self.cam.set_state(Gst.State.PLAYING)

    def night_mode(self):
        cam = self.cam.get_by_name('uvch264src')
        if cam:
            dev = cam.get_property('device')

            subprocess.call(['v4l2-ctl', '-d', dev, '-c',
                            ('brightness=140,saturation=140,contrast=0'
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
                            ('brightness=127,saturation=127,contrast=0'
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
                            ('brightness=127,saturation=127,contrast=0'
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
        else:
            socket.send(b'Unknown command: ' + cmd.split(' ', 1)[0].encode() + b'\n')
            return
        socket.send(b'OK\n')

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
                        "average-bitrate=3000000 name=uvch264src do-timestamp=1"
             "uvch264src.vfsrc ! image/jpeg,framerate=30/1 ! fakesink sync=false async=false qos=false "
             "uvch264src.vidsrc ! video/x-h264,width=1280,height=720,framerate=30/1,stream-format=byte-stream ! "
             "tee name = t1 ! pay. "
             "t1. ! h264parse ! shmsink socket-path=/tmp/cam1v async=0 qos=0 sync=0 wait-for-connection=0 name=shmsink"
             " "
             "rtpbin name=rtpbin do-retransmission=true"
             " "
             "h264parse name=pay ! rtph264pay config-interval=1 ! rtpbin.send_rtp_sink_0"
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
             "rpicamsrc name=rpicamsrc do-timestamp=true hflip=1 vflip=1 preview=0 ! "
             "video/x-h264,width=1280,height=720,framerate=0/1,profile=high ! "
             "h264parse config-interval=1 ! "
             "video/x-h264,stream-format=byte-stream,alignment=au ! "
             "tee name=t1 ! pay. "
             "t1. ! shmsink socket-path=/tmp/cam3v async=0 qos=0 sync=0 wait-for-connection=0 name=shmsink"
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
            return

    def cam3_message(self, obj, event):
        if event.src == self.cam3.cam:
            return

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
