#!/usr/bin/python3

import smbus, gi, server, time, wiringpi
from contextlib import suppress

gi.require_version('GLib', '2.0')
from gi.repository import GObject, GLib

class sht3x:
	def __init__(self, bus, addr=0x44):
		self.bus = bus
		self.addr = addr

		# Clear status reg
		bus.write_i2c_block_data(addr, 0x30, [0x41])

	def read_temp(self, celsius=True):
		self.bus.write_i2c_block_data(self.addr, 0x24, [0x00])

		time.sleep(.15)

		data = self.bus.read_i2c_block_data(self.addr, 0x24, 6)

		humidity = int(round(100. * (data[3] * 256 + data[4]) / 65535.))

		temp = data[0] * 256 + data[1]
		if (celsius):
			temp = -45 + (175 * temp / 65535.)
		else:
			temp = -49 + (315 * temp / 65535.)

		return temp, humidity

class bh1750fvi:
	def __init__(self, bus, addr=0x23):
		self.bus = bus
		self.addr = addr

		# Power on
		bus.write_byte(addr, 1)

	def read_light(self):
		# Read one time high res mode 2 (0x21)
		val = self.bus.read_i2c_block_data(self.addr, 0x21, 2)

		return int(round((val[1] + val[0] * 256) / 1.2))

class tsl2561:
	def __init__(self, bus, addr=0x39):
		self.bus = bus
		self.addr = addr

		# Power on and set default gain/timing
		bus.write_i2c_block_data(self.addr, 0x80, [3])

		self.set_param(2, 16)

	def set_param(self, time, gain):
		#gain  0: 0x00
		#gain 16: 0x10

		#time = 0x0 -> 13 ms
		#time = 0x1 -> 101 ms
		#time = 0x2 -> 402 ms

		param = time + gain

		self.bus.write_i2c_block_data(self.addr, 0x81, [param])
		self.gain = gain
		self.time = time

	def read_light(self):
		bb = self.bus.read_word_data(self.addr, 0xac)
		ir = self.bus.read_word_data(self.addr, 0xae)

		scale = 1.
		if self.gain:
			scale /= self.gain

		if not self.time:
			scale /= .013
		elif self.time == 1:
			scale /= .101
		else:
			scale /= .403

		return (bb + ir) * scale

class monitor:
	def __init__(self, server, light):
		self.light = light
		self.server = server
		self.mode = -2

	def set_mode(self, mode):
		if self.mode == mode:
			return

		if mode == 2:
			for cam in self.server.cams:
				cam.day_mode()
		elif mode == 1:
			for cam in self.server.cams:
				cam.shimmer_mode()
		else:
			for cam in self.server.cams:
				if self.mode > 0:
					cam.night_mode()
				prop = cam.cam.get_by_name('rpicamsrc')
				if prop:
					prop.set_property('shutter-speed', 1000000 if mode < 0 else 250000)

		self.mode = mode

	def update(self):
		lux = self.light.read_light()

		if lux < 1:
			mode = -1
		elif lux < 10:
			mode = 0
		elif lux < 300:
			mode = 1
		else:
			mode = 2

		self.set_mode(mode)

def update_text(cam, light, temp, monitor):
	try:
		[ t, rh ] = temp.read_temp()
		l = light.read_light()
		s = wiringpi.digitalRead(2)

		txt = 't = %.1f - LV = %.0f%% - Lux %i - Stroomklok: %s' % (t, rh, l, "aan" if s else "uit")
		mode = '1'
	except OSError:
		txt = ''
		mode = '0'

	cam.setprop('annotation-text', txt)
	cam.setprop('annotation-mode', mode)
	cam.setprop('annotation-text-colour', '1077264') #107010

	monitor.update()

	return True

if __name__ == '__main__':
	main = server.Controller()
	main.add_camera('cam1', 'uvch264src')
	cam3 = main.add_camera('cam3', 'rpicamsrc')

	#with suppress(OSError):
	if True:
		bus = smbus.SMBus(1)

		wiringpi.wiringPiSetup()

		# Probe for BH1750-FVI
		light = bh1750fvi(bus)

		# Probe for sht3x
		temp = sht3x(bus)

		# Use tsl2561 for choosing day/night mode..
		light2 = tsl2561(bus)
		monitor = monitor(main, light2)

		GLib.timeout_add_seconds(1, update_text, cam3, light, temp, monitor)

	main.run()
