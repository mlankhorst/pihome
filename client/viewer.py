#!/usr/bin/python3

import sys, gi, argparse

gi.require_version('Gst', '1.0')
gi.require_version('GstBase', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gst, GstBase, GLib

class Viewer:
    def __init__(self):
        Gst.init(sys.argv)
        self.mainloop = GLib.MainLoop()

        self.pipeline = Gst.parse_launch(self.parse_args())

        bus = self.pipeline.get_bus()
        bus.connect('message', self.message)
        bus.add_signal_watch()

        rtpbin = self.pipeline.get_by_name('rtpsession')
        rtpbin.connect('request-pt-map', self.request_pt_map)

    def parse_args(self):
        parser = argparse.ArgumentParser(description='A viewer for pihome')
        parser.add_argument('-p', '--preset', nargs=1, help='What preset to use (sets server/multicast/ports): cam1, cam2 or cam3')
        parser.add_argument('-a', '--no-audio', action='store_true', help='Disable audio for this stream')
        parser.add_argument('-v', '--no-video', action='store_true', help='Disable video for this stream')
        parser.add_argument('-s', '--server', nargs=1, help='Server address to use')
        parser.add_argument('-m', '--multicast', nargs=1, help='Multicast address to use for receiving (RTP + RTCP)')
        parser.add_argument('-A', '--audio-port', nargs=1, type=int, help='RTP audio port to use (RTCP port = audio port + 1)')
        parser.add_argument('-V', '--video-port', nargs=1, type=int, help='RTP video port to use (RTCP port = video port + 1)')

        # Ignore gstreamer options
        args, unk = parser.parse_known_args()

        if args.preset:
            preset = args.preset[len(args.preset)-1]
            if preset == 'cam1':
                args.audio_port = 2216
                args.video_port = 2214
                args.multicast = '224.1.1.4'
                if not args.server:
                    args.server = 'cam3'
            elif preset == 'cam2':
                args.audio_port = 2226
                args.video_port = 2224
                args.multicast = '224.2.2.4'
                if not args.server:
                    args.server = 'tegra-ubuntu'
            elif preset == 'cam3':
                args.audio_port = 2236
                args.video_port = 2234
                args.multicast = '224.3.3.4'
                if not args.server:
                    args.server = 'cam3'
            else:
                print('%s: Invalid preset "%s"\n' % (sys.argv[0], args.preset), file=sys.stderr)
                sys.exit(1)

        if args.no_audio and args.no_video:
            print(sys.argv[0] + ': Why run with no audio and no video?\n', file=sys.stderr)
            sys.exit(1)

        if not args.server:
            print(sys.argv[0] + ': Missing server specification\n', file=sys.stderr)
            parser.print_usage(file=sys.stderr)
            sys.exit(1)

        if not args.multicast:
            args.multicast = args.server

        if not args.video_port and not args.no_video:
            print(sys.argv[0] + ': No video port specified\n', file=sys.stderr)
            parser.print_usage(file=sys.stderr)
            sys.exit(1)

        if not args.audio_port and not args.no_audio:
            print(sys.argv[0] + ': No audio port specified\n', file=sys.stderr)
            parser.print_usage(file=sys.stderr)
            sys.exit(1)

        audio_index=1
        if args.no_video:
            audio_index=0

        rtpbin="rtpbin name=rtpsession"

        if not args.no_video:
            video = (
            "udpsrc name=rtpvidsrc port=%d address=%s ! rtpsession.recv_rtp_sink_0 "
            "rtpsession. ! rtph264depay ! decodebin ! autovideosink sync=false "
            " "
            "rtpsession.send_rtcp_src_0 ! udpsink host=%s port=%d auto-multicast=true qos=false sync=false async=false name=rtcpvidsink "
            "udpsrc name=rtcpvidsrc address=%s port=%d ! rtpsession.recv_rtcp_sink_0 " %
            (args.video_port, args.multicast,
             args.server, args.video_port + 1,
             args.multicast, args.video_port + 1))
        else:
            video = ""

        if not args.no_audio:
            audio = (
            "udpsrc name=rtpaudsrc port=%d address=%s ! rtpsession.recv_rtp_sink_%d "
            "rtpsession. ! rtpmpadepay ! decodebin ! autoaudiosink sync=false "
            " "
            "rtpsession.send_rtcp_src_%d ! udpsink host=%s port=%d auto-multicast=true qos=false sync=false async=false name=rtcpaudsink "
            "udpsrc name=rtcpaudsrc address=%s port=%d ! rtpsession.recv_rtcp_sink_%d" %
            (args.audio_port, args.multicast, audio_index,
             audio_index, args.server, args.audio_port + 1,
             args.multicast, args.audio_port + 1, audio_index))
        else:
            audio=""

        return "%s %s %s" % (rtpbin, video, audio)

    def request_pt_map(self, ptdemux, session, pt):
        if pt == 14:
            return Gst.Caps.from_string('application/x-rtp,media=audio,clock-rate=90000,encoding-name=MPA,payload=%d' % pt)
        if pt == 96:
            return Gst.Caps.from_string('application/x-rtp,media=video,clock-rate=90000,encoding-name=H264,payload=%d' % pt)

        print("Unknown pt ", pt)
        sys.exit(1)

    def message(self, obj, event):
        if event.src != self.pipeline:
            if event.type == Gst.MessageType.ERROR:
                print('Error from %s: ' % event.src.name, event.parse_error())
                self.shutdown()
                return

            if event.type == Gst.MessageType.STATE_CHANGED or \
               event.type == Gst.MessageType.ASYNC_DONE or \
               event.type == Gst.MessageType.TAG or \
               event.type == Gst.MessageType.STREAM_STATUS or \
               event.type == Gst.MessageType.ELEMENT:
                return

            print('Event from %s: ' % event.src.name, event.type)
            return

        if event.type == Gst.MessageType.STATE_CHANGED or \
            event.type == Gst.MessageType.ASYNC_DONE:
            if event.type == Gst.MessageType.STATE_CHANGED:
                prev, new, pending = event.parse_state_changed()
            else:
                new = event.src.get_state(0)[0]
                pending = event.src.get_state(0)[1]

            if pending == Gst.State.VOID_PENDING:
                print("New state: %s " % new)
        elif event.type == Gst.MessageType.EOS:
            self.shutdown()
        else:
            print('Streaming event: ', event.type)

    def run(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        self.mainloop.run()

    def shutdown(self):
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.get_state(2000000000)
        self.mainloop.quit()

if __name__ == '__main__':
    main = Viewer()
    main.run()

