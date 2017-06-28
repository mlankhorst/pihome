#!/usr/bin/python3

import smbus, gi, server, time
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
		# Read high res mode 2

		self.bus.write_byte(self.addr, 0x21)

		time.sleep(.12)

		val = [ self.bus.read_byte(self.addr) for x in range(2) ]

		return int(round((val[1] + val[0] * 256) / 1.2))

def update_text(cam, light, temp):
	try:
		[ t, rh ] = temp.read_temp()
		l = light.read_light()

		txt = 't = %.1f - LV = %.0f%% - Lux %i' % (t, rh, l)
		mode = '1'
	except OSError:
		txt = ''
		mode = '0'

	cam.setprop('annotation-text', txt)
	cam.setprop('annotation-mode', mode)
	cam.setprop('annotation-text-colour', '1077264') #107010

	return True

if __name__ == '__main__':
	main = server.Controller()
	main.add_camera('cam1', 'uvch264src')
	cam3 = main.add_camera('cam3', 'rpicamsrc')

	with suppress(OSError):
		bus = smbus.SMBus(1)

		# Probe for BH1750-FVI
		light = bh1750fvi(bus, addr=0x23)

		# Probe for sht3x
		temp = sht3x(bus, addr=0x44)

		GLib.timeout_add_seconds(1, update_text, cam3, light, temp)

	main.run()
